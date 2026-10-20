"""Conditional annual summer recruitment from already capped city getters.

Engine 0x434df9/0x434e8d/0x434f21 each sum one camp type then min with
0x434fb5. Remain is per-kind slack vs that same numeric ceiling, not
one city-wide pool: building parade grounds does not reduce cavalry/bow slack.
"""
KINDS=('infantry','cavalry','bow')
KIND_LABEL={'infantry':'步','cavalry':'骑','bow':'弓'}
BUILDING_KINDS={'parade_ground':'infantry','horse_farm':'cavalry','bow_studio':'bow'}
PRODUCE_SCORE_WEIGHTS={'infantry':1,'cavalry':3,'bow':1}

def population_cap(population):
 if type(population) is not int or population<0:return None
 return 0 if population<50000 else min(((population+50)//100)*10,50000)

def building_sums(state,city_id):
 totals=dict.fromkeys(KINDS,0)
 for building in (state or {}).get('entities',{}).get('production_buildings') or []:
  kind=BUILDING_KINDS.get(building.get('type'))
  if kind and building.get('linked_city_id')==city_id and type(building.get('building_ui_amount')) is int:
   totals[kind]+=building['building_ui_amount']
 return totals

def format_recruit_cell(built,cap):
 # remain = this kind's camps vs population cap; other kinds do not consume it
 if cap is None:return '帽未知'
 if type(built) is not int:return '未采集'
 slack=cap-built
 if slack>=0:return f'{slack:,}'
 return f'溢{-slack:,}'

def format_recruit_display(built,cap):
 remain=format_recruit_cell(built,cap)
 if type(built) is not int:
  return remain
 return f'{remain} · 已建{built:,}'

def recruit_view(state,city):
 if (city or {}).get('type')!='city':
  return {'cap':None,'cap_text':'—','built':None,'cells':{k:'—' for k in KINDS}}
 cap=(city.get('recruitment_capacity') or {}).get('population_cap')
 if cap is None:cap=population_cap(city.get('population'))
 built=building_sums(state,city.get('city_id'))
 cap_text=f'{cap:,}' if type(cap) is int else '未采集'
 return {'cap':cap,'cap_text':cap_text,'built':built,
         'cells':{k:format_recruit_cell(built[k],cap) for k in KINDS}}

def city_recruit_rows(state,force_id):
 # cells[kind] = cap - built[kind]; kinds do not share remaining quota
 cities=[c for c in (state or {}).get('entities',{}).get('cities_and_barriers',[]) if c.get('type')=='city' and c.get('owner_raw')==force_id]
 rows=[]
 for city in cities:
  view=recruit_view(state,city)
  rows.append({'name':city.get('name') or '?','cap':view['cap'],'built':view['built'],
               'cells':view['cells']})
 return rows
def annual_recruitment(state,force_id):
 all_cities=(state or {}).get('entities',{}).get('cities_and_barriers')
 if not isinstance(all_cities,list) or force_id is None:return {k:{'known':0,'missing':1,'cities':0} for k in KINDS}
 cities=[c for c in all_cities if c.get('type')=='city' and c.get('owner_raw')==force_id]
 out={}
 for kind in KINDS:
  values=[(c.get('recruitment_capacity') or {}).get('amounts',{}).get(kind) for c in cities]
  good=[v for v in values if type(v) is int and v>=0]
  out[kind]={'known':sum(good),'missing':len(values)-len(good),'cities':len(cities)}
 return out
def recruitment_text(result):
 if result['missing']:return f"{result['known']:,}＋未知" if result['known'] else '未采集完整'
 return f"≈{result['known']:,}"

def recruit_raw(old_raw):
 # Live 2026-09-14 魏/宋春夏：新兵原值 = 旧库存原值 × 3/5 取整；满训 300 即教程 180。
 if not isinstance(old_raw,int) or not 0<=old_raw<=300:
  return None
 return old_raw*3//5

def mix_after_recruit(old_raw,stock,added):
 if recruit_raw(old_raw) is None or not isinstance(stock,int) or stock<0:
  return None
 if not isinstance(added,int) or added<0:
  return None
 incoming=recruit_raw(old_raw)
 if added==0:
  return {'recruit_raw':incoming,'stock':stock,'raw':old_raw,'added':0}
 new_stock=stock+added
 return {'recruit_raw':incoming,'stock':new_stock,'raw':(old_raw*stock+incoming*added)//new_stock,'added':added}

def city_produce_amount(state, city, kind):
    if (city or {}).get('type') != 'city' or kind not in KINDS:
        return None
    amounts = ((city.get('recruitment_capacity') or {}).get('amounts') or {})
    value = amounts.get(kind)
    if type(value) is int and value >= 0:
        return value
    cap = (city.get('recruitment_capacity') or {}).get('population_cap')
    if cap is None:
        cap = population_cap(city.get('population'))
    built = building_sums(state, city.get('city_id')).get(kind)
    if type(built) is int and type(cap) is int:
        return min(built, cap)
    return built if type(built) is int and built >= 0 else None


def cities_over_produce(state, kind, threshold):
    if type(threshold) is not int or threshold < 0 or kind not in KINDS:
        return []
    rows = []
    for city in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        amount = city_produce_amount(state, city, kind)
        if type(amount) is int and amount > threshold:
            rows.append(city)
    return rows


def city_produce_score(state, city, weights=None):
    weights = weights or PRODUCE_SCORE_WEIGHTS
    total = 0
    known = False
    for kind in KINDS:
        amount = city_produce_amount(state, city, kind)
        if type(amount) is int:
            known = True
            total += amount * int(weights.get(kind) or 0)
    return total if known else None


def city_card_text(state, city):
    if (city or {}).get('type') != 'city':
        return '关隘无夏季募兵。'
    lines = []
    for kind, label in (('infantry', '步'), ('cavalry', '骑'), ('bow', '弓')):
        amount = city_produce_amount(state, city, kind)
        lines.append(f'可产{label} {amount:,}' if type(amount) is int else f'可产{label} 未采集')
    score = city_produce_score(state, city)
    if type(score) is int:
        lines.append(f'总分(步1骑3弓1) {score:,}')
    return '\n'.join(lines)


def cities_over_produce_score(state, threshold, weights=None):
    if type(threshold) is not int or threshold < 0:
        return []
    rows = []
    for city in ((state or {}).get('entities') or {}).get('cities_and_barriers') or []:
        score = city_produce_score(state, city, weights)
        if type(score) is int and score > threshold:
            rows.append(city)
    return rows


def predicted_after_summer(kind_row,added):
 """Warehouse mix for training; warehouse+field total plus new recruits for stock."""
 row=kind_row or {}
 if not isinstance(added,int) or added<0:
  added=0
 warehouse=row.get('warehouse')
 total=row.get('total')
 mix=mix_after_recruit(row.get('raw'),warehouse,added)
 stock=total+added if isinstance(total,int) else (mix['stock'] if mix else None)
 return {'stock':stock,'raw':mix['raw'] if mix else None,'added':added,
         'recruit_raw':mix['recruit_raw'] if mix else None}
