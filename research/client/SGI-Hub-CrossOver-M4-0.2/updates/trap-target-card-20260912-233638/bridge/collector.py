"""SANPK 3.5 typed, read-only collector. No GUI imports or target writes.

Discovery reads permitted regions once. Warm captures follow validated MFC lists
and batch reads through a per-capture page cache. Outputs stay in this directory.
"""
from probe import Memory, ROOT
from objects import u16,u32
import argparse, collections, hashlib, json, os, statistics, struct, time
from datetime import datetime, timezone
from pathlib import Path

BUILD='c06ec3aa9c2b539e4111b53c57bed3717a2c0c73f3145aac4d55f66b2abb26cc'
SCHEMA='astra-sgi-core-2'
CORE_VT=0x5053c0; DOC_VT=0x504d40
TYPES={0x506660:('lord',273),0x5056f0:('general',96),0x503688:('city',81),0x5037d0:('barrier',64),0x507e10:('parade_ground',26),0x507ee8:('horse_farm',26),0x507fc0:('bow_studio',26)}
LISTS={'lords':0x4f4,'generals':0x514,'field_units':0x534,'cities_and_barriers':0x554,'unclassified_empty_574':0x574,'production_buildings':0x594,'unclassified_empty_5b4':0x5b4}
from state_extensions import UNIT_TYPES,extend_general,extend_force,decode_unit,enrich

