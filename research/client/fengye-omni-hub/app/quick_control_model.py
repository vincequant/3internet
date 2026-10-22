"""Local test controls. All addresses derive from a bound, typed game instance."""
from datetime import datetime, timezone
import ntpath
from collections import Counter
from officer_reference import officer_metrics

BUILD = '1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2'
DESTRUCTOR_HOTFIX_BUILD = 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
SUPPORTED_BUILDS = (BUILD, DESTRUCTOR_HOTFIX_BUILD)
COMMANDS = {'recruit': 32836, 'infantry': 32822, 'cavalry': 32823, 'bow': 32824, 'alms':32935}
LABELS = {'extend': '回合 +10 秒', 'focus_unit':'定位当前部队', 'alms':'施舍 ×3',
          'infantry':'步兵·政治×3', 'cavalry':'骑兵·政治×3', 'bow':'弓兵·政治×3'}
TRAINING_POLITICS_FACTOR = 3
ALMS_FACTOR = 3


def alms_operand(remainder):
    """Native gain is remainder+5. This operand makes that gain three times as large.

    The game still does prestige + operand + 5, and still stops at 200.
    """
    if type(remainder) is not int:
        raise ValueError('施舍原版参数不是整数')
    return (remainder + 5) * ALMS_FACTOR - 5
KEYS = {'extend': 'F6', 'focus_unit':'F7', 'alms':'F11', 'infantry':'F8', 'cavalry':'F9', 'bow':'F10'}
VIRTUAL_KEYS = {action: 0x6f+int(key[1:]) for action,key in KEYS.items()}
RETIRED_ACTIONS = frozenset(('recruit_target','recruit_politics'))


def training_operand(payload):
    """Highest owned-officer politics times 3.

    Kept in this module so the Wine helper never loads the comparison panel.
    That panel imports tkinter, which the bundled Wine python does not have.
    Ties keep the earlier officer, same as the comparison panel.
    """
    from player_view import player_id
    state = (payload or {}).get('state') if isinstance((payload or {}).get('state'), dict) else (payload or {})
    force_id = player_id(state)
    if force_id is None:
        raise ValueError('尚未确认我方势力，未改训练参数')
    pick = None
    for officer in ((state.get('entities') or {}).get('generals') or []):
        if officer.get('owner_raw') != force_id:
            continue
        politics = (officer.get('attributes') or {}).get('pol')
        if type(politics) is not int or not 0 <= politics <= 255:
            continue
        if pick is None or politics > pick[0]:
            pick = (politics, officer.get('name') or '所属将')
    if pick is None:
        raise ValueError('读不到所属将政治，未改训练参数')
    politics, name = pick
    operand = politics * TRAINING_POLITICS_FACTOR
    if not 1 <= operand <= 255 * TRAINING_POLITICS_FACTOR:
        raise ValueError('所属将政治超出可提交范围，未改训练参数')
    return dict(politics=politics, name=name, operand=operand)


def require_available_action(action):
    """Reject retired commands before reads, patches, menu input or key dispatch."""
    if action in RETIRED_ACTIONS:
        raise ValueError('该功能已下架：双Mac实测指定必得／满值训练造成两端状态不一致')
    if action not in (*LABELS, 'recruit', 'inspect', 'recruit_probability', 'recruit_roster'):
        raise ValueError('不支持的快捷指令')
POLICIES = {'politics': '政治优选', 'ride_ambush': '统武·骑伏', 'bow_ambush': '统武·弓伏',
            'ride_charge_ambush': '统武·骑突伏'}


def binding(payload, now=None):
    state = payload.get('state'); ident = payload.get('identity')
    if not isinstance(state, dict) or not isinstance(ident, dict):
        raise ValueError('当前尚未进入游戏，等待本机采集桥发现新对局')
    if state.get('build_sha256') not in SUPPORTED_BUILDS:
        raise ValueError('当前游戏版本不受支持')
    captured = datetime.fromisoformat(state['capture_end'].replace('Z', '+00:00'))
    age = ((now or datetime.now(timezone.utc)) - captured).total_seconds()
    if not 0 <= age <= 10:
        raise ValueError('游戏状态已过期，请检查本机采集桥')
    if (type(ident.get('pid')) is not int or ident['pid'] <= 0
            or type(ident.get('creation_filetime')) is not int
            or ntpath.basename(ident.get('path', '')).lower() != 'sanpk.exe'):
        raise ValueError('游戏进程身份不完整')
    core = int(state['core_address'], 0)
    if not 0x10000 <= core <= 0x7ffe0000:
        raise ValueError('游戏对象地址不受支持')
    return dict(pid=ident['pid'], created=ident['creation_filetime'], image=ident['path'],
                core=core, source_id=payload['source_id'], build=state['build_sha256'])


