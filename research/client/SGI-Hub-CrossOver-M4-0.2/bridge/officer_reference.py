"""Website reference fields, isolated from runtime attributes and probabilities."""
import json,math
from pathlib import Path
from collections import defaultdict
DATA=json.loads(Path(__file__).with_name('officer_web_reference.json').read_text(encoding='utf8'))
INDEX=defaultdict(list)
for r in DATA['generals']:INDEX[r['name']].append(r)
KEYS={'lead':'leadership','war':'power','intel':'intelligence','pol':'politics','cha':'charm'}
STAT_LABELS=(('lead','统'),('war','武'),('intel','智'),('pol','政'),('cha','魅'))
# Live GBK names that differ from the website by one character or ASCII case.
# Used only when that website row is unique and the five stats are identical.
SPELLING={
 '陆云讯':'陆云迅','费纬':'费祎','毛介':'毛玠','雍阁':'雍闿','貂禅':'貂蝉',
 'QQQ':'qqq','OK哥':'ok哥',
}

def unique_ref(name):
 refs=INDEX.get(name) or []
 return refs[0] if len(refs)==1 else None

def matched_ref(officer):
 """Return (website row, 'exact'|'spelling') or (None, 'ambiguous'|'missing')."""
 name=(officer or {}).get('name')
 if unique_ref(name) is not None:
  return unique_ref(name),'exact'
 if INDEX.get(name):
  return None,'ambiguous'
 alt=SPELLING.get(name)
 ref=unique_ref(alt) if alt else None
 if ref is None:
  return None,'missing'
 attrs=(officer or {}).get('attributes') or {}
 stats=ref.get('stats') or {}
 if all(attrs.get(key)==stats.get(web) for key,web in KEYS.items()):
  return ref,'spelling'
 return None,'missing'

def website_attributes(name):
 refs=INDEX.get(name) or []
 if len(refs)!=1:
  return {}
 stats=refs[0].get('stats') or {}
 return {key:stats[web] for key,web in KEYS.items() if isinstance(stats.get(web),(int,float))}

def display_attributes(officer):
 attrs=dict((officer or {}).get('attributes') or {})
 if any(isinstance(attrs.get(key),(int,float)) for key,_ in STAT_LABELS):
  return attrs
 return website_attributes((officer or {}).get('name'))

def standout_stat(officer):
 scored=[(label,attrs[key]) for attrs in (display_attributes(officer),) for key,label in STAT_LABELS if isinstance(attrs.get(key),(int,float))]
 if not scored:
  return None
 top=max(value for _,value in scored)
 for label,value in scored:
  if value==top:
   number=int(value) if float(value).is_integer() else value
   return {'label':label,'value':number}
 return None

def officer_title(officer):
 name=(officer or {}).get('name') or '未知'
 stand=standout_stat(officer)
 return f"{name}({stand['label']}:{stand['value']})" if stand else name

def blade_total(officer):
 attrs=display_attributes(officer)
 lead,war=attrs.get('lead'),attrs.get('war')
 if type(lead) is int and type(war) is int and 0<=lead<=255 and 0<=war<=255:
  return lead+war
 return None

def recruit_standout(officer):
 """Show 统武, 智力 or 政治. 统武 is 统率+武力; compare 统武/2 with the other two."""
 attrs=display_attributes(officer)
 def number(key):
  value=attrs.get(key)
  if type(value) is int and 0<=value<=255:
   return value
  return None
 lead,war,intel,pol=number('lead'),number('war'),number('intel'),number('pol')
 options=[]
 if lead is not None and war is not None:
  options.append(((lead+war)/2, 0, '统武', lead+war))
 if intel is not None:
  options.append((intel, 1, '智力', intel))
 if pol is not None:
  options.append((pol, 2, '政治', pol))
 if not options:
  return None
 _score,_rank,label,shown=max(options, key=lambda item: (item[0], -item[1]))
 return {'label':label,'value':shown}

def recruit_title(officer):
 name=(officer or {}).get('name') or '未知'
 stand=recruit_standout(officer)
 return f"{name}({stand['label']}:{stand['value']})" if stand else name

def officer_event_text(officer, city=None, field='录用'):
 title=recruit_title(officer)
 place=city or (officer or {}).get('location_city_name')
 prefix='录用' if field=='录用' else '加入'
 return f'{prefix} {title}：{place}' if place else f'{prefix} {title}'

def hire_command_text(officer, city=None):
 return officer_event_text(officer, city, '录用')
def diplomacy(pol,cha,skills):
 return math.floor((pol+cha)*1.2+.5) if '提案' in skills else pol+cha

def officer_metrics(g):
 a=g.get('attributes',{});total=sum(a[k] for k in KEYS) if all(type(a.get(k)) in (int,float) for k in KEYS) else None
 out={'total':total,'attack':None,'strategy':None,'diplomacy':None,'skills':'未匹配','reference_total':None,'current_diplomacy':None,'match':'网站未收录同名；非无技能'}
 ref,how=matched_ref(g)
 if ref is None:
  if how=='ambiguous':out['match']='网站重名，未自动匹配'
  return out
 s=ref['stats'];skills=[x if isinstance(x,str) else x['name'] for x in ref.get('skills',[])]
 same=all(a.get(k)==s.get(v) for k,v in KEYS.items())
 if same and how=='spelling':
  label='游戏用字与网站差一字 / 五维一致；技能为网站资料'
 elif same:
  label='同名唯一 / 五维一致；技能为网站资料'
 else:
  label='同名参考 / 五维不同；请核对版本'
 out.update(attack=s.get('attack'),strategy=s.get('strategy'),diplomacy=diplomacy(s['politics'],s['charm'],skills),skills=' / '.join(skills) or '网站技能空表',reference_total=sum(s[v] for v in KEYS.values()),match=label)
 if isinstance(out['strategy'],str):
  try:out['strategy']=float(out['strategy'].replace('%',''))
  except ValueError:out['strategy']=None
 if same:out['current_diplomacy']=diplomacy(a['pol'],a['cha'],skills)
 return out

def cells(g):
 m=officer_metrics(g)
 return tuple('—' if m[k] is None else m[k] for k in ('total','attack','strategy','diplomacy','reference_total','skills','match'))
COLUMNS=[('total','本局五维合计',105),('ref_attack','网站攻击力',100),('ref_strategy','网站计略 %',100),('ref_diplomacy','网站外交力',100),('ref_total','网站五维合计',105),('ref_skills','网站技能',380),('ref_match','资料匹配',260)]

SKILL_OPTIONS=['全部技能']+sorted({x if isinstance(x,str) else x['name'] for r in DATA['generals'] for x in r.get('skills',[])})
def eligible_wild(g,skill='全部技能'):
 m=officer_metrics(g)
 return m['diplomacy'] is not None and (skill=='全部技能' or skill in m['skills'].split(' / '))

def website_compatibility(officer):
 """Website 相性 when the five stats match a unique website row. Otherwise unknown."""
 ref,how=matched_ref(officer)
 if ref is None:return None
 a=(officer or {}).get('attributes') or {};s=ref.get('stats') or {}
 if how!='spelling' and not all(a.get(k)==s.get(v) for k,v in KEYS.items()):return None
 value=ref.get('compatibility')
 return value if type(value) is int and 1<=value<=150 else None
