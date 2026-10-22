"""Client 3.5 land attack components + explicitly separate website combat scaling.

No target defence, terrain, morale, treasure or siege-skill bonus is inferred.
Bow/cavalry proficiency is a reference assumption, never a live skill-bit claim.
"""
import math
from officer_reference import officer_metrics
BUILD='c06ec3aa9c2b539e4111b53c57bed3717a2c0c73f3145aac4d55f66b2abb26cc'
# (unit bases, building bases, unit training coefficients, building coefficients)
PARAMS={
 '步兵':([50,150,250],[50,150,250],[100]*3,[100]*3),
 '强化步兵':([150,250,350],[150,250,350],[20]*3,[20]*3),
 '重装步兵':([190,300,400],[190,300,400],[0]*3,[0]*3),
 '骑兵':([100,250,450],[50,130,230],[25]*3,[10]*3),
 '强化骑兵':([150,300,500],[80,160,260],[25]*3,[10]*3),
 '重装骑兵':([200,350,550],[110,190,290],[25]*3,[10]*3),
 '弓兵':([80,140,200],[40,80,120],[20]*3,[20]*3),
 '强弓兵':([120,180,240],[80,120,160],[120,140,160],[80,100,120]),
 '重装弓兵':([240,320,400],[160,220,280],[120,140,160],[80,100,120])}
BOW={'弓兵','强弓兵','重装弓兵'}
def rnd(n):return math.floor(n+.5)
def span(values):
 if not values:return '缺参数'
 lo,hi=min(values),max(values)
 return str(lo) if lo==hi else f'{lo}–{hi}'

def enrich_targets(state):
 index={}
 for g in state.get('entities',{}).get('generals',[]):index.setdefault(g.get('general_id_raw'),[]).append(g)
 for u in state.get('entities',{}).get('field_units',[]):
  u.update(target_attack_unit='缺参数',target_attack_building='缺参数',target_attack_melee='—',target_attack_note='',unit_skills_reference='',skill_points_display='可用性未核实',target_attack_components={})
  skills=set();unmatched=[];missing=False
  for gid in u.get('general_ids',[]):
   if gid is None:continue
   gs=index.get(gid,[])
   if len(gs)!=1 or gs[0].get('owner_raw')!=u.get('owner_raw') or gs[0].get('status_code')!=2:missing=True;continue
   g=gs[0];m=officer_metrics(g)
   if m['current_diplomacy'] is None:unmatched.append(g.get('name',str(gid)));continue
   if m['skills']!='网站技能空表':skills.update(m['skills'].split(' / '))
  u['unit_skills_reference']=' / '.join(sorted(skills)) or '未匹配技能'
  if unmatched or missing:u['unit_skills_reference']+='；未核定：'+(' / '.join(unmatched) or '编成将')
  kind=u.get('unit_kind');s=u.get('size_index');w=u.get('training_degree');power=u.get('basic_combat_power')
  if state.get('build_sha256')!=BUILD:
   u['target_attack_note']='客户端版本未匹配，停用3.5静态系数';continue
  if kind not in PARAMS or s not in (0,1,2) or type(w) is not int or not 0<=w<=100:
   u['target_attack_note']='兵种、规模或部队训练字段不足';continue
  required='弓箭' if kind in BOW else ('骑马' if '骑兵' in kind else None)
  # Website matches can supply the positive scenario, but absent skills cannot
  # prove an engine-wide negative because treasure/event effects may add skills.
  proficient=required is None or required in skills
  ub,bb,uc,bc=PARAMS[kind]
  base_u=ub[s]+rnd(uc[s]*w/100);base_b=bb[s]+rnd(bc[s]*w/100)
  units=[base_u] if proficient else [base_u//2,base_u]
  buildings=[base_b] if proficient else [base_b//2,base_b]
  u['target_attack_components']={'unit':units,'building':buildings,'training':w,'size':s,'skill_scenario':required,'source':'SANPK 3.5 vt+dc/e0; land, arg1=0,arg2=0'}
  def display(vals):
   if type(power) is int and 0<=power<=150:return '≈'+span([rnd(v*power/150) for v in vals])
   return '基值 '+span(vals)+'（缺战力）'
  u['target_attack_unit']=display(units);u['target_attack_building']=display(buildings)
  if kind in BOW:u['target_attack_melee']=display([[30,60,90][s]])+' / '+display([[20,60,100][s]])
  skill_note=('按资料技能'+required if proficient else required+'状态未核定，范围为无/有技能两种情景') if required else '步兵常规情景'
  u['target_attack_note']='陆战参考：客户端基值含训练 × 编组战力÷150（网站折算）；'+skill_note+'；未含攻城技能、地形、士气、防御和宝物；不是扣血'
 return state
