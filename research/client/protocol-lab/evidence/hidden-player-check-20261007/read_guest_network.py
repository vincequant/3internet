from pathlib import Path
import sys,json,ctypes as c,struct,hashlib
from ctypes import wintypes as w
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'research/client/SGI-Hub-CrossOver-M4-0.2/room_monitor/sgi_room_monitor'));import wine_lobby_ops as m
assert c.sizeof(c.c_void_p)==4
ps=c.WinDLL('psapi');ps.EnumProcessModulesEx.argtypes=[w.HANDLE,c.POINTER(w.HMODULE),w.DWORD,c.POINTER(w.DWORD),w.DWORD];ps.GetModuleFileNameExW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]
seen=set()
for row in m.sanpk_windows():
 if row['pid'] in seen:continue
 seen.add(row['pid']);h=m.k.OpenProcess(0x410,False,row['pid']);assert h
 try:
  modules=(w.HMODULE*256)();needed=w.DWORD();assert ps.EnumProcessModulesEx(h,modules,c.sizeof(modules),c.byref(needed),3)
  out={'pid':row['pid'],'read_only':True,'sources':{}}
  for item in modules[:needed.value//4]:
   n=c.create_unicode_buffer(1024);ps.GetModuleFileNameExW(h,item,n,len(n))
   if n.value.lower().endswith('\\nethookcore.dll'):
    assert hashlib.sha256(Path(n.value).read_bytes()).hexdigest()=='5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4'
    value=struct.unpack('<I',m._rpm(h,item+0x1c828,4))[0]
    out['sources']['original_transport_ip']={'integer':value,'network_order':'.'.join(str(x) for x in struct.pack('<I',value)),'host_order':'.'.join(str(x) for x in struct.pack('!I',value))}
   if n.value.lower().endswith('\\koeinm.dll'):
    assert hashlib.sha256(Path(n.value).read_bytes()).hexdigest()=='629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
    out['sources']['network']={name:struct.unpack('<I',m._rpm(h,item+0x12170+off,4))[0] for name,off in [('first_word',0),('member_count',0x43bc),('is_host',0x148)]}
  print(json.dumps(out),flush=True)
 finally:m.k.CloseHandle(h)
