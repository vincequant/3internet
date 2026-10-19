"""Read only the audited network state in the second Mac's monitor game."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import struct
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import monitor_inspect as m

k=m.k
k.ReadProcessMemory.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
k.ReadProcessMemory.restype=w.BOOL
p=c.WinDLL('psapi')
p.EnumProcessModulesEx.argtypes=[w.HANDLE,c.POINTER(w.HMODULE),w.DWORD,c.POINTER(w.DWORD),w.DWORD]
p.GetModuleFileNameExW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]

def read(h,a,n):
    buf=c.create_string_buffer(n);got=c.c_size_t()
    if not k.ReadProcessMemory(h,a,buf,n,c.byref(got)) or got.value!=n:
        raise RuntimeError('Cannot read audited network state')
    return buf.raw

seen=set()
for row in m.rows:
    if not row['exe'].lower().endswith('\\sanpk.exe') or row['pid'] in seen:continue
    seen.add(row['pid'])
    exe=Path(row['exe'])
    dll=exe.parent/'Koeinm.dll'
    assert hashlib.sha256(dll.read_bytes()).hexdigest()=='629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
    h=k.OpenProcess(0x410,False,row['pid'])
    assert h
    try:
        modules=(w.HMODULE*256)();needed=w.DWORD()
        assert p.EnumProcessModulesEx(h,modules,c.sizeof(modules),c.byref(needed),3)
        names=[];base=None
        for item in modules[:needed.value//c.sizeof(w.HMODULE)]:
            name=c.create_unicode_buffer(1024)
            p.GetModuleFileNameExW(h,item,name,len(name))
            if any(t in name.value.lower() for t in ['koeinm','nethook','ws2']):
                names.append({'path':name.value,'base':hex(item)})
            if name.value.lower().endswith('\\koeinm.dll'):base=item
        assert base
        data=base+0x12170
        fields={name:struct.unpack('<I',read(h,data+offset,4))[0] for name,offset in [
            ('port',0x144),('app_id',0x8418),('max_slots',0x43c0),('field_841c',0x841c),
            ('field_43c8',0x43c8),('field_8470',0x8470),('field_8474',0x8474)]}
        print(json.dumps({'pid':row['pid'],'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                          'network':fields,'modules':names}),flush=True)
    finally:k.CloseHandle(h)
