"""Client 3.5 land/water attack index, with raw effective skills and observed morale.

The index is a verified engine intermediate, not final target damage.
Website scaling remains separate for the explicitly labelled planning references.
"""
import math
from website_combat import factor as website_factor
from native_unit_rules import (ARROW, HORSE, ATTACK_MODEL, attack_index,
                               proficiency_values, unit_skill_mask, primary_skill_text)
BUILD='c06ec3aa9c2b539e4111b53c57bed3717a2c0c73f3145aac4d55f66b2abb26cc'
LIFETIME_HOTFIX_BUILD='bce227ebd18ad9d9b1e95bb25027679684354a8822debd2974cb52947de28081'
DIAGNOSTIC_HOTFIX_BUILD='9c40791df3d38ee87dd242de2f2a7cc5458bd88561fda7c6120a7abd4ac07aa5'
FINALIZE_HOTFIX_BUILD='2d9a5635eba3ea515aac43af3a00f136eba0ece19e86272a033bdbb545078743'
NETWORK_HOTFIX_BUILD='1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2'
DESTRUCTOR_HOTFIX_BUILD='df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea'
def supported_combat_build(sha):
 # r2 changes lifetime guards only; combat coefficients/data remain identical.
 return sha in (BUILD,LIFETIME_HOTFIX_BUILD,DIAGNOSTIC_HOTFIX_BUILD,FINALIZE_HOTFIX_BUILD,NETWORK_HOTFIX_BUILD,DESTRUCTOR_HOTFIX_BUILD)
# (unit bases, building bases, unit training coefficients, building coefficients)
PARAMS={
 '步兵':([50,150,250],[50,150,250],[100]*3,[100]*3),
 '强化步兵':([150,250,350],[150,250,350],[20]*3,[20]*3),
 '重装步兵':([190,300,400],[190,300,400],[0]*3,[0]*3),
 '骑兵':([100,250,450],[50,130,230],[25]*3,[10]*3),
 '强化骑兵':([150,300,500],[80,160,260],[25]*3,[10]*3),
 '重装骑兵':([200,350,550],[110,190,290],[25]*3,[10]*3),
 '弓兵':([80,140,200],[40,80,120],[20]*3,[20]*3),
 '强弓兵':([120,180,240],[80,120,160],[120,140,160],[80,100,120]),
 '重装弓兵':([240,320,400],[160,220,280],[120,140,160],[80,100,120])}
WATER_BASES = (50, 150, 250)  # 0x477dfb; melee branch, not bow shooting
BOW={'弓兵','强弓兵','重装弓兵','弩兵','连弩'}
ALIASES={'弩兵':'强弓兵','连弩':'重装弓兵','铁骑兵':'重装骑兵','生骑兵':'骑兵','生步兵':'步兵'}
def rnd(n):return math.floor(n+.5)
def client_kind(kind):
 return ALIASES.get(kind,kind)
def client_factor(kind,size,training):
 name=client_kind(kind)
 if name not in PARAMS or size not in (0,1,2) or type(training) is not int or not 0<=training<=100:
  return None
 ub,_,uc,_=PARAMS[name]
 return ub[size]+rnd(uc[size]*training/100)
def unit_factor(kind,size,training):
 if kind in BOW:
  return client_factor(kind,size,training)
 return website_factor(kind,size,training)
def span(values):
 if not values:return '缺参数'
 lo,hi=min(values),max(values)
 return str(lo) if lo==hi else f'{lo}–{hi}'

LEGACY_SOURCES = {'unit=SANPK 3.5 table; building=SANPK 3.5 static',
                  'unit=website calculator; building=SANPK 3.5 static'}

def preserve_legacy_reference(unit):
    """Keep this frame's old comparison value before replacing derived fields.

    The old collector used reference officer skills, not raw skill bits. Its
    scalar must remain explicitly separate from the native morale pair.
    """
    source = (unit.get('target_attack_components') or {}).get('source')
    value = unit.get('target_attack_unit')
    if (unit.get('attack_model') is None and source in LEGACY_SOURCES
            and isinstance(value, str) and value.isascii() and value.isdecimal()):
        unit['legacy_attack_reference'] = {'value': int(value), 'source': source}