SPELL_NAMES = (('火攻', 0x200), ('落石', 0x400), ('混乱', 0x4000), ('天雷', 0x1000))


def _spell_bonus(general):
    import struct
    from native_unit_rules import raw_bytes
    raw = raw_bytes(general)
    flags = struct.unpack_from('<H', raw, 0x44)[0] if len(raw) >= 0x46 else general.get('combat_modifier_flags_word')
    if type(flags) is not int or not 0 <= flags <= 0xffff:
        return 0
    return 10 if flags & 0x100 else 0


def _roster_special(general, skills, matched, intel):
    """Native skill word first. Website names only when that word was not stored."""
    from native_unit_rules import general_skill_mask
    from unit_special_chance import SPELLS, personal_special_percent
    mask = general_skill_mask(general)
    source = 'native' if mask is not None else None
    if mask is None and matched:
        mask = 0x200 | 0x400 | 0x4000 | 0x1000 if '全技能' in skills else 0
        if '全技能' not in skills:
            for name, bit in SPELL_NAMES:
                if name in skills:
                    mask |= bit
        source = 'website'
    if mask is None or intel is None:
        return None, [], source or 'unknown'
    return (personal_special_percent(intel, mask, _spell_bonus(general)),
            [name for name, bit, _counter, _divisor in SPELLS if mask & bit], source)


def _officer_roster_row(general, city):
    """Use the same verified skill reference for wild and owned rosters."""
    attrs=general['attributes'];reference=officer_metrics(general)
    matched=(all(type(attrs.get(k)) is int and 0<=attrs[k]<=255 for k in ('lead','war','intel','pol','cha'))
             and reference['current_diplomacy'] is not None)
    skills=set(reference['skills'].split(' / ')) if matched else set();all_skills='全技能' in skills
    status=general.get('status_code')
    intel=attrs.get('intel')
    intel=intel if type(intel) is int and 0<=intel<=255 else None
    special_percent,special_skills,special_source=_roster_special(general,skills,matched,intel)
    return dict(id=general['general_id_raw'],city_id=city.get('city_id') if city else None,
                name=general.get('name') or '姓名未知',city=(city.get('name') or '城名未知') if city else '位置未知',
                politics=attrs['pol'],lead=attrs['lead'],war=attrs['war'],blade=attrs['lead']+attrs['war'],
                intel=intel,special_percent=special_percent,special_skills=special_skills,special_source=special_source,
                attributes={k:attrs[k] for k in ('lead','war','intel','pol','cha') if type(attrs.get(k)) is int and 0<=attrs[k]<=255},
                skills=sorted(skills),skills_matched=matched,
                skills_source='website_unique_name_and_five_stats' if matched else 'unknown',
                ride=all_skills or '骑马' in skills,bow=all_skills or '弓箭' in skills,
                ambush=all_skills or bool(skills & {'埋伏','伏兵'}),charge=all_skills or bool(skills & {'奇袭','突击'}),
                success_probability=None,target_guaranteed=False,
                status_code=status,status=general.get('status_label') or f'状态{status}（未命名）')


def owned_candidates(payload,bound):
    """Read only our confirmed ownership, including unknown locations/statuses."""
    from player_view import player_id
    if binding(payload)!=bound:raise ValueError('本营名单来自另一游戏实例')
    state=payload['state'];fid=player_id(state)
    if fid is None:raise ValueError('尚未确认我方势力，暂不显示本营名单')
    entities=state['entities'];places=entities['cities_and_barriers'];cities={}
    for city in places:
        cid=city.get('city_id')
        if cid in cities:raise ValueError('城池身份重复')
        cities[cid]=city
    generals=entities['generals'];ids=Counter(g.get('general_id_raw') for g in generals);rows=[]
    for general in generals:
        gid=general.get('general_id_raw');owner=general.get('owner_raw');status=general.get('status_code')
        attrs=general.get('attributes',{})
        if type(owner) is not int or owner!=fid or type(gid) is not int or ids[gid]!=1:continue
        if type(status) is not int or status in (1,3,5):continue # wild, unborn, dead
        if any(type(attrs.get(k)) is not int or not 0<=attrs[k]<=255 for k in ('pol','lead','war')):continue
        city=cities.get(general.get('location_city_id'))
        if city and city.get('type')!='city':city=None
        row=_officer_roster_row(general,city);row.update(row_kind='owned',owner_id=fid)
        rows.append(row)
    rows.sort(key=lambda r:(-r['blade'],-r['politics'],r['id']))
    return rows


