"""City talent: wild concentration plus website-matched skill counts."""
import math
import tkinter as tk
from tkinter import ttk
from officer_reference import website_compatibility
from player_view import player_id
from preparation_model import skills_for
from wild_locations import wild_location_groups
from recruitment_probability import city_probabilities
ALL_SKILLS='全技能'
SKILL_COLS=(
 ('ride','骑',frozenset({'骑马'})),
 ('bow','弓',frozenset({'弓箭'})),
 ('navy','水',frozenset({'水军'})),
 ('ambush','埋伏',frozenset({'埋伏','伏兵'})),
)
KEYS=('lead','war','intel','pol','cha')
WILD_COLS=(
    ('name','姓名',90),('id','将ID',60),
    ('blade','统武',55),('pol','政治',55),
    ('threshold','判定门槛',95),('chance','录取估算',100),
)
AFFINITY_CIRCLE=150


def lead_war_total(officer):
    attrs = (officer or {}).get('attributes') or {}
    lead, war = attrs.get('lead'), attrs.get('war')
    if type(lead) is int and type(war) is int and 0 <= lead <= 255 and 0 <= war <= 255:
        return lead + war
    return None


def officer_politics(officer):
    value = ((officer or {}).get('attributes') or {}).get('pol')
    return value if type(value) is int and 0 <= value <= 255 else None


def blade_numbers(officers):
    values = [value for value in (lead_war_total(officer) for officer in officers or []) if value is not None]
    if not values:
        return None, None
    return max(values), sum(values) / len(values)


def max_politics(officers):
    values = [value for value in (officer_politics(officer) for officer in officers or []) if value is not None]
    return max(values) if values else None


def five_total(officer):
    attrs = officer.get('attributes') or {}
    values = [attrs.get(key) for key in KEYS]
    if all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in values):
        return sum(values)
    return None


def known_five_totals(officers):
    return [total for total in (five_total(officer) for officer in officers or []) if total is not None]


def city_five_avg(officers):
    totals = known_five_totals(officers)
    if not totals:
        return None
    return sum(totals) / len(totals)


def number_floor(text):
    raw = str(text or '').strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def meets_floor(value, floor):
    if floor is None:
        return True
    return type(value) in (int, float) and math.isfinite(value) and value >= floor


FLOOR_KEYS = ('blade', 'blade_avg', 'pol', 'ride', 'bow', 'navy', 'ambush')


def passes_city_filters(row, query='', floors=None):
    """Keep a city when its name matches and every filled floor is met. Blank floors are unlimited."""
    floors = floors or {}
    needle = str(query or '').strip().lower()
    if needle and needle not in f"{row.get('name', '')} {row.get('owner', '')}".lower():
        return False
    return all(meets_floor(row.get(key), floors.get(key)) for key in FLOOR_KEYS)


def format_five_avg(value):
    if value is None:
        return '—'
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f'{value:.1f}'


def city_five_averages(state):
    rows, _meta = summarize(state)
    return {row['city'].get('city_id'): row.get('blade_avg') for row in rows}


def city_for_officer(state, officer):
    city_id = (officer or {}).get('location_city_id')
    if type(city_id) is not int:
        return None
    for city in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        if city.get('city_id') == city_id and city.get('type') != 'barrier':
            return city
    return None


def affinity_gap(ruler, officer_value):
    """Circular 相性 distance on 1–150. 0 is closest, 75 is farthest."""
    if type(ruler) is not int or type(officer_value) is not int:
        return None
    if not 1 <= ruler <= AFFINITY_CIRCLE or not 1 <= officer_value <= AFFINITY_CIRCLE:
        return None
    diff = abs(ruler - officer_value)
    return min(diff, AFFINITY_CIRCLE - diff)


def affinity_weight(gap):
    if type(gap) is not int or not 0 <= gap <= 75:
        return None
    return 76 - gap


