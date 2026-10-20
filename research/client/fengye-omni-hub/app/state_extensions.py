"""Additional decoded fields, with static-vs-live evidence made explicit."""
import struct
STATUS={0:'现役',1:'在野',2:'出阵',3:'未登场',4:'俘虏',5:'死亡',6:'负伤中'}
UNIT_TYPES={0x508678:'战略部队',0x508878:'步兵',0x508a60:'强化步兵',0x508c48:'重装步兵',0x508e30:'骑兵',0x509018:'强化骑兵',0x509200:'铁骑兵',0x5093e8:'弓兵',0x5095d0:'强弓兵',0x5097b8:'重装弓兵',0x5099d0:'运输兵',0x50bdb8:'游荡部队'}
def training_progress(raw):
    # Actual status dialog 0x424c56..0x424cd0; invalid values remain unknown.
    return (100 if raw>=300 else raw%100) if isinstance(raw,int) and 0<=raw<=300 else None
def extend_general(row,b):
    status=struct.unpack_from('<H',b,0x21)[0];city=struct.unpack_from('<h',b,0x34)[0]
    from recruitment_probability import INPUT_VERSION
    row.update(relation_byte_2e=b[0x2e],excluded_ruler_word_42=struct.unpack_from('<H',b,0x42)[0],
               recruitment_input_verification=INPUT_VERSION,
               defection_entry_year=struct.unpack_from('<h',b,0x38)[0],
               defection_clan_id=struct.unpack_from('<h',b,0x3e)[0],
               defection_parent_id=struct.unpack_from('<h',b,0x40)[0],
               defection_ambition=b[0x30])
    row.update(skill_mask_raw=struct.unpack_from('<I',b,0x2a)[0],
               combat_modifier_flags_word=struct.unpack_from('<H',b,0x44)[0])
    row.update(status_code=status,status_label=STATUS.get(status,'未命名状态'),location_city_id=city if city>=0 else None,
        status_verification='static_enum_table_and_behavior; GUI_not_crosschecked',
        location_verification='static_city_lookup_0x44fff4; not_screen_coordinates')
def extend_force(row,b=None):
    if b is not None:
        row.update(defection_protected_general_id=struct.unpack_from('<h',b,0x80)[0],
                   defection_exiled_flag=b[0x83],
                   diplomacy_pending={'target':struct.unpack_from('<h',b,0x63)[0],
                       'envoy':struct.unpack_from('<h',b,0x65)[0],'card_id':b[0x67],'parameter':b[0x6c]})
    row['training_progress']={k:training_progress(v) for k,v in row['armament_raw'].items()}
    row['training_verification']='status_dialog_formula_0x424c56; core_effective_phase_unverified'
def decode_unit(address,b,vt):
    ids=list(struct.unpack_from('<3H',b,0xf))
    return {'address':hex(address),'type':'field_unit','unit_kind':UNIT_TYPES[vt],'unit_id':struct.unpack_from('<H',b,0xa)[0],
      'owner_raw':struct.unpack_from('<H',b,8)[0],'world_xy_raw':list(struct.unpack_from('<hh',b,4)),
      'general_ids':[None if x==65535 else x for x in ids],
      'soldiers_candidate':struct.unpack_from('<I',b,0x15)[0],'rice_candidate':struct.unpack_from('<I',b,0x19)[0],
      'unit_state_flags_raw':b[0xd],'native_order_type_raw':struct.unpack_from('<H',b,0x7e)[0],
      'native_order_payload_raw':struct.unpack_from('<I',b,0x5e)[0],
      'move_remaining_raw':b[0x20],'movement_verification':'unit+0x20; current remaining points',
      'armament_degree_raw':b[0x29],'raw_1d':b[0x1d],'raw_1e':b[0x1e],'training_degree':None,'basic_combat_power':None,
      'verification':'static_layout_only_pending_live_unit_sample','source_layer':'game_core','raw_hex':b.hex()}

def enrich(state):
    cities={c['city_id']:c for c in state['entities']['cities_and_barriers']}
    for g in state['entities']['generals']:
        city=cities.get(g.get('location_city_id'))
        g['location_city_name']=city['name'] if city else None
        g['location_city_owner']=city['owner_raw'] if city else None
    state['extension_schema']='intel-2'
    state['current_local_projection']['training_progress']={k:training_progress(v) for k,v in state['current_local_projection']['armament_raw'].items()}
    state['unit_observation']={'container':'GameCore+0x534','count':len(state['entities'].get('field_units',[])),
      'verification':'static_unit_lookup_0x44ffc9_and_strategy_unit_callers; live_spawn_not_tested',
      'empty_meaning':'zero records in this container now; not proof that all possible unit sources are covered'}
    return state
