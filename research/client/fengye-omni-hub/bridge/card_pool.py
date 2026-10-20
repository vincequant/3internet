"""Bounded read-only public card pool; no random-state or next-card prediction."""
import struct
from collections import Counter
# Original card ID getters at vtable+0x14, verified by isolated x86 execution.
VT_IDS={0x5040a8:8,0x504108:9,0x504168:10,0x504228:1,0x504288:2,0x5042e8:3,0x504348:4,0x5043a8:5,0x504408:6,0x504468:7,0x504528:16,0x504588:17,0x5045e8:18,0x504648:19,0x5046a8:20,0x504708:21,0x504768:22,0x5047c8:23,0x504828:24,0x504888:25,0x504948:26,0x5049a8:27,0x504a08:28,0x504ac8:11,0x504b28:12,0x504b88:13,0x504be8:14,0x504c48:15}
def read_pool(collector):
 try:
  objects,meta=collector.walk(0x5d4,max_count=2048)
  disabled=collector.read(collector.core+0x48c,28);observed=[];counts=Counter();all_counts=Counter();states=Counter()
  for _,a in objects:
   b=collector.read(a,6);vt,owner=struct.unpack('<Ih',b);cid=VT_IDS.get(vt)
   if cid is None:raise ValueError('未知卡牌类型')
   if owner not in (-1,-2) and not 0<=owner<22:raise ValueError('未知卡牌归属')
   observed.append((a,b));all_counts[cid]+=1;states[owner]+=1
   if owner==-1 and disabled[cid-1]==0:counts[cid]+=1
  stable=collector.m.read(collector.core+0x48c,28)==disabled and all(collector.m.read(a,6)==b for a,b in observed)
  stable=stable and all(collector.m.read(a,len(b))==b for a,b in collector.headers)
  if not stable:raise ValueError('卡池在读取期间改变')
  return dict(status='verified',version=1,counts={str(i):counts[i] for i in range(1,29)},total=sum(counts.values()),all_counts={str(i):all_counts[i] for i in range(1,29)},
              disabled_ids=[i+1 for i,v in enumerate(disabled) if v],allocation_counts={str(i):n for i,n in states.items()},
              source='core+0x5d4; card+4 == -1; 0x43f5ae / 0x45b998; stable double read',list_count=meta['count'])
 except (ValueError,RuntimeError,TypeError,struct.error) as exc:return dict(status='unknown',version=1,reason=str(exc))