def wild_candidates(payload, bound, sort='politics'):
    current = binding(payload)
    if current != bound:
        raise ValueError('武将列表来自另一游戏实例，请重新连接')
    entities = payload['state']['entities']
    cities = {}
    for city in entities['cities_and_barriers']:
        cid = city.get('city_id')
        if cid in cities:
            raise ValueError('城池身份重复')
        cities[cid] = city
    rows = []
    identities = Counter(g.get('general_id_raw') for g in entities['generals'])
    for general in entities['generals']:
        if general.get('owner_raw') != 65535 or general.get('status_code') != 1:
            continue
        gid = general.get('general_id_raw'); cid = general.get('location_city_id')
        attrs = general.get('attributes', {}); city = cities.get(cid)
        if (type(gid) is not int or identities[gid] != 1 or not city or city.get('type') != 'city'
                or any(type(attrs.get(k)) is not int or not 0 <= attrs[k] <= 255 for k in ('pol','lead','war'))):
            continue  # Unknown location/abilities never become zero or recruitable.
        rows.append(_officer_roster_row(general,city))
    if sort not in ('politics','blade'):
        raise ValueError('未知排序方式')
    rows.sort(key=lambda r:(-r[sort],-r['blade' if sort=='politics' else 'politics'],r['id']))
    return rows


def select_candidate(payload, bound, policy, excluded_ids=()):
    """Maximum among current wild candidates, with no numeric threshold."""
    if policy not in POLICIES:
        raise ValueError('未知选将标准')
    rows = wild_candidates(payload, bound, 'politics' if policy == 'politics' else 'blade')
    rows = [r for r in rows if r['id'] not in excluded_ids]
    if policy != 'politics':
        kind = 'bow' if policy == 'bow_ambush' else 'ride'
        rows = [r for r in rows if r['skills_matched'] and r[kind] and r['ambush']]
        if policy == 'ride_charge_ambush':
            rows = [r for r in rows if r['charge']]
    if not rows:
        raise ValueError('当前没有可确认的'+POLICIES[policy]+'在野将；没有设置数值门槛，也不会改选其他类型')
    return dict(rows[0], policy=policy, eligible_count=len(rows),
                capture_end=payload['state']['capture_end'])


def validate_politics_request(payload, bound, request, excluded_ids=()):
    if request.get('policy') != 'politics':
        raise ValueError('仅保留政治最高录将；统武／技能指定录用已下架')
    row = select_candidate(payload, bound, 'politics', excluded_ids)
    if (request.get('general_id') != row['id'] or request.get('city_id') != row['city_id']
            or request.get('expected_attributes') != row['attributes']):
        raise ValueError('政治最高候选已变化；请刷新后再点，未提交招揽')
    return row


def candidate_previews(payload, bound, excluded_ids=()):
    """Use one fresh, identity-bound snapshot for all four display choices."""
    if binding(payload) != bound:
        raise ValueError('候选武将来自另一游戏实例')
    previews = {}
    for policy in POLICIES:
        try:
            previews[policy] = select_candidate(payload, bound, policy, excluded_ids)
        except ValueError as error:
            previews[policy] = dict(error=str(error))
    return previews


def candidate_label(policy, row=None, waiting='等待当前对局'):
    if not row:
        detail = waiting
    elif row.get('error'):
        detail = '无可确认候选'
    else:
        key, metric = ('politics', '政治') if policy == 'politics' else ('blade', '统武')
        detail = f'{row["name"]} · {metric} {row[key]}'
        if row.get('success_probability') is not None:
            detail += f'\n{row["city"]} · 估算 {row["success_probability"]*100:.2f}%'
    return POLICIES[policy] + '\n' + detail


