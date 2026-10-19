from pathlib import Path
import sys,json,ctypes as c
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'research/client/SGI-Hub-CrossOver-M4-0.2/room_monitor/sgi_room_monitor'));import wine_lobby_ops as m
assert c.sizeof(c.c_void_p)==4
out=[]
for row in m.sanpk_windows():
 if not row['visible']:continue
 controls=[]
 for ch in row['children']:
  if not ch['visible']:continue
  v={k:ch[k] for k in ['hwnd','class','title','rect']}
  if ch['class'].lower() in ['listbox','combobox']:
   count=int(m.u.SendMessageW(ch['hwnd'],0x18b if ch['class'].lower()=='listbox' else 0x146,0,0));v['count']=count
   if 0<=count<=32:
    texts=[]
    for i in range(count):
     buf=c.create_unicode_buffer(1024);m.u.SendMessageW(ch['hwnd'],0x189 if ch['class'].lower()=='listbox' else 0x148,i,c.byref(buf));texts.append(buf.value)
    v['items']=texts
  controls.append(v)
 out.append({'pid':row['pid'],'hwnd':row['hwnd'],'title':row['title'],'class':row['class'],'controls':controls})
print(json.dumps({'game_windows':out},ensure_ascii=False))
