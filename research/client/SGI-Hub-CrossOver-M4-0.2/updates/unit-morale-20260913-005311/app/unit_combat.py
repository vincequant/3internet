"""Pure read-only derivations; engine layout and website model are separate."""
import math
from collections import defaultdict
PARAMS={'步兵':(50,100,[0,100,200]),'强化步兵':(150,40,[0,100,200]),'重装步兵':(190,40,[0,100,200]),'骑兵':(100,50,[0,150,350]),'强化骑兵':(150,50,[0,150,350]),'重装骑兵':(200,50,[0,150,350]),'铁骑兵':(200,50,[0,150,350])}
COMBAT_TYPES=set(PARAMS)|{'弓兵','强弓兵','重装弓兵'}
def integer(v,lo,hi):return type(v) is int and lo<=v<=hi

def enrich_unit_combat(state):
    index=defaultdict(list)
    for g in state.get('entities',{}).get('generals',[]):
        index[g.get('general_id_raw')].append(g)
        if 'combat_modifier_flags' not in g and g.get('raw_hex'):
            b=bytes.fromhex(g['raw_hex'])
            if len(b)>0x44:g['combat_modifier_flags']=b[0x44]
    for u in state.get('entities',{}).get('field_units',[]):
        u.update(basic_combat_power=None,website_attack_power=None,combat_inputs=[],combat_missing=[])
        if u.get('unit_kind') not in COMBAT_TYPES:
            u['combat_missing']=['特殊部队未验证'];continue
        if u.get('raw_hex'):
            b=bytes.fromhex(u['raw_hex'])
            if len(b)>0x29:u['armament_degree_raw']=b[0x29]
        degree=u.get('armament_degree_raw')
        u['training_degree']=degree if integer(degree,0,100) else None
        u['training_verification']='unit+0x29; setter cap100 and attack consumers; GUI alignment pending'
        soldiers=u.get('soldiers_candidate')
        size=(int(soldiers>20000)+int(soldiers>35000)) if integer(soldiers,0,100000) else None
        u['size_index']=size;u['size_label']=['小队','中队','大队'][size] if size is not None else '未知'
        ids=u.get('general_ids',[])
        values=[];seen=set()
        for gid in ids:
            if gid is None:continue
            gs=index.get(gid,[])
            if gid in seen or len(gs)!=1:
                u['combat_missing'].append('武将ID缺失/重复/不唯一');continue
            seen.add(gid);g=gs[0];a=g.get('attributes',{});flags=g.get('combat_modifier_flags')
            if g.get('owner_raw')!=u.get('owner_raw') or g.get('status_code')!=2:
                u['combat_missing'].append('编成将归属/出阵状态待核验');continue
            if not integer(flags,0,255) or any(not integer(a.get(k),0,255) for k in ('lead','war')):
                u['combat_missing'].append('统武或修正位未采集（请重启采集服务）');continue
            lead=a['lead']+(a['lead']*2//5 if flags&0x10 else 0)
            war=a['war']+(a['war']*2//5 if flags&0x20 else 0)
            values.append((lead,war));u['combat_inputs'].append({'id':gid,'name':g.get('name'),'lead_effective':lead,'war_effective':war,'flags':flags})
        if not values:u['combat_missing'].append('无已验证编成将')
        if values and not u['combat_missing']:
            lead=values[0][0] if len(values)==1 else (values[0][0]+sum(v[0] for v in values[1:])//(len(values)-1))//2
            lead=max(10,lead);war=sum(v[1] for v in values)//len(values)
            u['basic_combat_power']=(lead+war)//2
        u['combat_verification']='static reproduction 0x477b4f/0x477c24/0x477cd0; actual GUI comparison pending'
        params=PARAMS.get(u.get('unit_kind'));ability=u['basic_combat_power']
        if params is None:u['combat_missing'].append('弓兵远射/攻城/肉搏参考见目标攻击列')
        if degree is None or not integer(degree,0,100):u['combat_missing'].append('部队武装/训练字段未采集')
        if size is None:u['combat_missing'].append('兵数/规模未确认')
        if ability is not None and not 0<=ability<=150:u['combat_missing'].append('战力超出网页输入域')
        if params and integer(degree,0,100) and size is not None and ability is not None and 0<=ability<=150:
            base,coefficient,bonuses=params
            u['website_attack_power']=math.floor(ability*(base+bonuses[size]+math.floor(coefficient*degree/100+.5))/150+.5)
        u['attack_verification']='website formula; W=unit+0x29 assumed; not engine damage or victory probability'
    from unit_target_attack import enrich_targets
    enrich_targets(state)
    return state