def probability_candidate(payload, bound, policy, excluded_cities=()):
    """Probability first, selected attribute second. Filters never shrink pools."""
    from recruitment_probability import city_probabilities
    from player_view import player_id
    if policy not in POLICIES:
        raise ValueError('未知选将标准')
    state=payload['state']; fid=player_id(state)
    rows=wild_candidates(payload,bound,'politics' if policy=='politics' else 'blade')
    cities={}
    for row in rows:
        if row['city_id'] not in cities:
            cities[row['city_id']]=city_probabilities(state,row['city_id'],fid)
    eligible=[]
    for row in rows:
        if row['city_id'] in excluded_cities:continue
        if policy!='politics' and (not row['skills_matched'] or not row['ambush'] or not row['bow' if policy=='bow_ambush' else 'ride']):continue
        if policy=='ride_charge_ambush' and not row['charge']:continue
        model=cities[row['city_id']]; probability=model['rows'].get(row['id'],{})
        if probability.get('chance') is None or probability['chance']<=0:continue
        eligible.append(dict(row,success_probability=probability['chance'],threshold=probability['threshold'],
                             probability_model=model['model'],prestige=model['prestige'],
                             pool_signature=sorted([gid,p['threshold']] for gid,p in model['rows'].items())))
    if not eligible:
        reason=next((m['reason'] for m in cities.values() if m['reason']), '当前无可确认的候选，或所在城已提交招揽')
        raise ValueError(reason)
    metric='politics' if policy=='politics' else 'blade'
    eligible.sort(key=lambda r:(-round(r['success_probability'],14),-r[metric],-r['blade' if metric=='politics' else 'politics'],r['id']))
    return dict(eligible[0],policy=policy,eligible_count=len(eligible),capture_end=state['capture_end'])


def probability_previews(payload,bound,excluded_cities=()):
    previews={}
    for policy in POLICIES:
        try:previews[policy]=probability_candidate(payload,bound,policy,excluded_cities)
        except ValueError as error:previews[policy]={'error':str(error)}
    return previews


ROSTER_SKILLS = {'ride':'骑马', 'bow':'弓箭', 'charge':'突击／奇袭', 'ambush':'埋伏'}


def probability_roster(payload, bound):
    """Annotate all wild officers before any display filter changes the list."""
    from recruitment_probability import city_probabilities
    from player_view import player_id
    rows=wild_candidates(payload,bound,'blade');state=payload['state']
    fid=player_id(state);models={}
    for row in rows:
        cid=row['city_id']
        if cid not in models:models[cid]=city_probabilities(state,cid,fid)
        model=models[cid];estimate=model['rows'].get(row['id'],{})
        chances=[p.get('chance') for p in model['rows'].values()]
        chance=estimate.get('chance');none=model.get('none_chance')
        any_chance=None if none is None else 1-none
        ranked=(chance is not None and chance>0 and all(p is not None for p in chances))
        rank=1+sum(round(p,14)>round(chance,14) for p in chances) if ranked else None
        tied=rank==1 and sum(round(p,14)==round(chance,14) for p in chances)>1 if ranked else False
        row.update(success_probability=estimate.get('chance'),threshold=estimate.get('threshold'),
                   prestige=model.get('prestige'),probability_reason=model.get('reason') or '',
                   probability_model=model['model'],city_rank=rank,city_top_tied=tied,
                   city_pool_count=len(chances),city_any_probability=any_chance,
                   city_success_share=chance/any_chance if chance is not None and any_chance and any_chance>0 else None,
                   pool_signature=sorted([gid,p['threshold']] for gid,p in model['rows'].items()))
    return rows


def validate_roster_request(payload,bound,request,excluded_cities=()):
    """Recheck a user-selected officer without replacing them with a maximum."""
    expected=request.get('selection')
    if not isinstance(expected,dict):raise ValueError('未选中名册武将')
    matches=[r for r in probability_roster(payload,bound) if r['id']==expected.get('id')]
    if len(matches)!=1:raise ValueError('该将已不在当前在野名单，未提交招揽')
    row=matches[0]
    if row['city_id'] in excluded_cities:raise ValueError('本城本回合已提交招揽，请先结算')
    if row['success_probability'] is None or row['success_probability']<=0:
        raise ValueError('该将的录取估算未知或为0，未提交快捷招揽')
    if any(expected.get(k)!=row[k] for k in ('city_id','attributes','pool_signature','prestige')):
        raise ValueError('所选武将或同城竞争已变化，请刷新名册后再点；未提交招揽')
    return dict(row,policy='roster',capture_end=payload['state']['capture_end'])


