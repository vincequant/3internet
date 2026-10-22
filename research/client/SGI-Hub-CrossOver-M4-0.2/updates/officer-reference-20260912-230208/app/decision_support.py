"""Explicit website scenarios and transparent current-state officer rankings."""
import math
from military_summary import troop_info
PARAMS={'步兵':(50,100,'infantry'),'强化步兵':(150,40,'infantry'),'重装步兵':(190,40,'infantry'),'骑兵':(100,50,'cavalry'),'强化骑兵':(150,50,'cavalry'),'铁骑兵':(200,50,'cavalry')}
def js_round(v):return math.floor(v+.5)
def website_morale(prestige,power):
 # Preserve the cached site's first-calculation behavior, including out-of-range input.
 if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in (prestige,power)):
  raise ValueError('请输入有限数字')
 return min(100,math.floor(int(prestige)/4+int(power)/2))

def website_attack_inputs(name,armament,size,ability):
 if name not in PARAMS:raise ValueError('网站未提供该兵种参数')
 if size not in (0,1,2) or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in (armament,ability)):
  raise ValueError('请输入有限数字')
 if not 0<=armament<=100 or not 0<=ability<=150:raise ValueError('武装度0–100，战斗能力0–150')
 base,arm,family=PARAMS[name];bonus={'infantry':[0,100,200],'cavalry':[0,150,350]}[family][size]
 return js_round(int(ability)*(base+bonus+js_round(arm*int(armament)/100))/150)

def website_attack(kind,raw,size,ability):
 info=troop_info(kind,raw)
 if info['name'] not in PARAMS:return None
 if size not in (0,1,2) or not isinstance(ability,(int,float)) or not math.isfinite(ability) or not 0<=ability<=150:raise ValueError('请输入0–150战斗能力')
 return website_attack_inputs(info['name'],info['training'],size,ability)

def attack_scenario(kind,pred,size,ability):
 if not pred:return None
 before=website_attack(kind,pred['raw_before'],size,ability)
 if before is None:return None
 values=[website_attack(kind,r,size,ability) for r in range(pred['raw_after_min'],pred['raw_after_max']+1)]
 low,high=min(values),max(values)
 return {'before':before,'low':low,'high':high,'percent_low':100*(low/before-1) if before else None,'percent_high':100*(high/before-1) if before else None}

def recommend_officers(state,task,query='',city='全部城市'):
 result=[]
 for g in state['entities']['generals']:
  if g.get('status_code')!=1 or g.get('owner_raw')!=65535:continue
  if city!='全部城市' and g.get('location_city_name')!=city:continue
  a=g.get('attributes',{})
  required={'战斗':['lead','war'],'训练 / 内政':['pol'],'计略':['intel']}[task]
  if any(not isinstance(a.get(k),(int,float)) for k in required):continue
  if task=='战斗':score=(a['lead']+a['war'])/2;why=f"统 {a['lead']} / 武 {a['war']}；网站统武均值，仅候选指标"
  elif task=='训练 / 内政':score=a['pol'];why=f"政治 {a['pol']}；训练公式相关，能否执行待确认"
  else:score=a['intel'];why=f"智力 {a['intel']}；无成功率公式，不计未知技能"
  if query.lower() not in f"{g.get('name','')} {g.get('location_city_name','')} {g.get('general_id_raw','')}".lower():continue
  result.append({'officer':g,'score':score,'why':why})
 return sorted(result,key=lambda r:(-r['score'],r['officer']['general_id_raw'],r['officer']['container_index']))