def ruler_affinity(state):
    """Confirmed player's ruler, matched to website 相性. Prestige is not used."""
    fid = player_id(state)
    if fid is None:
        return {'compatibility': None, 'why': '我方未确认'}
    entities = (state or {}).get('entities') or {}
    force = next((row for row in entities.get('lords') or [] if row.get('force_id') == fid), None)
    if force is None:
        return {'compatibility': None, 'why': '我方未确认'}
    ruler_id = force.get('ruler_general_id')
    matches = [row for row in entities.get('generals') or []
               if row.get('general_id_raw') == ruler_id and row.get('owner_raw') == fid]
    if len(matches) != 1:
        return {'compatibility': None, 'why': '君主未定位', 'force': force.get('name')}
    ruler = matches[0]
    compatibility = website_compatibility(ruler)
    if compatibility is None:
        return {'compatibility': None, 'why': '君主相性未匹配', 'name': ruler.get('name'), 'force': force.get('name')}
    return {'compatibility': compatibility, 'why': None, 'name': ruler.get('name'), 'force': force.get('name')}


def affinity_ranks(officers, ruler_compatibility):
    """Closer 相性 first. Share is a linear weight among matched officers, not a hit rate."""
    rows = []
    for officer in officers or []:
        gap = affinity_gap(ruler_compatibility, website_compatibility(officer))
        weight = affinity_weight(gap)
        rows.append({'officer': officer, 'gap': gap, 'weight': weight, 'share': None, 'blade': lead_war_total(officer)})
    known = [row for row in rows if row['weight'] is not None]
    total = sum(row['weight'] for row in known)
    for row in known:
        row['share'] = row['weight'] / total if total else None
    rows.sort(key=lambda row: (
        row['gap'] is None,
        row['gap'] if row['gap'] is not None else 0,
        -(row['blade'] if row['blade'] is not None else -1),
        (row['officer'] or {}).get('general_id_raw') or 0,
    ))
    return rows


def likely_recruit_label(officers, ruler_compatibility):
    if not officers or ruler_compatibility is None:
        return '—'
    known = [row for row in affinity_ranks(officers, ruler_compatibility) if row['gap'] is not None]
    if not known:
        return '相性未匹配'
    best = known[0]['gap']
    parts = []
    for row in known:
        if row['gap'] != best:
            break
        officer = row['officer']
        name = officer.get('name') or '姓名未解码'
        parts.append(f"{name} {row['blade']}" if row['blade'] is not None else name)
    return '、'.join(parts)


def format_share(share):
    return '—' if share is None else f'{share * 100:.1f}%'


def blade_order_label(officers):
    """Wild officers in this city, highest 统率＋武力 first."""
    ordered = sorted(officers or [], key=lambda officer: (
        lead_war_total(officer) is not None,
        lead_war_total(officer) or 0,
        officer_politics(officer) or 0,
        (officer or {}).get('general_id_raw') or 0,
    ), reverse=True)
    if not ordered:
        return '—'
    parts = []
    for officer in ordered:
        name = officer.get('name') or '姓名未解码'
        blade = lead_war_total(officer)
        parts.append(f'{name} {blade}' if blade is not None else name)
    return '、'.join(parts)


def city_wild_officers(state, city):
    """Wild officers currently located in this city. Barriers stay excluded."""
    city_id = city.get('city_id') if city else None
    if type(city_id) is not int:
        return []
    wild, _hidden = wild_location_groups(state or {})
    rows = [officer for officer in wild if officer.get('location_city_id') == city_id]
    rows.sort(key=lambda officer: (lead_war_total(officer) is not None, lead_war_total(officer) or 0,
                                   officer_politics(officer) or 0, officer.get('general_id_raw') or 0), reverse=True)
    return rows


def listed_skill_count(officers, names):
 n=0
 for officer in officers or []:
  skills=skills_for(officer)
  if ALL_SKILLS in skills or skills & names:
   n+=1
 return n


def skill_percent(officers, names):
    """Share of this city's wild officers who have the skill, as a whole percent."""
    total = len(officers or [])
    if not total:
        return None
    return int(round(100 * listed_skill_count(officers, names) / total))