def filter_roster(rows, sort='blade', required_skills=(), min_probability=None, search='', min_blade=None,
                  min_politics=None,max_politics=None,city_first_only=False,min_intel=None,max_intel=None):
    if sort not in ('blade','politics','probability','intel','special'):raise ValueError('未知名册排序方式')
    if type(city_first_only) is not bool:raise ValueError('未知同城排名筛选')
    required=set(required_skills)
    if required-set(ROSTER_SKILLS):raise ValueError('未知技能筛选')
    if min_probability is not None and (type(min_probability) not in (int,float) or not 0<=min_probability<=1):
        raise ValueError('未知概率筛选')
    if min_blade is not None and (type(min_blade) is not int or not 0<=min_blade<=510):
        raise ValueError('统武下限请输入0–510的整数，留空不限制')
    for limit in (min_politics,max_politics):
        if limit is not None and (type(limit) is not int or not 0<=limit<=255):
            raise ValueError('政治界限请输入0–255的整数，留空不限制')
    if min_politics is not None and max_politics is not None and max_politics<=min_politics:
        raise ValueError('政治上限须大于下限')
    for limit in (min_intel,max_intel):
        if limit is not None and (type(limit) is not int or not 0<=limit<=255):
            raise ValueError('智力界限请输入0–255的整数，留空不限制')
    if min_intel is not None and max_intel is not None and max_intel<=min_intel:
        raise ValueError('智力上限须大于下限')
    query=search.strip().casefold();result=[]
    for row in rows:
        if city_first_only and row.get('city_rank')!=1:continue
        if min_blade is not None and row['blade']<=min_blade:continue
        if min_politics is not None and row['politics']<=min_politics:continue
        if max_politics is not None and row['politics']>max_politics:continue
        if min_intel is not None or max_intel is not None:
            if type(row.get('intel')) is not int:continue
            if min_intel is not None and row['intel']<=min_intel:continue
            if max_intel is not None and row['intel']>max_intel:continue
        if required and (not row['skills_matched'] or not all(row[k] for k in required)):continue
        chance=row.get('success_probability')
        if min_probability is not None and (chance is None or chance<min_probability):continue
        if query and query not in f"{row['name']} {row['city']} {row['id']}".casefold():continue
        result.append(row)
    if sort=='probability':
        result.sort(key=lambda r:(r.get('success_probability') is None,
                    -round(r.get('success_probability') or 0,14),-r['blade'],-r['politics'],r['id']))
    elif sort=='intel':
        result.sort(key=lambda r:(r.get('intel') is None,-(r.get('intel') or 0),
                    r.get('special_percent') is None,-(r.get('special_percent') or 0),r['id']))
    elif sort=='special':
        result.sort(key=lambda r:(r.get('special_percent') is None,-(r.get('special_percent') or 0),
                    r.get('intel') is None,-(r.get('intel') or 0),r['id']))
    else:
        result.sort(key=lambda r:(-r[sort],-r['politics' if sort=='blade' else 'blade'],r['id']))
    return result


def roster_cell(row, key):
    if key in ('probability','city_success_share','city_any_probability'):
        chance=row.get('success_probability' if key=='probability' else key)
        return '—' if chance is None else f'≈{chance*100:.2f}%'
    if key=='city_rank':
        rank=row.get('city_rank')
        return '未知' if rank is None else f'第{rank}名/{row["city_pool_count"]}人'
    if key=='city_top':
        rank=row.get('city_rank')
        return '未知' if rank is None else ('并列第一' if row.get('city_top_tied') else '第一') if rank==1 else '非第一'
    if key=='intel':
        return '—' if row.get('intel') is None else row['intel']
    if key=='special':
        value=row.get('special_percent')
        return '—' if value is None else f'{value:.2f}%'
    if key in ROSTER_SKILLS:
        return ('有' if row[key] else '无') if row['skills_matched'] else '未知'
    return row[key]


def validate_probability_request(payload,bound,request,excluded_cities=()):
    row=probability_candidate(payload,bound,request.get('policy'),excluded_cities)
    expected=request.get('selection') or {}
    if any(expected.get(k)!=row[k] for k in ('id','city_id','attributes','pool_signature','prestige')):
        raise ValueError('概率候选或同城竞争已变化，请刷新后再点；未提交招揽')
    return row


def recruitment_hint(ready, orders_used=0, pending_names=()):
    if not ready:
        return '正在自动等待当前对局。'
    if orders_used >= 3:
        return '本回合3次指令已用完，请在游戏中结束战略回合。'
    if pending_names:
        return '待结算：'+'、'.join(pending_names)+f'。可继续录取下一名；本回合剩余{3-orders_used}次指令。'
    return '候选自动刷新；点击即提交一次招揽，正常结束战略回合后结算。'


