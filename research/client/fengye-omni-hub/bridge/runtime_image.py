"""Locate the PE image at runtime. Does not attach a debugger."""
import ctypes,struct,time,hashlib
from ctypes import wintypes as W
from pathlib import Path
from recovery import apply_layout_delta

_LAYOUT_BASE=None

def unique_image_base(found):
 # Native WOW64 snapshots can enumerate the same image in both module views.
 bases=set(found)
 if len(bases)!=1 or not next(iter(bases)):raise RuntimeError('游戏映像基址不唯一，停止')
 return next(iter(bases))

def module_base(pid):
 k=ctypes.WinDLL('kernel32',use_last_error=True)
 class Module(ctypes.Structure):
  _fields_=[('dwSize',W.DWORD),('th32ModuleID',W.DWORD),('th32ProcessID',W.DWORD),('GlblcntUsage',W.DWORD),('ProccntUsage',W.DWORD),('modBaseAddr',ctypes.c_void_p),('modBaseSize',W.DWORD),('hModule',W.HMODULE),('szModule',W.WCHAR*256),('szExePath',W.WCHAR*260)]
 k.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];k.CreateToolhelp32Snapshot.restype=W.HANDLE
 k.Module32FirstW.argtypes=[W.HANDLE,ctypes.POINTER(Module)];k.Module32NextW.argtypes=k.Module32FirstW.argtypes;k.CloseHandle.argtypes=[W.HANDLE]
 for attempt in range(3):
  h=k.CreateToolhelp32Snapshot(0x18,pid)
  if h!=ctypes.c_void_p(-1).value:break
  error=ctypes.get_last_error()
  if error!=24 or attempt==2:raise OSError(error, '无法查询游戏映像基址；停止，不猜地址: '+ctypes.FormatError(error))
  time.sleep(0.05)
 m=Module();m.dwSize=ctypes.sizeof(m);found=[]
 try:
  ok=k.Module32FirstW(h,ctypes.byref(m))
  while ok:
   if m.szModule.lower()=='sanpk.exe':found.append(m.modBaseAddr)
   ok=k.Module32NextW(h,ctypes.byref(m))
 finally:k.CloseHandle(h)
 return unique_image_base(found)
def _layout_snapshot(collector):
 return {'CORE_VT':collector.CORE_VT,'DOC_VT':collector.DOC_VT,'TYPES':dict(collector.TYPES),'UNIT_TYPES':dict(collector.UNIT_TYPES)}

def apply_layout(collector,layout):
 collector.CORE_VT=layout['CORE_VT'];collector.DOC_VT=layout['DOC_VT']
 collector.TYPES=dict(layout['TYPES'])
 collector.UNIT_TYPES.clear();collector.UNIT_TYPES.update(layout['UNIT_TYPES'])

def configure(pid,path):
 global _LAYOUT_BASE
 import collector
 if _LAYOUT_BASE is None:_LAYOUT_BASE=_layout_snapshot(collector)
 b=Path(path).read_bytes()
 if not collector.supported_build(hashlib.sha256(b).hexdigest()):raise RuntimeError('不支持的SANPK版本；停止，不套用结构偏移')
 pe=struct.unpack_from('<I',b,0x3c)[0]
 if b[pe:pe+4]!=b'PE\0\0' or struct.unpack_from('<H',b,pe+24)[0]!=0x10b:raise RuntimeError('目标不是预期32位PE')
 base=module_base(pid);preferred=struct.unpack_from('<I',b,pe+52)[0]
 delta=base-preferred
 apply_layout(collector,apply_layout_delta(_LAYOUT_BASE,delta))
 print('当前映像基址',hex(base),'重定位差',hex(delta),flush=True)
 return base
