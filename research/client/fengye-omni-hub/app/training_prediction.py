"""Conservative one-command training envelope from static SANPK 3.5 code.
No RNG reads, target calls, or game input. Actor eligibility remains unverified.
"""
from military_summary import troop_info
from player_view import local_projection
COEFF={'infantry':(2,1),'cavalry':(3,2),'bow':(1,1)}
# Inventory only changes the 10..5 training base; 100k is the floor, not a bonus.
STOCK_BRACKETS=((0,10000,10,'1万以下'),(10000,30000,9,'1–3万'),(30000,50000,8,'3–5万'),(50000,70000,7,'5–7万'),(70000,90000,6,'7–9万'),(90000,None,5,'9万以上'))
def muldiv(a,b,c):
 if c<=0 or min(a,b)<0:raise ValueError('nonnegative domain only')
 return (a*b+c//2)//c

def stock_training_base(stock):
 if not isinstance(stock,int) or not 0<=stock<=2000000:return None
 return max(5,10-muldiv(stock,5,100000))

def stock_bracket(stock):
 base=stock_training_base(stock)
 if base is None:return None
 for low,high,value,label in STOCK_BRACKETS:
  if value==base and stock>=low and (high is None or stock<high):
   return {'base':base,'percent':10*base,'label':label,'low':low,'high':high,'next_at':high,'remain':None if high is None else high-stock}
 return None

def efficiency_ratio(stock):
    row = stock_bracket(stock)
    if not row:
        return '未知'
    return f"{row['percent']}%"


def describe_stock_efficiency(stock):
 row=stock_bracket(stock)
 if not row:return '未知'
 text=f"{row['percent']}% · {row['label']}"
 if row['next_at'] is None:return text+' · 已是最低档'
 return text+f" · 再募{row['remain']:,}人→{row['percent']-10}%"

def predict_training(kind,raw,stock,politics_min=50,politics_max=140):
 if troop_info(kind,raw)['training'] is None or not isinstance(stock,int) or not 0<=stock<=2000000 or not 0<=politics_min<=politics_max<=140:return None
 cost=1000 if raw<100 else 1500 if raw<200 else 2000
 if raw==300:return {'raw_before':raw,'raw_after_min':300,'raw_after_max':300,'gain_min':0,'gain_max':0,'cost':cost,'verdict':'已经满级，不建议为训练收益消耗指令','upgrade':'无升级空间'}
 base=max(5,10-muldiv(stock,5,100000));a,b=COEFF[kind]
 lo=muldiv(base,a*max(50,politics_min),b*50)
 hi=muldiv(base+1,a*max(50,politics_max),b*50)
 low,high=min(300,raw+lo),min(300,raw+hi)
 threshold=100 if raw<100 else 200 if raw<200 else 300
 upgrade='必达'+('满级' if threshold==300 else '下一兵种等级') if low>=threshold else '可能'+('满级' if threshold==300 else '晋级') if high>=threshold else '本次范围内不晋级'
 return {'raw_before':raw,'raw_after_min':low,'raw_after_max':high,'gain_min':low-raw,'gain_max':high-raw,'uncapped_gain_min':lo,'uncapped_gain_max':hi,'cost':cost,'upgrade':upgrade,'verdict':upgrade,'overflow_possible':raw+hi>300}

def force_predictions(state,force):
 projection=local_projection(state,force['force_id'])
 own=projection is not None
 source=projection if own else force
 # All owned officers give a superset envelope; no claim that all can execute.
 pol=[g.get('attributes',{}).get('pol') for g in state['entities']['generals'] if g.get('owner_raw')==force['force_id']]
 pol=[v for v in pol if isinstance(v,int) and 0<=v<=100]
 upper=max([50]+[p+(2*p)//5 for p in pol]) if pol else 140
 result={}
 for kind in COEFF:
  raw=source.get('armament_raw',{}).get(kind);stock=source.get('troop_stock',{}).get(kind)
  pred=predict_training(kind,raw,stock,50,upper)
  if pred:
   pred.update(source='操作层' if own else '势力层',politics_range=[50,upper],gold=source.get('gold'),verification='static_formula_envelope; actor_selection/active_bonus not verified; not a guaranteed command availability check')
  result[kind]=pred
 return result

def describe_prediction(kind,p):
 if not p:return '训练预测暂不可用'
 a=troop_info(kind,p['raw_after_min']);b=troop_info(kind,p['raw_after_max'])
 end=f"{a['name']} {a['training']}" if p['raw_after_min']==p['raw_after_max'] else f"{a['name']} {a['training']} → {b['name']} {b['training']}"
 before=troop_info(kind,p['raw_before'])
 cost=f"金 {p['cost']:,} / 1 指令"
 if isinstance(p.get('gold'),int) and p['gold']<p['cost']:cost+='（金不足）'
 return f"按{p['source']}：{before['name']} {before['training']}\n下次估计：{end}\n有效增加 {p['gain_min']}–{p['gain_max']} · {p['upgrade']}\n{cost}"+('\n可能溢出，收益受上限限制' if p.get('overflow_possible') else '')
