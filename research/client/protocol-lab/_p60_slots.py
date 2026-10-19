import json, sys
sys.path.insert(0, r'Z:\Users\vk\sgi-fengye-lab\shadow\bridge')
from collector import Collector
pid=int(sys.argv[1]); c=Collector(pid)
try:
    c.bind(); s=c.capture()
    ps=s.get('player_slots') or []
    out=[]
    for r in ps:
        if isinstance(r, dict):
            out.append({k: r.get(k) for k in ('slot','name','id','force','force_id','state','connected','nickname')})
        else:
            out.append(r)
    print(json.dumps({'ok':True,'slots':out,'local':s.get('player_context')}, ensure_ascii=False))
finally:
    c.close()
