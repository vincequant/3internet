"""Read-only guide models. Evidence labels never upgrade estimates to sync proof."""
import json
from pathlib import Path
import sys
BRIDGE=Path(__file__).resolve().parents[1]/'bridge'
if str(BRIDGE) not in sys.path:sys.path.insert(0,str(BRIDGE))
from recruitment_probability import BUILD,city_probabilities
CARD_NAMES=json.loads(Path(__file__).with_name('card_catalog.json').read_text(encoding='utf8'))['names']
# 43f8ad via 43f507: false means retained by the ordinary full-hand seasonal branch.
PROTECTED=frozenset({7,10,*range(15,26)})
SYNC_ROWS=(
 ('骑兵训练参数1000','双Mac结算一致','96→300；金26628→25628。只核准这一笔，不代表所有训练或服务器验证。'),
 ('弓兵训练参数300','双Mac结算一致','180→234；金28128→26628。弓/步参数1000仍缺两端结算对照。'),
 ('原版施舍参数195','双Mac结算一致','民望163→200；两端金22378、粮154101。不能推广为任意数值可同步。'),
 ('普通城市招揽','双Mac结算一致','江陵鄂焕、西河褒姒两笔归属一致；不保证指定将，不校准统计胜率。'),
 ('指定武将必得 / 本机改满训','已发现不同步，已下架','曾出现将领归属不同、训练300/114等差异。'),
 ('回合加10秒','本机功能，保留','玩家限时局未验收；没有证明改变双方时间或服务器超时。'),
 ('外交换卡 / 排序 / 随机数修改','尚未做修改后双端对照','原版牌组路径已定位。不能据此添加“必抽指定卡”。'),
 ('其他内政、外交数值参数','待研究','优先查原版指令确实传递的操作数、费用和上限，再逐项双端结算；目前没有新增成功例。'),
)
RECRUIT_TEXT=(
 '招揽先把同城在野将打乱，再逐个判定，第一个成功的人入队。选中名册某将，实际提交的是他所在城，可能录到同城别人。',
 '“轮到他时”只算这一关；“整笔录到他”还要扣掉同城别人先成功的机会。政治、统武和魅力不参与已核准的这段命中判定。',
 '民望提高，会让同城各将的门槛一起提高，并不会压低低属性将的条件成功率。因此想录的人未必明显受益。',
 '正常民望上限200；关系匹配项达到最佳时，被轮到的门槛可以到100/100。但有人先成功、另一势力先录走，都仍会阻止你得到目标。',
 '进阶公式：D=min(|a−b|, |a+b−150|)，门槛T=四舍五入[民望×max(15,150−D)÷300]；随机余数小于T才成功。a、b是目标和君主的原始隐藏关系字节，尚未把它们等同于网站相性。',
 '表中百分比是随机顺序、独立均匀随机判定的模型估算；实际随机数是确定性序列，均匀/独立及对方竞争未验证。民望200栏只作情景对比，不是假定已施舍，也不称整体概率的绝对最大值。',
)
CARD_TEXT=(
 '原版使用公共牌组，不是每一格独立从28种卡中随机选一种。洗牌会反复按“随机数 % 剩余张数”取出实体牌；领取时沿顺序找可领取的牌，并登记归属。',
 '可领取还要求这张实体牌处于未分配状态，并符合本局开关。只知道五张手牌，不足以算剩余牌的数量、权重或下一张。',
 '普通满手季更分支会从左向右找第一张可替换的牌，优先跳过保护类；如果五张全是保护类，原版会回退丢弃第一张。想保留的普通牌可移到右侧。这是原版路径结论，是否有待执行换卡、已使用牌、全换卡等还会改变结果。',
 '援助友军、斩杀使者、策反及皇帝诏书至吴越春秋这一组，在该满手分支优先保留，不是永久保护；“更换手中卡”会处理普通牌，“更换众人卡片”走另一条全局处理路径。',
 '随机数由55项状态表加游标生成；相同状态和调用顺序可复算，其他随机判定也会消耗它。修改本机随机数或牌组顺序可能让两端走向不同结果。',
 '目前不能预先锁定下季度的指定卡。尚缺当前公共牌组实体顺序、分配/可用标记、随机状态、双方待执行指令与结算顺序的联合核验；没有接入强制抽卡按钮。',
)

def card_rows(force):
 slots=(force or {}).get('hand_cards',{}).get('slots') or []
 return [dict(slot=c.get('slot'),name=c.get('name') or CARD_NAMES.get(str(c.get('card_id')),'未知'),
              card_id=c.get('card_id'),seasonal=('保护类' if c['card_id'] in PROTECTED else '可替换类')
              if type(c.get('card_id')) is int and 1<=c['card_id']<=28 else '未确认') for c in slots]

def recruit_rows(state,force_id,city_id=None,min_blade=150):
 """Compute from complete city pools BEFORE any display filtering. Do not mutate snapshot."""
 s=state or {};entities=s.get('entities') or {};generals=entities.get('generals') or []
 cities={c.get('city_id'):c for c in entities.get('cities_and_barriers',[]) if c.get('type')=='city'}
 force=next((f for f in entities.get('lords',[]) if f.get('force_id')==force_id),None)
 if not force:return [],'所选势力未确认'
 high=dict(s,entities=dict(entities,lords=[dict(f,prestige=200) if f is force else f for f in entities.get('lords',[])]))
 ids=sorted({g['location_city_id'] for g in generals if g.get('status_code')==1 and type(g.get('location_city_id')) is int and g['location_city_id'] in cities})
 output=[];reasons=set()
 unplaced=sum(g.get('status_code')==1 and g.get('location_city_id') not in cities for g in generals)
 if unplaced:reasons.add(f'另有{unplaced}名在野将无有效城池记录，未列入')
 for cid in ids:
  if city_id is not None and cid!=city_id:continue
  now=city_probabilities(s,cid,force_id);maxp=city_probabilities(high,cid,force_id)
  if now['reason']:reasons.add(now['reason'])
  for g in generals:
   if g.get('status_code')!=1 or g.get('location_city_id')!=cid:continue
   attrs=g.get('attributes') or {};lead=attrs.get('lead');war=attrs.get('war')
   blade=lead+war if type(lead) is int and type(war) is int else None
   if min_blade is not None and (blade is None or blade<=min_blade):continue
   gid=g.get('general_id_raw');n=now['rows'].get(gid,{});m=maxp['rows'].get(gid,{})
   output.append(dict(gid=gid,name=g.get('name') or '?',city=cities.get(cid,{}).get('name') or f'城#{cid}',
      city_id=cid,blade=blade,lead=lead,war=war,chance=n.get('chance'),chance200=m.get('chance'),
      threshold=n.get('threshold'),threshold200=m.get('threshold'),pool=now['pool_count'],excluded=n.get('excluded')))
 output.sort(key=lambda r:(-(r['chance'] if r['chance'] is not None else -1),-(r['blade'] or 0),str(r['gid'])))
 return output,'；'.join(sorted(reasons))

def percent(value):return '未知' if value is None else f'{value*100:.2f}%'
