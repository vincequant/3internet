"""Named talent presets; rankings are not battle victory predictions."""
import math
from officer_reference import officer_metrics
SCHEMES={'火攻','火计','落石','混乱','反计','计谋','伪兵','引诱','埋伏','奇袭','收拾','天变','天雷'}
ROLES={'全部人才':'', '主动外交':'政治＋魅力；提案加成20%，四舍五入',
 '被动外交':'政治＋魅力；拒绝加成20%，四舍五入',
 '部队攻击之王':'按武将攻击力降序；实际部队攻击还受兵种、训练、编成影响',
 '天师':'天变或天雷；按智力降序', '谋士':'至少一种计谋技能；按技能种数、智力降序',
 '攻城专家':'拥有攻城；按攻击力降序', '骑射能手':'骑马或弓箭；按攻击力降序',
 '内政能臣':'按政治降序'}
def role_value(g,role):
 m=officer_metrics(g);s=set(m['skills'].split(' / '));a=g.get('attributes',{})
 if role in ('主动外交','被动外交'):
  if m['current_diplomacy'] is None:return None
  return math.floor((a['pol']+a['cha'])*(1.2 if ('提案' if role=='主动外交' else '拒绝') in s else 1)+.5)
 if role=='部队攻击之王':return m['attack']
 if role=='天师':return a.get('intel') if s&{'天变','天雷'} else None
 if role=='谋士':return (len(s&SCHEMES),a.get('intel',0)) if s&SCHEMES else None
 if role=='攻城专家':return m['attack'] if '攻城' in s else None
 if role=='骑射能手':return m['attack'] if s&{'骑马','弓箭'} else None
 if role=='内政能臣':return a.get('pol')
 return 0
