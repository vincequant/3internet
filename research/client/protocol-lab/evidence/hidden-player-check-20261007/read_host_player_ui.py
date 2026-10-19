import ctypes as c,json,sys
from ctypes import wintypes as w
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import inspect_host_ipcheck_20261006 as m
m.u.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,c.c_void_p];m.u.SendMessageW.restype=w.LPARAM
out=[]
for row in m.rows:
 if row['pid']!=2052 or not row['exe'].lower().endswith('\\sanpk.exe'):continue
 controls=[]
 @m.CB
 def visit(ch,_):
  if not m.u.IsWindowVisible(ch):return True
  cls=m.label(ch,True)
  if True:
   buf=c.create_unicode_buffer(1024);m.u.SendMessageW(ch,0xd,len(buf),c.byref(buf));controls.append({'hwnd':int(ch),'class':cls,'text':buf.value})
  return True
 m.u.EnumChildWindows(row['hwnd'],visit,0);out.append({'pid':row['pid'],'controls':controls})
print(json.dumps({'host_game_ui':out},ensure_ascii=False),flush=True)
