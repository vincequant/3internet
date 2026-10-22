"""Website reference fields, isolated from runtime attributes and probabilities."""
import json,math
from pathlib import Path
from collections import defaultdict
DATA=json.loads(Path(__file__).with_name('officer_web_reference.json').read_text(encoding='utf8'))
INDEX=defaultdict(list)
for r in DATA['generals']:INDEX[r['name']].append(r)
KEYS={'lead':'leadership','war':'power','intel':'intelligence','pol':'politics','cha':'charm'}
def diplomacy(pol,cha,skills):
 return math.floor((pol+cha)*1.2+.5) if '提案' in skills else pol+cha

def officer_metrics(g):
 a=g.get('attributes',{});total=sum(a[k] for k in KEYS) if all(type(a.get(k)) in (int,float) for k in KEYS) else None
 out={'total':total,'attack':None,'strategy':None,'diplomacy':None,'skills':'未匹配','reference_total':None,'current_diplomacy':None,'match':'网站未收录同名；非无技能'}
 refs=INDEX.get(g.get('name'),[])
 if len(refs)!=1:
  if refs:out['match']='网站重名，未自动匹配'
  return out
 ref=refs[0];s=ref['stats'];skills=[x if isinstance(x,str) else x['name'] for x in ref.get('skills',[])]
 same=all(a.get(k)==s.get(v) for k,v in KEYS.items())
 out.update(attack=s.get('attack'),strategy=s.get('strategy'),diplomacy=diplomacy(s['politics'],s['charm'],skills),skills=' / '.join(skills) or '网站技能空表',reference_total=sum(s[v] for v in KEYS.values()),match='同名唯一 / 五维一致；技能为网站资料' if same else '同名参考 / 五维不同；请核对版本')
 if isinstance(out['strategy'],str):
  try:out['strategy']=float(out['strategy'].replace('%',''))
  except ValueError:out['strategy']=None
 if same:out['current_diplomacy']=diplomacy(a['pol'],a['cha'],skills)
 return out

def cells(g):
 m=officer_metrics(g)
 return tuple('—' if m[k] is None else m[k] for k in ('total','attack','strategy','diplomacy','reference_total','skills','match'))
COLUMNS=[('total','本局五维合计',105),('ref_attack','网站攻击力',100),('ref_strategy','网站计略 %',100),('ref_diplomacy','网站外交力',100),('ref_total','网站五维合计',105),('ref_skills','网站技能',380),('ref_match','资料匹配',260)]
