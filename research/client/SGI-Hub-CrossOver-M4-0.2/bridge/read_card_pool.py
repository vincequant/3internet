"""One-shot, identity-bound READ_PROCESS_MEMORY only. No game actions or writes."""
import json,os,sys,time,ntpath
from datetime import datetime,timezone
from collector import Collector
from card_pool import read_pool
def diplomacy_state(c,clock):
 from collector import LISTS,TYPES
 entities={};observed=[]
 for name in ('lords','generals','cities_and_barriers'):
  objects,_=c.walk(LISTS[name]);rows=[]
  for _,address in objects:
   row=c.decode(address);b=bytes.fromhex(row.pop('raw_hex'));row.pop('address',None)
   observed.append((address,b));rows.append(row)
  entities[name]=rows
 if any(c.m.read(a,len(b))!=b for a,b in observed) or any(c.m.read(a,len(b))!=b for a,b in c.headers):raise ValueError('策反资料在读取期间改变')
 return dict(entities=entities,identity=c.m.identity,core_address=hex(c.core),build_sha256=c.sha,clock_candidates={'raw_hex':clock.hex()})

def capture(request):
 identity=request['identity'];pid=identity['pid'];path=identity['path'];core=int(request['core_address'],16)
 if type(pid) is not int or pid<=0 or ntpath.basename(path).lower()!='sanpk.exe':raise ValueError('不是已绑定游戏实例')
 if not 0x10000<=core<0xffff0000:raise ValueError('核心地址无效')
 os.environ['SGI_GAME_EXE']=path;c=Collector(pid);start=time.perf_counter()
 try:
  if any(c.m.identity.get(k)!=identity.get(k) for k in ('pid','path','creation_filetime')):raise ValueError('游戏实例已改变')
  if c.sha!=request['build_sha256']:raise ValueError('游戏版本已改变')
  c.core=core;c.validate_core(core);clock=c.read(core+0x4cc,18)
  if request.get('clock_raw_hex') and clock.hex()!=request['clock_raw_hex']:raise ValueError('当前画面阶段已改变，请等待刷新')
  kind=request.get('kind','card_pool')
  if kind not in ('card_pool','diplomacy'):raise ValueError('读取类型无效')
  pool=read_pool(c) if kind=='card_pool' else None
  state=diplomacy_state(c,clock) if kind=='diplomacy' else None
  if c.m.read(core+0x4cc,18)!=clock:raise ValueError('阶段在读取期间改变')
  if pool is not None and pool.get('status')!='verified':raise ValueError(pool.get('reason','卡池未确认'))
  result=dict(identity=identity,core_address=request['core_address'],clock_raw_hex=clock.hex(),captured_at=datetime.now(timezone.utc).isoformat(),readonly=True,capture_ms=round((time.perf_counter()-start)*1000,2))
  result['card_pool' if kind=='card_pool' else 'diplomacy_state']=pool if kind=='card_pool' else state
  return result
 finally:c.close()
if __name__=='__main__':
 try:
  text=sys.stdin.read(8193)
  if len(text)>8192:raise ValueError('读取请求过长')
  print(json.dumps(capture(json.loads(text)),ensure_ascii=True))
 except Exception as e:print(json.dumps({'error':str(e)},ensure_ascii=True));sys.exit(1)
