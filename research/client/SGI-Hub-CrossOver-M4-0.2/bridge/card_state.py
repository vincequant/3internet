"""Five-card hands: static accessor + player screenshot aligned. Read-only."""
import json,os,time
from pathlib import Path
from collections import Counter
NAMES=json.loads(Path(__file__).with_name('card_catalog.json').read_text(encoding='utf8'))['names']
def decode_hand(raw):
 if len(raw)!=5:raise ValueError('Expected exactly five card slots')
 slots=[{'slot':i+1,'card_id':v,'name':'空槽' if v==0 else NAMES.get(str(v),f'未知卡牌 ID {v}'),'status':'empty' if v==0 else 'known' if str(v) in NAMES else 'unknown'} for i,v in enumerate(raw)]
 return {'slots':slots,'occupied_count':sum(v!=0 for v in raw),'known_count':sum(str(v) in NAMES for v in raw),'counts':[{'card_id':v,'name':NAMES.get(str(v),f'未知卡牌 ID {v}'),'count':n} for v,n in sorted(Counter(v for v in raw if v).items())],'verification':'lord+0x5e five u8 slots; getter 0x467bfc; enumerator 0x467c52; player screenshot order matches; enemy UI and consumption not tested','scope':'hand_slots; usability/pending diplomacy effects not included'}

class HandReader:
 def __init__(self):
  from collector import Collector,ROOT
  self.c=Collector();self.c.bind();self.last=None
  self.output=ROOT/'cards'/str(os.getpid());self.output.mkdir(parents=True,exist_ok=True)
 def close(self):self.c.close()
 def sample(self,identity):
  from collector import atomic_json,u16
  from datetime import datetime,timezone
  c=self.c
  if c.m.identity!=identity:raise ValueError('Card/game instance mismatch')
  start=time.perf_counter();c.cache.clear();c.headers=[];c.validate_core(c.core)
  objects,header=c.walk(0x4f4);forces={};reads=[]
  for _,a in objects:
   if c.read(a,4)!=bytes.fromhex('60665000'):raise ValueError('Unexpected force class')
   fid=u16(c.read(a+8,2),0);raw=c.read(a+0x5e,5)
   if fid in forces:raise ValueError('Duplicate force identity')
   forces[fid]=decode_hand(raw);reads.append((a,raw,fid))
  if any(c.m.read(a+0x5e,5)!=raw or c.m.read(a+8,2)!=fid.to_bytes(2,'little') for a,raw,fid in reads):raise ValueError('Cards changed during sample')
  if any(c.m.read(a,len(b))!=b for a,b in c.headers):raise ValueError('Force list changed during sample')
  now=datetime.now(timezone.utc).isoformat();result={'identity':identity,'captured_at':now,'readonly':True,'capture_ms':round((time.perf_counter()-start)*1000,3),'forces':forces}
  atomic_json(self.output/'latest.json',result)
  sig=json.dumps(forces,sort_keys=True,ensure_ascii=False)
  if sig!=self.last:
   with (self.output/'changes.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
   self.last=sig
  return result