def enrich_targets(state):
    for u in state.get('entities', {}).get('field_units', []):
        preserve_legacy_reference(u)
        u.update(target_attack_unit='缺参数', target_attack_building='缺参数',
                 target_attack_melee='—', target_attack_note='', unit_skills_reference='',
                 skill_points_display='', target_attack_components={}, attack_model=None,
                 native_attack_index=None, native_attack_index_full_morale=None,
                 target_attack_full_morale='缺参数', effective_skill_mask=None,
                 attack_missing_reason=None)
        if not supported_combat_build(state.get('build_sha256')):
            u['target_attack_note'] = '客户端版本未匹配，攻击指数未核实'
            continue
        kind = u.get('unit_kind'); size = u.get('size_index')
        training = u.get('training_degree'); ability = u.get('basic_combat_power')
        name = client_kind(kind)
        mask = unit_skill_mask(state, u)
        u['effective_skill_mask'] = mask
        u['unit_skills_reference'] = primary_skill_text(mask, full=True)
        training_known = type(training) is int and 0 <= training <= 100
        if name not in PARAMS or type(size) is not int or size not in (0, 1, 2):
            u['target_attack_note'] = '兵种或规模字段不足'
            continue
        required = ARROW if name in BOW else (HORSE if '骑兵' in name else None)
        _, building_bases, _, building_coeffs = PARAMS[name]
        units = (proficiency_values(client_factor(kind, size, training), required, mask)
                 if training_known else [])
        building_base = (building_bases[size] + rnd(building_coeffs[size] * training / 100)
                         if training_known else None)
        buildings = proficiency_values(building_base, required, mask) if training_known else []
        # Preserve the explicitly separate website/planning scale. It is never
        # substituted for the native index or treated as native damage.
        # Retain this separate scale for planning/legacy consumers only.
        reference = unit_factor(kind, size, training) if training_known else None
        u['target_attack_components'] = {
            'unit': units, 'building': buildings, 'reference_unit': [reference],
            'training': training, 'size': size, 'effective_skill_mask': mask,
            'attack_mode': 'shooting' if name in BOW else 'melee',
            'source': 'SANPK 3.5 native land/water coefficient + raw effective skills',
        }
        if type(ability) is int and 0 <= ability <= 150:
            u['target_attack_building'] = span([rnd(v * ability / 150) for v in buildings])
        water = u.get('on_water')
        if type(water) is not bool:
            code = u.get('terrain_type_raw')
            water = code in (4, 6) if type(code) is int and 0 <= code <= 29 else None
        full_values = [attack_index(v, ability, 100) for v in units]
        if full_values and all(v is not None for v in full_values):
            u['target_attack_full_morale'] = span(full_values)
            u['native_attack_index_full_morale'] = (full_values[0]
                if len(set(full_values)) == 1 else None)
            u['attack_model'] = ATTACK_MODEL
            if required and mask is None:
                u['attack_missing_reason'] = '技能未存'
        if water is None:
            u['target_attack_note'] = '水陆状态未采集；右值仅为陆地满士气'
            continue
        # Original 0x477dfb: infantry/cavalry water melee is size-only.
        # Bow shooting (mode0) retains its own coefficient even on water.
        current_units = [WATER_BASES[size]] if water and name not in BOW else units
        u['target_attack_components'].update(current_unit=current_units,
            terrain_branch='water' if water else 'land', full_morale_terrain='land')
        morale = u.get('morale')
        values = [attack_index(v, ability, morale) for v in current_units]
        if not values or any(v is None for v in values):
            u['target_attack_note'] = '编成能力、士气或训练字段不足，当前攻击力未知'
            continue
        u['target_attack_unit'] = span(values)
        u['native_attack_index'] = values[0] if len(set(values)) == 1 else None
        u['attack_model'] = ATTACK_MODEL
        u['attack_verification'] = '0x456269 intermediate; raw skills; not final damage'
        uncertainty = '；有效技能未采集，显示无／有技能范围' if required and mask is None else ''
        u['target_attack_note'] = (
            '攻击[当前/陆地满士气]：左值按当前水陆与士气，右值固定陆地、士气100；'
            '弓兵为远射，未含目标及完整修正与最终结算，不是实际扣血。'
            '攻城列仍为基础参考，未核实完整攻城修正' + uncertainty
        )
    return state
