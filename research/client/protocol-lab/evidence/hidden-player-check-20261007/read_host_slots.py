import sys,os,json,struct,hashlib,time,ctypes as c
from pathlib import Path
bridge=Path(r'Z:\Users\vkquant\Applications\SGI-Game\hub\bridge');assert (bridge/'probe.py').exists();sys.path.insert(0,str(bridge))
os.environ['SGI_GAME_EXE']=r'C:\sgi\run-3.5\3I\SANPK.exe'
from probe import Memory,MBI,kernel
m=Memory(2052)
assert hashlib.sha256(Path(m.identity['path']).read_bytes()).hexdigest()=='df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
start=time.monotonic();a=0;budget=128*1024*1024;docs=[]
try:
 while a<0x40000000 and budget>0 and time.monotonic()-start<10:
  mbi=MBI()
  if not kernel().VirtualQueryEx(m.h,c.c_void_p(a),c.byref(mbi),c.sizeof(mbi)):break
  base=mbi.BaseAddress or 0;size=mbi.RegionSize
  if not size or base+size<=a:break
  if mbi.State==0x1000 and mbi.Type==0x20000 and mbi.Protect&0xff in (4,8,0x40,0x80) and not mbi.Protect&0x100:
   for off in range(0,size,1024*1024):
    n=min(1024*1024,size-off,budget);budget-=n;raw=m.read(base+off,n)
    if raw:
     pos=0
     while True:
      pos=raw.find(struct.pack('<I',0x504d40),pos)
      if pos<0:break
      doc=base+off+pos;pos+=4
      if m.read(doc+0x912,4)==struct.pack('<I',0x5053c0):docs.append(doc)
    if budget<=0:break
  a=base+size
 docs=list(set(docs));assert len(docs)==1,docs
 doc=docs[0];slots=[]
 for i in range(8):
  record=m.read(doc+0xb4+i*0x87,0x87);assert record
  ip=struct.unpack_from('<I',record,6)[0]
  slots.append({'slot':i,'network_id':str(ip),'type_u16':struct.unpack_from('<H',record,4)[0],'slot_marker':struct.unpack_from('<I',record,0x42)[0]})
 print(json.dumps({'pid':2052,'doc':hex(doc),'slots':slots,'readonly':True,'scan_seconds':time.monotonic()-start}),flush=True)
finally:m.close()
