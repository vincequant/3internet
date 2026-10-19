"""List wild generals (status 1) with ids — read-only, for the P60 personnel preset."""
import ctypes as c, json, os, struct, sys
from ctypes import wintypes as w
sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector  # noqa
GENERAL_VT = 0x5056F0
k = c.WinDLL('kernel32', use_last_error=True)
k.OpenProcess.restype = w.HANDLE

def find_pid(name='sanpk.exe'):
    class E(c.Structure):
        _fields_=[('dwSize',w.DWORD),('cntUsage',w.DWORD),('th32ProcessID',w.DWORD),
                  ('th32DefaultHeapID',c.c_size_t),('th32ModuleID',w.DWORD),('cntThreads',w.DWORD),
                  ('th32ParentProcessID',w.DWORD),('pcPriClassBase',c.LONG),('dwFlags',w.DWORD),
                  ('szExeFile',w.WCHAR*260)]
    snap=k.CreateToolhelp32Snapshot(0x2,0); e=E(); e.dwSize=c.sizeof(e); out=[]
    ok=k.Process32FirstW(snap, c.byref(e))
    while ok:
        if e.szExeFile.lower()==name: out.append(int(e.th32ProcessID))
        ok=k.Process32NextW(snap, c.byref(e))
    k.CloseHandle(snap)
    return out

pid = int(sys.argv[1]) if len(sys.argv)>1 else (find_pid() or [None])[0]
col = Collector(pid); col.bind(); core = col.core; col.close()
h = k.OpenProcess(0x10, False, pid)
def rd(addr, n):
    b=c.create_string_buffer(n); got=c.c_size_t()
    if not k.ReadProcessMemory(h, c.c_void_p(addr), b, n, c.byref(got)): return None
    return b.raw
def u32(a):
    r=rd(a,4); return struct.unpack('<I', r)[0] if r else None
def i16(a):
    r=rd(a,2); return struct.unpack('<h', r)[0] if r else None
def walk(head):
    out=[]; node=head; guard=0
    while node and guard<5000:
        obj=u32(node+8)
        if not obj: break
        out.append(obj); node=u32(node); guard+=1
    return out
objs = walk(u32(core+0x518))
wild=[]; inservice=[]
for o in objs:
    if u32(o)!=GENERAL_VT: continue
    gid=i16(o+0x0A); st=i16(o+0x21); city=i16(o+0x34)
    if st==1: wild.append({'id':gid,'city':city,'obj':hex(o)})
    elif st in (0,2,3,4,9): inservice.append({'id':gid,'status':st,'city':city})
print(json.dumps({'pid':pid,'core':hex(core),'generals':len(objs),'wild_count':len(wild),
                  'wild_sample':wild[:12],'inservice_sample':inservice[:5]}, ensure_ascii=False))