def summarize(state):
 entities=state.get('entities',{});wild,hidden=wild_location_groups(state)
 cities=entities.get('cities_and_barriers',[]);ids=[c.get('city_id') for c in cities]
 unique={i for i in ids if i is not None and ids.count(i)==1};groups={i:[] for i in unique};unlocated=0
 for g in wild:
  cid=g.get('location_city_id')
  if cid in groups:groups[cid].append(g)
  else:unlocated+=1
 forces={f['force_id']:f.get('name','未知') for f in entities.get('lords',[])};rows=[]
 for c in cities:
  if c.get('city_id') not in unique or c.get('type')=='barrier':continue
  gs=groups[c['city_id']];blade,blade_avg=blade_numbers(gs)
  row={'city':c,'name':c.get('name','?'),'owner':forces.get(c.get('owner_raw'),'无主/未知'),'total':len(gs),'blade':blade,'blade_avg':blade_avg,'pol':max_politics(gs),'blades':blade_order_label(gs)}
  for key,_title,names in SKILL_COLS:
   row[key]=skill_percent(gs, names)
  rows.append(row)
 return rows,{'total':len(wild),'unlocated':unlocated,'hidden_barriers':len(hidden)}
COLS=[('name','城池',85),('owner','势力',60),('total','在野总数',85)]
COLS.extend((key,title,55) for key,title,_names in SKILL_COLS)
COLS.extend([('blade','最高统武',80),('blade_avg','平均统武',80),('pol','最高政治',70),('blades','统武顺序',420)])
class CityTalent(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg='#f7f4ea');self.app=app;self.rows={};self.order=('total',True);self.busy=False
  bar=tk.Frame(self,bg='#f7f4ea');bar.pack(fill='x',padx=8,pady=6)
  tk.Label(bar,text='城池 / 势力',bg='#f7f4ea').pack(side='left');self.query=tk.StringVar();tk.Entry(bar,textvariable=self.query,width=16).pack(side='left',padx=6);self.query.trace_add('write',lambda *_:self.refresh())
  tk.Label(bar,text='最高统武≥',bg='#f7f4ea').pack(side='left')
  self.blade_floor=tk.StringVar();tk.Entry(bar,textvariable=self.blade_floor,width=6).pack(side='left',padx=(2,8))
  tk.Label(bar,text='政治≥',bg='#f7f4ea').pack(side='left')
  self.pol_floor=tk.StringVar();tk.Entry(bar,textvariable=self.pol_floor,width=6).pack(side='left',padx=2)
  tk.Label(bar,text='平均统武≥',bg='#f7f4ea').pack(side='left',padx=(8,0))
  self.blade_avg_floor=tk.StringVar();tk.Entry(bar,textvariable=self.blade_avg_floor,width=6).pack(side='left',padx=(2,8))
  self.skill_floors={}
  for key,title,_names in SKILL_COLS:
   tk.Label(bar,text=f'{title}≥',bg='#f7f4ea').pack(side='left')
   var=tk.StringVar();self.skill_floors[key]=var
   tk.Entry(bar,textvariable=var,width=4).pack(side='left')
   tk.Label(bar,text='%',bg='#f7f4ea').pack(side='left',padx=(0,8))
   var.trace_add('write',lambda *_:self.refresh())
  self.blade_floor.trace_add('write',lambda *_:self.refresh());self.pol_floor.trace_add('write',lambda *_:self.refresh());self.blade_avg_floor.trace_add('write',lambda *_:self.refresh())
  self.note=tk.Label(self,bg='#f7f4ea',fg='#675937',anchor='w',justify='left',wraplength=1050);self.note.pack(fill='x',padx=8,pady=4)
  box=tk.Frame(self);box.pack(fill='both',expand=True);self.tree=ttk.Treeview(box,columns=[k for k,_,_ in COLS],show='headings')
  for k,title,width in COLS:self.tree.heading(k,text=title,command=lambda key=k:self.sort(key));self.tree.column(k,width=width,stretch=False)
  y=ttk.Scrollbar(box,command=self.tree.yview);x=ttk.Scrollbar(box,orient='horizontal',command=self.tree.xview);self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);x.pack(side='bottom',fill='x');y.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
  self.tree.bind('<Double-1>',self.locate)
 def sort(self,key):self.order=(key,not self.order[1] if self.order[0]==key else True);self.refresh()
 def refresh(self):
  if not self.app.doc:return
  rows,meta=summarize(self.app.doc);q=self.query.get().strip()
  floors={
   'blade':number_floor(self.blade_floor.get()),
   'blade_avg':number_floor(self.blade_avg_floor.get()),
   'pol':number_floor(self.pol_floor.get()),
  }
  floors.update({key:number_floor(var.get()) for key,var in self.skill_floors.items()})
  rows=[r for r in rows if passes_city_filters(r,q,floors)]
  key,reverse=self.order
  def value(r):return (r.get(key) is not None,r[key] if r.get(key) is not None else 0,r['total'],r.get('blade') or 0)
  rows.sort(key=value,reverse=reverse)
  self.note.configure(text=f"全图在野 {meta['total']} 人 · 已隐藏关隘 {meta['hidden_barriers']} 人 · 所在城未确认 {meta['unlocated']} 人。最高统武、平均统武是本城在野的统率＋武力。统武顺序是本城在野按统武从高到低，姓名后是统武。最高政治是本城在野里最高的政治。骑/弓/水/埋伏是本城在野里具备该技能的百分比，全技能计入各项。筛选留空不限；骑/弓/水/埋伏按百分比。未同名且五维一致的不计入技能。点列头排序，双击城池打开全图定位。")
  self.busy=True;self.tree.delete(*self.tree.get_children());self.rows={}
  skill_keys={key for key,_title,_names in SKILL_COLS}
  for i,row in enumerate(rows):
   vals=[]
   for k,_,_ in COLS:
    value=row[k]
    if value is None:
     vals.append('—')
    elif k=='blade_avg':
     vals.append(format_five_avg(value))
    elif k in skill_keys:
     vals.append(f'{value}%')
    else:
     vals.append(value)
   self.tree.insert('','end',iid=str(i),values=vals);self.rows[str(i)]=row
  self.busy=False
 def locate(self,event=None):
  if self.busy:return
  if event is not None and getattr(event,'x',None) is not None and getattr(event,'y',None) is not None:
   if self.tree.identify_region(event.x,event.y)!='cell':return
  iid=None
  if event is not None and getattr(event,'y',None) is not None:
   iid=self.tree.identify_row(event.y)
   if iid:self.tree.selection_set(iid)
  if not iid:
   ids=self.tree.selection();iid=ids[0] if ids else None
  if iid and iid in self.rows:
   self.app.locate_object('cities',self.rows[iid]['city'],prefer_world=True,nation_view=True)


