"""Read only the audited network state in the second Mac's monitor game."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import struct
import sys
from pathlib import Path
sys.path.insert(0,r'Z:\Users\vkquant\sgi-protocol-lab-20260915')
import inspect_host_ipcheck_20261006 as m

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
    dll_sha=hashlib.sha256(dll.read_bytes()).hexdigest()
    assert dll_sha in ('629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841','25e9e54d7ec11a64287130fa614c1ab80e041fa0864a406ae76de030d512ee83','28476038d67d2f330860d88b3dd0be53594354107cfd26ecb36ddf8512d111d8')
    assert hashlib.sha256(exe.read_bytes()).hexdigest()=='df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
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
            ('connected_member_count',0x43bc),('search_gate_8410',0x8410),('search_gate_8414',0x8414),('is_host',0x148),('port',0x144),('app_id',0x8418),('max_slots',0x43c0),('field_841c',0x841c),
            ('field_43c8',0x43c8),('field_8470',0x8470),('field_8474',0x8474)]}
        slot_pointer=struct.unpack('<I',read(h,data+0x43b8,4))[0]
        assert 0 < fields['connected_member_count'] <= 8
        members=[{'id':str(struct.unpack('<I',read(h,slot_pointer+i*0x164,4))[0]),'name':read(h,slot_pointer+i*0x164+4,31).split(b'\0')[0].decode('gbk','replace')} for i in range(fields['connected_member_count'])]
        slot=read(h,slot_pointer,0x164)
        host_id=struct.unpack('<I',slot[:4])[0]
        host_name=slot[4:35].split(b'\0')[0].decode('gbk','replace')
        session_name=read(h,data+0x43d8,31).split(b'\0')[0].decode('gbk','replace')
        assert fields['is_host']==1 and any(('当前用户: '+host_name+']') in x['title'] for x in m.rows if x['exe'].lower().endswith('sanguo.exe'))
        host_ip='.'.join(str(x) for x in struct.pack('!I',host_id))
        print(json.dumps({'host_name':host_name,'session_name':session_name,'host_id':str(host_id),'host_ip':host_ip,'read_only':True,'pid':row['pid'],'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                          'network_dll_sha256':dll_sha,'network':fields,'members':members,'modules':names}),flush=True)
    finally:k.CloseHandle(h)
