"""Scoped SANPK read-only research; no GUI, target writes, or injection."""
import os
import ctypes as C
from ctypes import wintypes as W
import struct, json, time, hashlib
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent
K=None
class MBI(C.Structure):
    _fields_=[('BaseAddress',C.c_void_p),('AllocationBase',C.c_void_p),('AllocationProtect',W.DWORD),('RegionSize',C.c_size_t),('State',W.DWORD),('Protect',W.DWORD),('Type',W.DWORD)]

def kernel():
    global K
    if K is None:
        K=C.WinDLL('kernel32',use_last_error=True)
        K.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];K.OpenProcess.restype=W.HANDLE
        K.CloseHandle.argtypes=[W.HANDLE];K.CloseHandle.restype=W.BOOL
        K.ReadProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)];K.ReadProcessMemory.restype=W.BOOL
        K.VirtualQueryEx.argtypes=[W.HANDLE,C.c_void_p,C.POINTER(MBI),C.c_size_t];K.VirtualQueryEx.restype=C.c_size_t
        K.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)];K.QueryFullProcessImageNameW.restype=W.BOOL
        K.GetProcessTimes.argtypes=[W.HANDLE]+[C.POINTER(W.FILETIME)]*4;K.GetProcessTimes.restype=W.BOOL
    return K

class WindowsProcessApi:
    def open_process(self,pid):
        h=kernel().OpenProcess(0x410,False,pid)
        if not h: raise C.WinError(C.get_last_error())
        return h
    def close_handle(self,h):
        kernel().CloseHandle(h)
    def query_path(self,h):
        k=kernel();buf=C.create_unicode_buffer(32768);n=W.DWORD(len(buf))
        if not k.QueryFullProcessImageNameW(h,0,buf,C.byref(n)): raise C.WinError(C.get_last_error())
        return buf.value
    def process_times(self,h):
        k=kernel();ft=[W.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h,*[C.byref(t) for t in ft]): raise C.WinError(C.get_last_error())
        ticks=(ft[0].dwHighDateTime<<32)|ft[0].dwLowDateTime
        return ticks,datetime.fromtimestamp(ticks/1e7-11644473600,timezone.utc).isoformat()

class Memory:
    def __init__(self,pid=26176,api=None):
        self.api=api if api is not None else WindowsProcessApi()
        self.h=None;self.identity=None;self.calls=0;self.bytes=0;self.failures=[];self.segments=[];self.regions=[]
        self.h=self.api.open_process(pid)
        try:
            path=self.api.query_path(self.h)
            expected=Path(os.environ['SGI_GAME_EXE'])
            if Path(path).resolve()!=expected.resolve(): raise RuntimeError('instance path mismatch')
            ticks,created=self.api.process_times(self.h)
            self.identity={'pid':pid,'path':path,'creation_filetime':ticks,'created_utc':created}
        except Exception:
            self.close();raise
    def read(self,a,n):
        self.calls+=1;b=C.create_string_buffer(n);got=C.c_size_t()
        ok=kernel().ReadProcessMemory(self.h,C.c_void_p(a),b,n,C.byref(got))
        if not ok or got.value!=n:
            self.failures.append({'addr':hex(a),'requested':n,'got':got.value,'error':C.get_last_error()});return None
        self.bytes+=n;return b.raw
    def load(self):
        self.regions=[];self.segments=[];a=0;t=time.perf_counter()
        while a<0x100000000:
            m=MBI()
            if not kernel().VirtualQueryEx(self.h,C.c_void_p(a),C.byref(m),C.sizeof(m)):break
            base=m.BaseAddress or 0;size=m.RegionSize
            if not size or base+size<=a:break
            if m.State==0x1000 and m.Protect&0xff in (2,4,8,0x20,0x40,0x80) and not m.Protect&0x100:
                self.regions.append({'base':hex(base),'size':size,'protect':m.Protect,'type':m.Type})
                for off in range(0,size,1024*1024):
                    addr=base+off;count=min(1024*1024,size-off);b=self.read(addr,count)
                    if b is not None:self.segments.append((addr,b))
                    else:
                        for p in range(0,count,4096):
                            s=self.read(addr+p,min(4096,count-p))
                            if s is not None:self.segments.append((addr+p,s))
            a=base+size
        self.scan_s=time.perf_counter()-t
    def find(self,pat,limit=200):
        hits=[];last_end=None;tail=b''
        for a,b in self.segments:
            prefix=tail if last_end==a else b''
            merged=prefix+b;start=0
            while True:
                i=merged.find(pat,start)
                if i<0:break
                absolute=a-len(prefix)+i
                if i+len(pat)>len(prefix):hits.append(absolute)
                if len(hits)>=limit:return hits
                start=i+1
            tail=b[-(len(pat)-1):] if len(pat)>1 else b'';last_end=a+len(b)
        return hits
    def context(self,a,before=32,after=96):
        b=self.read(a-before,before+after)
        return {'addr':hex(a),'start':hex(a-before),'hex':b.hex() if b else None}
    def close(self):
        h=getattr(self,'h',None)
        self.h=None
        if h:
            closer=getattr(getattr(self,'api',None),'close_handle',None)
            if closer:closer(h)
            else:kernel().CloseHandle(h)
        if getattr(self,'segments',None) is not None:self.segments.clear()
        if getattr(self,'regions',None) is not None:self.regions.clear()

def main():
    t=time.perf_counter();m=Memory()
    try:
        m.load();patterns={};namehits={}
        names=['宋王','文钦','孔丘','孔子','诸葛睿']
        for name in names:
            for enc in ['gbk','utf-16le']:
                key=name+':'+enc;hits=m.find(name.encode(enc));namehits[key]=hits
                patterns[key]=[m.context(a) for a in hits[:30]]
        stats={'宋王':[95,80,89,74,57],'文钦':[76,82,56,28,31],'孔丘':[89,80,99,90,98]}
        for name,values in stats.items():
            for fmt in ['B','H','I']:
                for n in [5,3]:
                    pat=struct.pack('<'+fmt*n,*values[:n]);hits=m.find(pat)
                    patterns[f'{name}:stats_{fmt}{n}']=[m.context(a,48,144) for a in hits[:25]]
        refs={}
        for key,hits in namehits.items():
            if key.endswith('gbk'):
                for a in hits[:30]:
                    rr=m.find(struct.pack('<I',a),limit=100)
                    refs[hex(a)]={'name':key,'count_capped':len(rr),'references':[m.context(x,32,96) for x in rr[:25]]}
        out={'identity':m.identity,'captured_utc':datetime.now(timezone.utc).isoformat(),'readonly':True,'scan_s':m.scan_s,'elapsed_s':time.perf_counter()-t,'read_calls':m.calls,'bytes_read':m.bytes,'regions':m.regions,'read_failures':m.failures,'patterns':patterns,'name_references':refs}
        ROOT.mkdir(exist_ok=True);(ROOT/'probe_result.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'scan_s':m.scan_s,'total_s':out['elapsed_s'],'read_MB':m.bytes/1e6,'hits':{k:len(v) for k,v in patterns.items()},'name_refs':{k:{'name':v['name'],'n':v['count_capped']} for k,v in refs.items()}},ensure_ascii=False,indent=2))
    finally:m.close()
if __name__=='__main__':main()
