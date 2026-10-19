from pathlib import Path
import sys,json,ctypes as c,time
ROOT=Path(__file__).resolve().parents[5]
sys.path.insert(0,str(ROOT/'research/client/SGI-Hub-CrossOver-M4-0.2/room_monitor/sgi_room_monitor'))
import wine_lobby_ops as m
assert c.sizeof(c.c_void_p)==4
rows=m.sanguo_windows();assert any('当前用户: VK(筑基期)' in row['title'] for row in rows)
trees=m.tree_items(rows);match,exact,_=m.collect_tree_matches(trees,'电信1（备用）');assert match and '三国对战房' in match['parent']
hwnd=match['hwnd'];handle=match['handle']
height=int(m.u.SendMessageW(hwnd,0x111c,0,0));indent=int(m.u.SendMessageW(hwnd,0x1106,0,0))
first=int(m.u.SendMessageW(hwnd,m.TVM_GETNEXTITEM,5,0));tree=next(t for t in trees if t['hwnd']==hwnd);first_index=next(i for i,row in enumerate(tree['items']) if row['handle']==first)
assert 10 <= height <= 60 and 5 <= indent <= 60
x=(match['depth']+1)*indent+12;y=(match['index']-first_index)*height+height//2
assert x>=0 and y>=0
m.u.SendMessageW(hwnd,m.TVM_SELECTITEM,m.TVGN_CARET,handle)
m.u.SendMessageW(hwnd,m.TVM_ENSUREVISIBLE,0,handle)
lp=m._lparam_xy(x,y)
for msg in [m.WM_LBUTTONDOWN,m.WM_LBUTTONUP,m.WM_LBUTTONDBLCLK,m.WM_LBUTTONUP]:m.u.PostMessageW(hwnd,msg,1 if msg!=m.WM_LBUTTONUP else 0,lp)
print(json.dumps({'stage':'target_line_doubleclick','title':match['text'],'parent':match['parent'],'item_height':height,'indent':indent,'first_visible_index':first_index,'x':x,'y':y},ensure_ascii=False),flush=True)
time.sleep(2)
v=m.inspect();print(json.dumps({k:v[k] for k in ['titles','has_start','lists','trees']},ensure_ascii=False),flush=True)