def atomic_json(path,doc):
    tmp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    with tmp.open('w',encoding='utf8') as f:
        json.dump(doc,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

class Collector:
    def __init__(self,pid=26176,memory_factory=None,read_exe=None):
        self.m=None;self.cache={};self.headers=[];self.decode_warnings=[];self.core=None;self.sha=None
        try:
            self.m=(memory_factory or Memory)(pid)
            data=(read_exe or (lambda p:Path(p).read_bytes()))(self.m.identity['path'])
            sha=hashlib.sha256(data).hexdigest()
            if sha!=BUILD:raise RuntimeError('Unsupported executable build; rediscover layout before use')
            self.sha=sha
        except Exception:
            self.close();raise
    def close(self):
        self.core=None
        if getattr(self,'cache',None) is not None:self.cache.clear()
        if getattr(self,'headers',None) is not None:self.headers.clear()
        memory=getattr(self,'m',None);self.m=None
        if memory is not None:memory.close()
    def read(self,a,n):
        chunks=[]
        while n:
            page=a&~4095;offset=a-page;size=min(n,4096-offset)
            if page not in self.cache:
                b=self.m.read(page,4096)
                if b is None:raise RuntimeError(f'Unreadable page {page:x}')
                self.cache[page]=b
            chunks.append(self.cache[page][offset:offset+size]);a+=size;n-=size
        return b''.join(chunks)
    def text(self,p,max_bytes=96):
        if p<0x10000:raise ValueError('invalid string pointer')
        b=self.read(p,max_bytes);end=b.find(b'\0')
        if end<0:raise ValueError('unterminated string')
        try:return b[:end].decode('gbk')
        except UnicodeDecodeError:
            self.decode_warnings.append({'pointer':hex(p),'raw_hex':b[:end].hex(),'issue':'not_valid_gbk'});return None
    def validate_core(self,a):
        if u32(self.read(a,4),0)!=CORE_VT or u32(self.read(a-0x912,4),0)!=DOC_VT:raise ValueError('root vtable mismatch')
        if u32(self.read(a+LISTS['lords']+12,4),0)>256:raise ValueError('lord count out of safety bounds')
    def bind(self,discover=False):
        start=time.perf_counter()
        self.core=None;self.cache.clear();self.headers=[]
        if getattr(self.m,'segments',None) is not None:self.m.segments.clear()
        try:
            self.m.load();hits=self.m.find(struct.pack('<I',CORE_VT),1000);valid=[]
            for a in hits:
                if a<0x10000:continue
                try:self.validate_core(a);valid.append(a)
                except (ValueError,RuntimeError):pass
            if len(valid)==0:raise RuntimeError('Ambiguous/missing GameCore: 0')
            if len(valid)!=1:raise RuntimeError(f'Ambiguous/missing GameCore: {len(valid)}')
            self.core=valid[0]
            return {'mode':'one_pass_discovery','seconds':time.perf_counter()-start}
        finally:
            # Drop scan buffers after bind success or failure; keep only the chosen address.
            if getattr(self.m,'segments',None) is not None:self.m.segments.clear()
            self.cache.clear()
    def walk(self,offset,max_count=5000):
        address=self.core+offset;h=self.read(address,28);head,tail,count=struct.unpack_from('<III',h,4)
        if count>max_count:raise RuntimeError('container safety bound exceeded')
        self.headers.append((address,h));node=head;prev=0;seen=set();objects=[]
        for index in range(count):
            if not node or node in seen:raise RuntimeError('list short/cyclic')
            seen.add(node);nxt,back,obj=struct.unpack('<III',self.read(node,12))
            if back!=prev:raise RuntimeError('list backlink mismatch')
            objects.append((index,obj));prev,node=node,nxt
        if node or prev!=tail:raise RuntimeError('list tail/count mismatch')
        return objects,{'header':hex(address),'count':count,'head':hex(head),'tail':hex(tail),'structurally_valid':True}
    def decode(self,a):
        vt=u32(self.read(a,4),0)
        if vt in UNIT_TYPES:return decode_unit(a,self.read(a,168),vt)
        if vt not in TYPES:raise RuntimeError(f'Unexpected entity class {vt:x} at {a:x}')
        kind,size=TYPES[vt];b=self.read(a,size)
        r={'address':hex(a),'type':kind,'source_layer':'game_core','verification':'typed_container_structural','raw_hex':b.hex()}
        if kind=='lord':
            r.update(force_id=u16(b,8),name=self.text(u32(b,10)),ruler_general_id=u16(b,18),capital_city_id=u16(b,20),prestige=b[23],rice=u32(b,24),gold=u32(b,28),troop_stock={'infantry':u32(b,32),'cavalry':u32(b,38),'bow':u32(b,44)},armament_raw={'infantry':u16(b,36),'cavalry':u16(b,42),'bow':u16(b,48)},temporal_status='core_observed_now_effective_phase_unverified')
        else:
            r.update(world_xy_raw=list(struct.unpack_from('<hh',b,4)),owner_raw=u16(b,8))
            if kind=='general':
                r.update(general_id_raw=u16(b,10),surname=self.text(u32(b,12)),given_name=self.text(u32(b,16)),courtesy_name=self.text(u32(b,20)),birth_year_candidate=u16(b,30),soldiers=u16(b,35),attributes=dict(zip(['lead','war','intel','pol','cha'],b[37:42])))
                r['name']=r['surname']+r['given_name'] if r['surname'] is not None and r['given_name'] is not None else None;r['activity_status']='not_decoded'
            elif kind in ('city','barrier'):
                r.update(city_id=u16(b,10),name=self.text(u32(b,12)),defense=[u16(b,16),u16(b,18)])
                if kind=='city':r.update(population=u32(b,63),development=u16(b,67),commerce=u16(b,69))
            else:r['object_id_candidate']=u16(b,10)
        if kind=='general':extend_general(r,b)
        elif kind=='lord':
            extend_force(r)
            from card_state import decode_hand
            r['hand_cards']=decode_hand(b[0x5e:0x63])
        return r
    def capture(self):
        start=time.perf_counter();utc=datetime.now(timezone.utc).isoformat();c0=self.m.calls;b0=self.m.bytes
        self.cache.clear();self.headers=[];self.decode_warnings=[]
        if self.core is None:raise RuntimeError('no bound GameCore')
        try:self.validate_core(self.core)
        except RuntimeError as e:
            if str(e).startswith('Unreadable page'):raise RuntimeError(str(e)) from e
            raise
        except ValueError as e:
            raise RuntimeError('root object invalid: '+str(e)) from e
        clock_before=self.read(self.core+0x4cc,18)
        entities={};coverage={}
        for name,offset in LISTS.items():
            objects,meta=self.walk(offset);coverage[name]=meta
            if name.startswith('unclassified'):
                entities[name]=[{'address':hex(a),'vtable':hex(u32(self.read(a,4),0))} for _,a in objects]
                continue
            entities[name]=[self.decode(a)|{'container_index':i} for i,a in objects]
        doc=self.core-0x912;projection=self.read(doc+0x785,0x60)
        local={'source_layer':'local_projection','address':hex(doc+0x785),'gold':u32(projection,16),'rice':u32(projection,20),'population':u32(projection,0),'troop_stock':dict(zip(['infantry','cavalry','bow'],[u32(projection,o) for o in [52,64,76]])),'armament_raw':dict(zip(['infantry','cavalry','bow'],[u32(projection,o) for o in [56,68,80]]))}
        # Root headers and scalar flags must remain unchanged during capture.
        coherent=all(self.m.read(a,len(h))==h for a,h in self.headers)
        coherent=coherent and self.m.read(self.core+0x4cc,18)==clock_before
        # Player attribution is applied by the bridge after session confirmation.
        local['player_force_id']=None;divergences={}
        ids=collections.Counter(r['general_id_raw'] for r in entities['generals'])
        return enrich({'schema':SCHEMA,'snapshot_id':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'),'capture_start':utc,'capture_end':datetime.now(timezone.utc).isoformat(),'identity':self.m.identity,'build_sha256':self.sha,'readonly':True,'core_address':hex(self.core),'coverage':coverage,'entities':entities,'current_local_projection':local,'core_projection_divergence':divergences,'decode_warnings':self.decode_warnings,'clock_candidates':{'raw_hex':clock_before.hex(),'year_u16':u16(clock_before,4),'season_u16':u16(clock_before,10),'verification':'candidate_not_validated_by_transition'},'duplicate_general_ids':{str(k):v for k,v in ids.items() if v>1},'consistency':{'root_headers_and_clock_unchanged':coherent,'atomic_game_snapshot':False,'limitation':'does not prove every mutable entity field was unchanged during sampling'},'omniscient_layer_ready':False,'limits':['Core state and current local projection differ; do not silently merge','923 general records include unassigned/future/reserved; activity enum not decoded','Empty lists have structurally confirmed count zero but their unit semantics remain unverified','Restart/load and temporal liveness not tested; coordinates not GUI-calibrated'],'timing':{'capture_ms':(time.perf_counter()-start)*1000,'rpm_calls':self.m.calls-c0,'rpm_bytes':self.m.bytes-b0,'pages':len(self.cache)}})

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pid',type=int,default=26176);ap.add_argument('--discover',action='store_true');ap.add_argument('--bench',type=int,default=0);args=ap.parse_args()
    if not 0<=args.bench<=1000:raise ValueError('bench range 0..1000')
    c=Collector(args.pid)
    try:
        binding=c.bind(args.discover);d=c.capture();samples=[]
        for _ in range(args.bench):
            q=c.capture();samples.append(q['timing'])
            if not q['consistency']['root_headers_and_clock_unchanged']:raise RuntimeError('inconsistent capture')
            d=q
        atomic_json(ROOT/'state.json',d)
        bench=None
        if samples:
            times=sorted(x['capture_ms'] for x in samples)
            bench={'n':len(times),'scope':'typed lists + all decoded entities + local projection + header recheck; excludes disk publish, GUI, LLM, and process startup','p50_ms':statistics.median(times),'p95_ms':times[max(0,__import__('math').ceil(len(times)*.95)-1)],'min_ms':times[0],'max_ms':times[-1],'samples':samples}
            atomic_json(ROOT/'benchmark.json',bench)
        print(json.dumps({'binding':binding,'counts':{k:v['count'] for k,v in d['coverage'].items()},'divergence':d['core_projection_divergence'],'timing':d['timing'],'benchmark':{k:v for k,v in (bench or {}).items() if k!='samples'},'state_file':str(ROOT/'state.json')},ensure_ascii=False,indent=2))
    finally:c.close()
if __name__=='__main__':main()
