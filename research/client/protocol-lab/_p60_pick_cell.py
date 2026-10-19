import json, sys
sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector
pid=int(sys.argv[1]); cx=int(sys.argv[2]); cy=int(sys.argv[3]); force=int(sys.argv[4]) if len(sys.argv)>4 else 1
c=Collector(pid)
try:
    c.bind(); s=c.capture(); e=s.get('entities') or {}
    tg=s['terrain_grid']; W=int(tg['width']); H=int(tg['height'])
    raw=bytes.fromhex(tg['types'])
    occupied=set()
    for r in (e.get('production_buildings') or [])+(e.get('traps') or []):
        xy=r.get('world_xy_raw') or []
        if len(xy)==2 and xy[0]>=0: occupied.add((int(xy[0]),int(xy[1])))
    for r in (e.get('cities_and_barriers') or []):
        xy=r.get('world_xy_raw') or []
        if len(xy)==2 and xy[0]>=0: occupied.add((int(xy[0]),int(xy[1])))
    grid=[[raw[y*W+x] if y*W+x < len(raw) else -1 for x in range(W)] for y in range(H)]
    cands=[]
    for dy in range(-3,4):
        for dx in range(-3,4):
            if dx==0 and dy==0: continue
            x,y=cx+dx, cy+dy
            if not (0<=x<W and 0<=y<H): continue
            t=grid[y][x]
            if t==2 and (x,y) not in occupied:
                cands.append({'xy':[x,y],'terrain':t,'dist':abs(dx)+abs(dy)})
    cands.sort(key=lambda c:(c['dist'],c['xy'][1],c['xy'][0]))
    print(json.dumps({'ok':True,'city_xy':[cx,cy],'terrain_at_city':grid[cy][cx],
                      'occupied_count':len(occupied),'candidates':cands[:8]}, ensure_ascii=False))
finally:
    c.close()