class CityWildPanel(tk.Frame):
 def __init__(self,parent,app=None):
  super().__init__(parent,bg='#f7f4ea')
  self.app=app;self.rows={};self.city=None;self.state=None;self.busy=False;self.order=('chance',True);self.probability={}
  self.heading=tk.Label(self,bg='#f7f4ea',fg='#3f3420',anchor='w',justify='left',font=('Microsoft YaHei',12,'bold'))
  self.heading.pack(fill='x',padx=10,pady=(10,2))
  self.note=tk.Label(self,bg='#f7f4ea',fg='#675937',anchor='w',justify='left',wraplength=1080)
  self.note.pack(fill='x',padx=10)
  self.detail=tk.Label(self,bg='#f4efe0',fg='#3f3420',anchor='w',justify='left',wraplength=1080)
  self.detail.pack(fill='x',padx=10,pady=6)
  box=tk.Frame(self);box.pack(fill='both',expand=True,padx=8,pady=(0,8))
  self.tree=ttk.Treeview(box,columns=[key for key,_,_ in WILD_COLS],show='headings')
  for key,title,width in WILD_COLS:
   self.tree.heading(key,text=title,command=lambda k=key:self.sort(k));self.tree.column(key,width=width,stretch=False)
  y=ttk.Scrollbar(box,command=self.tree.yview);self.tree.configure(yscrollcommand=y.set)
  y.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
  self.tree.bind('<<TreeviewSelect>>',self.pick)
  self.clear()

 def clear(self,text='点城池后列出该城在野武将的统武和政治。'):
  self.city=None;self.state=None;self.rows={};self.rank_rows={}
  self.heading.configure(text='本城在野')
  self.note.configure(text=text)
  self.detail.configure(text='')
  self.busy=True;self.tree.delete(*self.tree.get_children());self.busy=False

 def focus(self,state,city,officer=None):
  self.state=state;self.city=dict(city or {})
  officers=city_wild_officers(state,self.city)
  self.probability=city_probabilities(state,self.city.get('city_id'),player_id(state))
  probabilities=self.probability['rows']
  key,reverse=self.order
  def sort_value(row):
   value={'name':row.get('name'),'id':row.get('general_id_raw'),'blade':lead_war_total(row),'pol':officer_politics(row)}.get(key)
   if key in ('threshold','chance'):value=probabilities.get(row.get('general_id_raw'),{}).get(key)
   if key=='chance' and value is not None:value=round(value,14)
   return value
  known=[r for r in officers if sort_value(r) is not None]
  unknown=[r for r in officers if sort_value(r) is None]
  officers=sorted(known,key=lambda r:(sort_value(r),lead_war_total(r) or 0,officer_politics(r) or 0,-r.get('general_id_raw',0)),reverse=reverse)+unknown
  name=self.city.get('name') or '该城'
  self.heading.configure(text=f'{name} · 在野 {len(officers)} 人')
  context=f"{self.probability.get('force_name') or '我方'} · 民望 {self.probability.get('prestige') if self.probability.get('prestige') is not None else '—'}"
  reason=self.probability['reason']
  summary=reason if reason else f"本城至少录到一人估算 {(1-self.probability['none_chance'])*100:.2f}%"
  self.note.configure(text=f'{context}；{summary}。门槛是轮到该将时通过判定的阈值；录取估算计入同城竞争，假设随机顺序、独立均匀判定，未计其他势力先录走及本回合待结算变化。仅当前采集候选，非实测成功率。点击列头排序。')
  self.busy=True;self.tree.delete(*self.tree.get_children());self.rows={}
  selected='0'
  want=None if officer is None else officer.get('general_id_raw')
  for index,row in enumerate(officers):
   blade=lead_war_total(row)
   pol=officer_politics(row)
   probability=probabilities.get(row.get('general_id_raw'),{})
   values=(
    row.get('name') or '姓名未解码',
    row.get('general_id_raw') if row.get('general_id_raw') is not None else '—',
    blade if blade is not None else '—',
    pol if pol is not None else '—',
    f"{probability['threshold']}/100" if probability.get('threshold') is not None else '—',
    f"≈{probability['chance']*100:.2f}%" if probability.get('chance') is not None else '—',
   )
   iid=str(index);self.tree.insert('','end',iid=iid,values=values);self.rows[iid]=row
   if want is not None and row.get('general_id_raw')==want:
    selected=iid
  self.busy=False
  self.detail.configure(text='点列表中的武将查看属性。' if officers else f'{name} 当前没有可显示的在野武将。')
  if officers:
   self.tree.selection_set(selected);self.tree.see(selected);self.pick()

 def sort(self,key):
  self.order=(key,not self.order[1] if self.order[0]==key else True)
  ids=self.tree.selection();selected=self.rows.get(ids[0]) if ids else None
  if self.state is not None:self.focus(self.state,self.city,selected)

 def refresh(self,state):
  if not self.city:return
  cities=[c for c in (state.get('entities') or {}).get('cities_and_barriers',[]) if c.get('city_id')==self.city.get('city_id') and c.get('type')=='city']
  if len(cities)!=1:self.clear('该城已不在当前采集状态中。');return
  ids=self.tree.selection();selected=self.rows.get(ids[0]) if ids else None
  self.focus(state,cities[0],selected)

 def pick(self,_=None):
  if self.busy:return
  ids=self.tree.selection()
  if not ids or ids[0] not in self.rows:return
  officer=self.rows[ids[0]]
  parts=[f"{officer.get('name') or '姓名未解码'}  ID {officer.get('general_id_raw','?')}"]
  blade=lead_war_total(officer)
  pol=officer_politics(officer)
  parts.append(f"统武 {blade if blade is not None else '—'}　政治 {pol if pol is not None else '—'}")
  probability=self.probability.get('rows',{}).get(officer.get('general_id_raw'),{})
  if probability.get('excluded'):parts.append('原版跳过此将')
  elif probability.get('threshold') is not None:parts.append(f"轮到判定门槛 {probability['threshold']}/100")
  if probability.get('chance') is not None:parts.append(f"本城录取估算 ≈{probability['chance']*100:.2f}%")
  self.detail.configure(text='　'.join(parts))
  locator=getattr(self.app,'object_locator',None)
  if locator is not None and self.state is not None:
   locator.update_state(self.state)
   locator.focus_officer(officer,recenter=False)