def duration_ms(phase, setting, unit_count):
    """Exact 4447b2..444856. None means unlimited; unknown is rejected."""
    if type(phase) is not int or phase not in range(1, 6) or type(setting) is not int or setting not in range(4):
        raise ValueError('未知回合时间规则')
    if type(unit_count) is not int or not 0 <= unit_count <= 64:
        raise ValueError('部队数量未知')
    if phase == 1:
        return (60000, 90000, 120000, None)[setting]
    if phase == 2:
        return (20000, 40000, 60000, None)[setting]
    if unit_count:
        return (30000, 60000, 90000, None)[setting]
    return None if setting == 3 else 20000


def timer_value(state):
    total = duration_ms(state['phase'], state['time_setting'], state['unit_count'])
    if total is None:
        return None
    # GetTickCount and the game's subtraction use wrapping 32-bit integers.
    remaining = (state['start_tick'] - state['tick'] + total) & 0xffffffff
    return remaining if remaining < 0x80000000 else remaining - 0x100000000


def require_test_session(state, enabled):
    if not enabled:
        raise ValueError('请先勾选「启用本局快捷修改」')
    if state['mode'] not in (1, 2) or state['phase'] not in range(1, 6) or state['ending']:
        raise ValueError('当前不是可输入的游戏回合')


def require_menu(state, action, enabled):
    require_test_session(state, enabled)
    if action not in COMMANDS:
        raise ValueError('不支持的快捷指令')
    if (state['mode'] != 2 or state['phase'] != 1 or state['allowance'] != 1 or state['modal']
            or state['native_dialogs'] or state['widget_count'] or state['map_mode']
            or state['selected_unit'] or state['selected_order'] != -1
            or state['strategy_dialog'] or state['recruit_dialog'] or state['map_widget']
            or not 0 <= state['orders_used'] < 3):
        raise ValueError('请先关闭游戏弹窗／选兵，回到战略阶段')
    return COMMANDS[action]


def extension_remaining(state, enabled, allow_write, added_ms=10000):
    if type(added_ms) is not int or added_ms == 0:
        raise ValueError('加时秒数必须是整数')
    # 任意非零 delta 都是調整量（拉長或縮短）。0 表示已在目標上，不寫入。
    require_test_session(state, enabled)
    if not allow_write:
        raise ValueError('加时尚未启用：需要允许修改本局倒计时')
    # 4447b2/444857 use the same document+0x6c origin in civil and military
    # phases. Only extend our active input, never processing or diplomacy.
    if state['mode'] != 2 or state['phase'] not in (1, 3, 4, 5) or state['allowance'] != 1:
        raise ValueError('加时仅支持我方内政／军事输入阶段')
    if state['modal'] or state['native_dialogs']:
        raise ValueError('请先关闭游戏弹窗，再加时')
    if added_ms == 60000 and state['phase'] == 1 and state['orders_used'] >= 3:
        raise ValueError('内政指令已用完，不再自动加时')
    remaining = timer_value(state)
    if remaining is None:
        raise ValueError('本局输入时间为无限制，无需加时')
    if not 0 < remaining <= 3600000:
        raise ValueError('倒计时已结束或状态异常，不写入')
    return remaining


def extension_plan(state, enabled, allow_write, added_ms=10000):
    """Accept any non-zero delta. The two gates below are only the old
    +60s / +10s buttons, not the round-percent slider."""
    remaining = extension_remaining(state, enabled, allow_write, added_ms)
    if added_ms == 60000 and remaining > 1000:
        raise ValueError('先走原版倒计时，剩最后1秒才自动加时')
    if added_ms == 10000 and remaining < 2000:
        raise ValueError('倒计时已临近结束或状态异常，不写入')
    return dict(address=state['document'] + 0x6c, before=state['start_tick'],
                after=(state['start_tick'] + added_ms) & 0xffffffff, added_ms=added_ms,
                remaining_before_ms=remaining)


def extension_basis(state):
    """Fields which must survive intent logging and the timer write."""
    return (tuple(state[k] for k in ('document', 'view', 'hwnd', 'mode', 'phase',
                 'allowance', 'time_setting', 'unit_count', 'start_tick'))
            + tuple(state.get(k) for k in ('round_clock','player_slot_raw','player_force_raw')))
