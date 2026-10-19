import ctypes as c
from ctypes import wintypes as w
import hashlib,json,sys,struct
from pathlib import Path
sys.path.insert(0,r'Z:\Users\vkquant\sgi-protocol-lab-20260915')
import inspect_host_ipcheck_20261006 as m
k,u=m.k,m.u
k.ReadProcessMemory.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
k.ReadProcessMemory.restype=w.BOOL
u.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
u.SendMessageW.restype=w.LPARAM
out=[]
for row in m.rows:
 if not row['exe'].lower().endswith('sanguo.exe') or not row['title']:continue
 assert hashlib.sha256(Path(row['exe']).read_bytes()).hexdigest()=='4029e2a414f9b2d4e09be16c5d78685d90ac37bf2a5aa701af64398d1e294eee'
 h=k.OpenProcess(0x410,False,row['pid']);assert h
 def read(addr,n):
  b=c.create_string_buffer(n);got=c.c_size_t()
  assert k.ReadProcessMemory(h,addr,b,n,c.byref(got)) and got.value==n
  return b.raw
 @m.CB
 def child(hwnd,_):
  if 'treeview' not in m.label(hwnd,True).lower():return True
  selected=int(u.SendMessageW(hwnd,0x110a,9,0))
  if not selected:return True
  node=selected;labels=[]
  for i in range(4):
   if not node:break
   data=read(node,64)
   assert struct.unpack_from('<I',data,40)[0]==65534
   ptr=struct.unpack_from('<I',data,24)[0]
   chars=[]
   for j in range(80):
    pair=read(ptr+j*2,2)
    if pair==b'\0\0':break
    chars.append(pair)
   labels.append(b''.join(chars).decode('utf-16le'))
   node=struct.unpack_from('<I',data,0)[0]
  out.append({'tree_hwnd':int(hwnd),'selected_to_root':labels,'visible':bool(u.IsWindowVisible(hwnd))})
  return True
 try:u.EnumChildWindows(row['hwnd'],child,0)
 finally:k.CloseHandle(h)
print(json.dumps({'read_only':True,'selected_trees':out},ensure_ascii=False))
