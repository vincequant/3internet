"""Native declaration/refusal points, with held white-card counterfactuals."""
from itertools import combinations
from force_relations import allied
from native_diplomacy import CARD_POINTS,POINT_WHITE_IDS,envoy_score,envoys
WAR_IDS={1,6};REJECT_IDS={8,9};GREEN_IDS={12,13,14};AUX_IDS={26,27,28};SEAL_ID=17
GRAY_IDS=POINT_WHITE_IDS;SUPPLEMENT_LIMIT=4
BG,FG='#f7f4ea','#302c22'
def _held(force):return [c for c in ((force or {}).get('hand_cards') or {}).get('slots',[]) if c.get('card_id') not in (0,None)]
def _points(c):return CARD_POINTS.get(c.get('card_id'),0)
def card_pack(force,role,white=False):
 cards=_held(force);ids=WAR_IDS if role=='主动' else REJECT_IDS;mains=[c for c in cards if c.get('card_id') in ids]
 whites=[c for c in cards if c.get('card_id') in POINT_WHITE_IDS]
 if not mains:return dict(ok=False,reason='无宣战卡' if role=='主动' else '斩使需特殊回应判定' if any(c.get('card_id')==10 for c in cards) else '无拒绝卡',skipped=whites,seal=False)
 main=max(mains,key=_points)
 allowed=GREEN_IDS|AUX_IDS
 extras=[c for c in cards if c is not main and (c.get('card_id') in allowed or c.get('card_id') in POINT_WHITE_IDS and (white is True or isinstance(white,(set,frozenset)) and c.get('slot') in white))]
 extras.sort(key=lambda c:(-_points(c),c.get('slot',0)));chosen=[main,*extras[:4]]
 return dict(ok=True,chosen=chosen,card_points=sum(_points(c) for c in chosen),skipped=[c for c in whites if c not in chosen],seal=any(c.get('card_id')==17 for c in chosen),trimmed=len(extras)>4,role=role)
def best_envoy(state,force,role):
 found=envoys(state,(force or {}).get('force_id'),role)
 return found[0] if found else None
def side_line(pack,envoy):
 if not pack['ok']:return dict(text=pack['reason'],total=None,card_points=None)
 names='＋'.join(f"{c.get('name','卡牌')}{_points(c)}" for c in pack['chosen']);points=pack['card_points']
 if envoy is None:return dict(text=f'{names}；使者资料不足',total=None,card_points=points)
 total=points+envoy['actor'];return dict(text=f"{names}；{envoy['name']} {envoy['actor']}＋卡{points}＝{total}",total=total,card_points=points)
def _delta(a,b):return a['total']-b['total'] if a['total'] is not None and b['total'] is not None else None
def _result(delta,initiating):
 if delta is None:return '未知',''
 win=delta>=0 if initiating else delta<0
 return ('胜','win') if win else ('负','loss')
def _scenario(a,b,initiating):
 if not b['pack']['ok'] and b['pack']['reason']=='斩使需特殊回应判定':return dict(delta=None,result='未知',tone='',text=b['pack']['reason'])
 if not b['pack']['ok']:return dict(delta=None,result='胜' if initiating else '负',tone='win' if initiating else 'loss',text='对方无拒绝卡' if initiating else '我方无拒绝卡')
 delta=_delta(a['line'],b['line']);result,tone=_result(delta,initiating)
 return dict(delta=delta,result=result,tone=tone,text=f'{result}（点差{delta:+}）' if delta is not None else '使者资料不足')
def _side(state,f,role,white=False):
 pack=card_pack(f,role,white);envoy=best_envoy(state,f,role)
 return dict(pack=pack,line=side_line(pack,envoy))
def _white_names(side):return '、'.join(c.get('name','白卡') for c in side['pack'].get('chosen',[]) if c.get('card_id') in POINT_WHITE_IDS) or '无白卡'
def _pair(state,own,other,initiating):
 attacker,defender=(own,other) if initiating else (other,own)
 a,b=_side(state,attacker,'主动'),_side(state,defender,'被动')
 aw,bw=_side(state,attacker,'主动',True),_side(state,defender,'被动',True)
 base=_scenario(a,b,initiating)
 ours=_scenario(aw,b,True) if initiating else _scenario(a,bw,False)
 theirs=_scenario(a,bw,True) if initiating else _scenario(aw,b,False)
 both=_scenario(aw,bw,initiating)
 own_white=aw if initiating else bw;other_white=bw if initiating else aw
 solution='无需白卡' if base['result']=='胜' else '现有白卡不能反转' if base['result']=='负' else '使者资料不足'
 if base['result']=='负' and ours['result']=='胜':
  whites=[c for c in _held(own) if c.get('card_id') in POINT_WHITE_IDS]
  choices=[]
  for n in range(1,min(4,len(whites))+1):
   for subset in combinations(whites,n):
    side=_side(state,own,'主动' if initiating else '被动',{c['slot'] for c in subset})
    trial=_scenario(side,b,True) if initiating else _scenario(a,side,False)
    if trial['result']=='胜':choices.append((side['pack']['card_points'],side,trial))
   if choices:break
  if choices:
   _,side,trial=min(choices,key=lambda x:x[0]);solution='可反转：'+_white_names(side)+f"（点差{trial['delta']:+}）"
 fields=dict(scene='我方宣战' if initiating else '对方宣战',opponent=other.get('name','未知'),result=base['result'],tone=base['tone'],
  delta='—' if base['delta'] is None else f"{base['delta']:+}",attack=a['line']['text'],defend=b['line']['text'],
  our_white=ours['text']+' · '+_white_names(own_white),their_white=theirs['text']+' · '+_white_names(other_white),both_white=both['text'],solution=solution,
  note='同点宣战方胜。白卡情景使用当前手牌；补点主卡＋最多四张。换牌卡不补点，援助武将需另选武将，未自动加入。',
  white_attack=aw['line']['text'],white_defend=bw['line']['text'])
 return fields
def matchup_rows(state,own_id):
 forces=((state or {}).get('entities') or {}).get('lords',[]);own=next((f for f in forces if f.get('force_id')==own_id),None)
 if not own:return []
 others=[f for f in forces if f.get('force_id')!=own_id and not allied(state,f.get('force_id'))]
 rows=[]
 for other in others:
  if card_pack(own,'主动')['ok']:rows.append(_pair(state,own,other,True))
  if card_pack(other,'主动')['ok']:rows.append(_pair(state,own,other,False))
 return rows
