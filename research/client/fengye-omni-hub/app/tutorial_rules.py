"""Tutorial-derived estimates; source rules never overwrite observed state."""
import math
from officer_reference import officer_metrics
from native_diplomacy import CARD_POINTS,envoy_score as native_envoy_score

RULES={
 '外交卡片':'一张功能卡，最多四张附加卡。主动提案、被动拒绝分别加成使者基础外交力20%，然后加卡点。教程截图169×1.2取整+110=313。声望高者优先接见，同声望有随机性。原版同点主动方胜；玉玺补300点，换牌卡不能补点。外交合法性、接见与结算顺序另算。',
 '战略内政':'招募针对城市，人数、相性和声望影响结果，不是点名必招；同城人数仅供竞争比较。卖米为当前一半，1金换5米。城市募兵上限为人口十分之一，断线影响募兵及建设。首都失守与迁都需关注；不自动下令。',
 '军事作战':'士气高先行动，同士气随机。城市3格、粮仓2格是补给参考，友敌、连线及距离算法仍需确认。换季在城士气增加参考为战力20%。原版无双为受击触发12.5%，该次防守士气项×1.5；奇袭按双方最高智力判定，最高25%；合击需满足围攻条件。弓、弩、连弩的远射与近战不同，不能统一套用骑步公式。',
 '游戏规则':'此页包含群盟战约定：打流亡一家算胜等，并非所有对局统一引擎条件。盟约、禁卡、同盟补给等须以当前房间设置为准；本Hub不自动把群规套到全电脑局。',
 '钱粮收支':'春收金、秋收粮。每城按信用、人口、商业/开发计算，首都倍增。武将粮俸=带兵数/10、金俸=带兵数/50。皇帝费用=min(金/25,1000)，仅确实供养时适用。落石维护两文分别700/750，采用范围提示，不伪装精确净收入。',
 '练兵技巧':'教程种子：原值300时夏季新兵180。实测新兵原值=旧原值×3/5取整，再与仓库加权。盖营中位：练兵所1.42万、弓工坊9240、牧场3225。一次训练折回1万以下100%：弓+20、骑+32、步约+50；9万以上对半。从零冲十万弩兵80：仓库空时练到300再收兵约14–15次；一万练到180再收九万约17次，囤十万再练约18次。连弩移动射击受罚。',
 '声望信用':'施舍+5至10；供养皇帝+1；释放俘虏+1至7。迁都-30、无法支付皇帝-30、无法付薪-10。未宣战进入领土/攻击城-70，野战攻击-50，是否适用需确认战争状态。直接接受与看牌后接受有不同声望范围。声望关联收入、接见、招募和出兵士气。'}
def num(v):return type(v) in (int,float) and math.isfinite(v) and v>=0

def city_economy(city,force):
 vals=[force.get('prestige'),city.get('population'),city.get('development'),city.get('commerce')]
 if not all(num(v) for v in vals):return None
 p,pop,dev,commerce=vals;factor=(100+p)/200;cap=2 if city.get('city_id')==force.get('capital_city_id') else 1
 return {'gold':factor*(pop/1000+commerce*2+100)*10*cap,'rice':factor*(pop/1000+dev*2+100)*25*cap,'recruit_cap':pop/10,'capital':cap==2}

def force_economy(state,force):
 cities=[c for c in state['entities']['cities_and_barriers'] if c.get('type')=='city' and c.get('owner_raw')==force['force_id']]
 rows=[(c,city_economy(c,force)) for c in cities];known=[r for _,r in rows if r]
 generals=[g for g in state['entities']['generals'] if g.get('owner_raw')==force['force_id']]
 salaries=[g.get('soldiers') for g in generals];salary=sum(salaries) if all(num(n) for n in salaries) else None
 return {'rows':rows,'gold':sum(r['gold'] for r in known),'rice':sum(r['rice'] for r in known),'missing':len(rows)-len(known),'salary_gold':salary/50 if salary is not None else None,'salary_rice':salary/10 if salary is not None else None,'gold_per_prestige':sum(r['gold']/(100+force['prestige']) for r in known),'rice_per_prestige':sum(r['rice']/(100+force['prestige']) for r in known)}

def diplomacy_score(g,cards,role):
 if role not in ('主动','被动'):raise ValueError(role)
 if not 1<=len(cards)<=5 or len({c['slot'] for c in cards})!=len(cards):return {'total':None,'why':'选择1至5个不同手牌槽'}
 missing=[c['name'] for c in cards if c.get('card_id') not in CARD_POINTS]
 if missing:return {'total':None,'why':'不能补点或点数未确认：'+('/'.join(missing))}
 cid=cards[0].get('card_id')
 actual_role='策反' if cid in (11,12,13,14,15) else '主动' if cid in range(1,8) else '被动' if cid in (8,9,10) else role
 score=native_envoy_score(g,actual_role)
 if score is None:return {'total':None,'why':'原版武将字段缺失，无法确认技能与宝物修正'}
 points=sum(CARD_POINTS[c['card_id']] for c in cards);actor=score['actor']
 return {'total':actor+points,'base':score['base'],'actor':actor,'cards':points,'why':f"政魅{score['base']}；技能"+('生效' if score['bonus'] else '未生效')+f'＝{actor}；卡牌+{points}','special':any(c['card_id']==17 for c in cards)}

def unit_rule_hint(state,u):
 n=u.get('soldiers_candidate');kind=u.get('unit_kind','');size=u.get('size_index');parts=[]
 if size in (0,1,2):
  if '骑' in kind:parts.append('移动力 '+str([16,13,10][size])+'–'+str([18,15,12][size])+'（骑马技能影响）')
  elif '步' in kind or '弓' in kind or '弩' in kind:parts.append('移动力 '+str([12,10,8][size]))
  if n in (20000,35000):parts.append('规模边界：教程与静态实现口径待核')
 force=next((f for f in state['entities']['lords'] if f['force_id']==u.get('owner_raw')),None);power=u.get('basic_combat_power')
 if force and num(force.get('prestige')) and num(power):parts.append('出兵基础士气参考 '+str(min(100,math.floor(force['prestige']/4+power/2)))+'（非当前士气）')
 if u.get('rice_candidate')==0:parts.append('粮候选为0：核对缺粮，每回合士气可能-10至20')
 if '弓' in kind or '弩' in kind:
  row=([220,300,400] if kind in ('连弩','重装弓兵') else [120,180,240] if kind in ('强弓兵','弩兵') else [80,140,200])
  if size in (0,1,2):parts.append(f'攻略远射基础{row[size]}+a（a训练项未定；非完整攻击力）')
  parts.append('视野不足不能射击；连弩大队沿表中“未改”旧值')
 return '；'.join(parts)
