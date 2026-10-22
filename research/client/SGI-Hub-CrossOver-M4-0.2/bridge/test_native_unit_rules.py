"""Sealed raw-read regression evidence, not simulated target damage."""
import copy,json,struct,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'bridge')]
from native_unit_rules import (ATTACK_MODEL,TERRAIN_ENCODING,UNKNOWN_TERRAIN,attack_index,attack_pair_text,
    general_skill_mask,remaining_move,terrain_entry_cost,unit_skill_mask)
from unit_combat import enrich_unit_combat
from unit_target_attack import enrich_targets,BUILD

def fixture():return json.loads((ROOT/'bridge/native-map-321-fixture.json').read_text(encoding='utf8'))

class NativeUnitRulesTests(unittest.TestCase):
    def test_compact_same_frame_word_restores_exact_modifier_byte(self):
        from game_archive import compact_state
        from state_extensions import extend_general
        s=fixture()['state'];enrich_unit_combat(s)
        expected={u['unit_id']:attack_pair_text(u) for u in s['entities']['field_units']}
        for g in s['entities']['generals']:
            # The raw BYTE and WORD overlap at the exact same address.
            g['combat_modifier_flags_word']=int.from_bytes(bytes.fromhex(g['raw_hex'])[0x44:0x46],'little')
            extend_general(g,bytes.fromhex(g['raw_hex']))
        saved=compact_state(s)
        for g in saved['entities']['generals']:g.pop('combat_modifier_flags',None)
        before=copy.deepcopy(saved['entities']['generals'])
        enrich_unit_combat(saved);enrich_unit_combat(saved)
        self.assertEqual({u['unit_id']:attack_pair_text(u) for u in saved['entities']['field_units']},expected)
        self.assertEqual(saved['entities']['generals'],before)
        # Treasure lead/war bits survive WORD-only input; unknown never means0.
        single=saved['entities']['field_units'][0];single['general_ids']=[s['entities']['generals'][0]['general_id_raw']]
        g=saved['entities']['generals'][0];g['owner_raw']=single['owner_raw'];g['status_code']=2
        g['attributes'].update(lead=100,war=100);g['combat_modifier_flags_word']=0x130
        enrich_unit_combat(saved);self.assertEqual(single['basic_combat_power'],140)
        del g['combat_modifier_flags_word'];enrich_unit_combat(saved)
        self.assertIsNone(single['basic_combat_power'])

    def test_real_320_replay_preserves_reference_without_inventing_skill_bits(self):
        from unit_memory import attack_label, memory_line
        from map_unit_labels import unit_label
        f=json.loads((ROOT/'bridge/replay-legacy-attack-324-fixture.json').read_text(encoding='utf8'))
        s=f['state'];original=copy.deepcopy(s)
        for _ in range(2):
            enrich_unit_combat(s)
            for u in s['entities']['field_units']:
                with self.subTest(unit=u['unit_id']):
                    text='—' if u['unit_kind']=='强弓兵' else f['expected'][str(u['unit_id'])]
                    self.assertEqual(attack_label(u),text)
                    if u['unit_kind']=='强弓兵':
                        self.assertNotIn('(攻:',unit_label(s,u))
                        self.assertNotIn('攻击',memory_line(u))
                    else:
                        self.assertIn(f'(攻:{text})',unit_label(s,u))
                        self.assertIn(text,memory_line(u))
                    self.assertIsNone(u['effective_skill_mask'])
                    if u['unit_kind']=='强弓兵':
                        self.assertEqual(attack_pair_text(u),'[未知/未知]')
                        self.assertIsNone(u['native_attack_index'])
                        self.assertNotIn('当前/满士气',memory_line(u))
        self.assertEqual(s['entities']['generals'],original['entities']['generals'])
        bow=next(u for u in s['entities']['field_units'] if u['unit_kind']=='强弓兵')
        bow['on_water']=True;enrich_targets(s)
        self.assertEqual(attack_label(bow),'—')
        bow['on_water']=False;s['build_sha256']='unknown';enrich_targets(s)
        self.assertEqual(attack_label(bow),'—')

    def test_new_archive_keeps_native_skill_fields_and_recomputes_pair(self):
        import tempfile
        from game_archive import compact_state,write_packed_archive,ArchiveReader
        from state_extensions import extend_general
        s=fixture()['state'];enrich_unit_combat(s)
        expected={u['unit_id']:attack_pair_text(u) for u in s['entities']['field_units']}
        for g in s['entities']['generals']:
            extend_general(g,bytes.fromhex(g['raw_hex']))
        saved=compact_state(s)
        for g in saved['entities']['generals']:
            self.assertNotIn('raw_hex',g)
            self.assertIsInstance(g['skill_mask_raw'],int)
            self.assertIsInstance(g['combat_modifier_flags_word'],int)
        with tempfile.TemporaryDirectory() as tmp:
            path=write_packed_archive(Path(tmp)/'archive',[saved])
            with ArchiveReader(path,read_only=True) as reader:
                loaded=reader.load_frame(1);enrich_unit_combat(loaded)
                self.assertEqual({u['unit_id']:attack_pair_text(u)
                    for u in loaded['entities']['field_units']},expected)

    def test_sealed_three_actual_units(self):
        f=fixture();s=f['state'];enrich_unit_combat(s)
        units={u['unit_id']:u for u in s['entities']['field_units']}
        for expected in f['expected_units']:
            with self.subTest(unit=expected['unit_id']):
                u=units[expected['unit_id']]
                self.assertEqual(u['basic_combat_power'],expected['basic_combat_power'])
                self.assertEqual(u['effective_skill_mask'],int(expected['native_skill_union'],16))
                self.assertEqual(u['target_attack_components']['unit'],[expected['client_land_factor_after_skill']])
                self.assertEqual(u['native_attack_index'],expected['engine_consumer_pre_random_component'])
                self.assertEqual(u['native_attack_index_full_morale'],{27:1024,28:498,32:246}[u['unit_id']])
                self.assertEqual(u['target_attack_unit'],str(expected['engine_consumer_pre_random_component']))
                self.assertEqual(u['attack_model'],ATTACK_MODEL)
                self.assertIn('不是实际扣血',u['target_attack_note'])
                self.assertEqual(remaining_move(s,u),expected['remaining_move_raw'])

    def test_morale_rounding_and_missing_inputs(self):
        self.assertEqual(attack_index(300,89,85),867)
        self.assertEqual(attack_index(164,77,75),372)
        self.assertEqual(attack_index(83,74,75),184)
        self.assertEqual(attack_index(190,100,100),713)
        self.assertEqual(attack_index(300,89,0),0)
        for args in ((300,None,85),(True,89,85),(300,89,-1),(300,89,101)):
            self.assertIsNone(attack_index(*args))

    def test_raw_skills_override_reference_and_union_treasure(self):
        b=bytearray(96);struct.pack_into('<I',b,0x2a,1);struct.pack_into('<H',b,0x44,0x200)
        g={'general_id_raw':1,'owner_raw':3,'status_code':2,'raw_hex':b.hex(),'skill_mask_raw':0,'combat_modifier_flags_word':0}
        s={'build_sha256':BUILD,'entities':{'generals':[g]}}
        u={'owner_raw':3,'general_ids':[1]}
        self.assertEqual(general_skill_mask(g),5);self.assertEqual(unit_skill_mask(s,u),5)
        other=dict(g,general_id_raw=2,raw_hex='',skill_mask_raw=2,combat_modifier_flags_word=0)
        s['entities']['generals'].append(other);u['general_ids']=[1,2]
        self.assertEqual(unit_skill_mask(s,u),7)
        for ids in ([1,1],[1,9],[[1]],[]):
            self.assertIsNone(unit_skill_mask(s,dict(u,general_ids=ids)))
        other['owner_raw']=9;self.assertIsNone(unit_skill_mask(s,u))
        s['build_sha256']='unknown';self.assertIsNone(unit_skill_mask(s,u))

    def test_missing_skills_are_range_not_absent_and_water_not_land(self):
        f=fixture();s=f['state'];enrich_unit_combat(s)
        u=next(u for u in s['entities']['field_units'] if u['unit_id']==32)
        s['entities']['generals']=[]
        enrich_targets(s);self.assertEqual(u['target_attack_unit'],'184–369')
        self.assertIsNone(u['native_attack_index'])
        u['on_water']=True;enrich_targets(s)
        self.assertEqual(u['target_attack_unit'],'184–369');self.assertEqual(u['attack_model'],ATTACK_MODEL)
        self.assertEqual(u['target_attack_components']['terrain_branch'],'water')
        u['on_water']=False;u['morale']=None;enrich_targets(s)
        self.assertEqual(u['target_attack_unit'],'缺参数')

    def test_map_pair_uses_sealed_indices_and_never_guesses_missing_skills(self):
        from map_unit_labels import unit_label
        from unit_memory import attack_reference
        s=fixture()['state'];enrich_unit_combat(s)
        expected={27:180,28:91,32:82}
        for u in s['entities']['field_units']:
            self.assertEqual(attack_reference(u),expected[u['unit_id']])
            pair={27:'[867/1024]',28:'[372/498]',32:'[184/246]'}[u['unit_id']]
            if u['unit_id']==32:self.assertNotIn('(攻:',unit_label(s,u))
            else:self.assertIn(f'(攻:{pair})',unit_label(s,u))
        s['entities']['generals']=[];enrich_targets(s)
        for u in s['entities']['field_units']:
            with self.subTest(unit=u['unit_id']):
                self.assertEqual(attack_reference(u),expected[u['unit_id']])
                text=unit_label(s,u)
                display=('[867/1024]' if u['unit_id']==27 else
                         f"旧参考{expected[u['unit_id']]}·技能未存")
                if u['unit_id']==32:self.assertNotIn('(攻:',text)
                else:self.assertIn(f'(攻:{display})',text)
                self.assertEqual(attack_pair_text(u),
                                 '[867/1024]' if u['unit_id']==27 else '[未知/未知]')
                self.assertNotIn('–',text)
        bow=next(u for u in s['entities']['field_units'] if u['unit_id']==32)
        self.assertEqual(bow['target_attack_unit'],'184–369')
        bow.pop('legacy_attack_reference')
        self.assertNotIn('(攻:',unit_label(s,bow))
        bow['on_water']=True;enrich_targets(s)
        self.assertEqual(attack_reference(bow),82)
        self.assertEqual(bow['target_attack_unit'],'184–369')
        self.assertEqual(attack_pair_text(bow),'[未知/未知]')

    def test_verified_morale_skill_examples_and_independent_full_morale(self):
        for kind,mask,pair in [('重装步兵',0,'[447/599]'),
                              ('强化骑兵',0,'[193/258]'),('强化骑兵',1,'[388/520]'),
                              ('强弓兵',0,'[226/302]'),('强弓兵',2,'[452/605]')]:
            with self.subTest(kind=kind,mask=mask):
                u={'unit_kind':kind,'size_index':0,'training_degree':60,
                   'basic_combat_power':80,'morale':75,'on_water':False,
                   'owner_raw':3,'general_ids':[1]}
                s={'build_sha256':BUILD,'entities':{'field_units':[u],'generals':[
                    {'general_id_raw':1,'owner_raw':3,'status_code':2,
                     'skill_mask_raw':mask,'combat_modifier_flags_word':0}]}}
                enrich_targets(s)
                self.assertEqual(attack_pair_text(u),pair)
                full=u['native_attack_index_full_morale']
                u['morale']=100;enrich_targets(s)
                self.assertEqual(attack_pair_text(u),f'[{full}/{full}]')
                u['morale']=0;enrich_targets(s)
                self.assertEqual(attack_pair_text(u),f'[0/{full}]')
                u['morale']=None;enrich_targets(s)
                self.assertEqual(attack_pair_text(u),f'[未知/{full}]')
                s['build_sha256']='unknown';enrich_targets(s)
                self.assertEqual(attack_pair_text(u),'[未知/未知]')

    def test_water_melee_and_land_full_are_independent(self):
        # Original x86: water B=50; land B=165 with horse,82 without.
        # A80 gives C84; M75 gives S112. Fixed expected values from native audit.
        u={'unit_kind':'强化骑兵','size_index':0,'training_degree':60,
           'basic_combat_power':80,'morale':75,'terrain_type_raw':4,
           'owner_raw':3,'general_ids':[1]}
        g={'general_id_raw':1,'owner_raw':3,'status_code':2,
           'skill_mask_raw':1,'combat_modifier_flags_word':0}
        s={'build_sha256':BUILD,'entities':{'field_units':[u],'generals':[g]}}
        for code in (4,6):
            u['terrain_type_raw']=code
            for mask,right in ((0,258),(1,520),(4,258),(5,520)):
                g['skill_mask_raw']=mask;enrich_targets(s)
                self.assertEqual(attack_pair_text(u),f'[118/{right}]')
                self.assertEqual(u['target_attack_components']['current_unit'],[50])
                self.assertIn('陆地',u['target_attack_note'])
        s['entities']['generals']=[];enrich_targets(s)
        self.assertEqual(attack_pair_text(u),'[118/未知]')
        s['entities']['generals']=[g];u.pop('terrain_type_raw');enrich_targets(s)
        self.assertEqual(attack_pair_text(u),'[未知/520]')
        u['on_water']=False;enrich_targets(s)
        self.assertEqual(attack_pair_text(u),'[388/520]')
        u['on_water']=True;u['training_degree']=None;enrich_targets(s)
        self.assertEqual(attack_pair_text(u),'[118/未知]')
        u['training_degree']=60;u['morale']=None;enrich_targets(s)
        self.assertEqual(attack_pair_text(u),'[未知/520]')

    def test_remaining_zero_and_raw_precedence(self):
        b=bytearray(168);b[0x20]=0
        s={'build_sha256':BUILD}
        u={'raw_hex':b.hex(),'move_remaining_raw':18}
        self.assertEqual(remaining_move(s,u),0)
        self.assertEqual(remaining_move(s,{'move_remaining_raw':3}),3)
        self.assertIsNone(remaining_move(s,{}));self.assertIsNone(remaining_move({},u))

    def test_complete_entry_cost_classes(self):
        expected={0:3,1:5,2:5,3:6,4:8,5:3,6:8,18:4,19:4}
        for code in range(30):
            self.assertEqual(terrain_entry_cost(code,'重装步兵',0,1),expected.get(code,2 if code<24 else None))
        self.assertEqual(terrain_entry_cost(4,'重装步兵',4,1),2)
        for code in (4,6):self.assertIsNone(terrain_entry_cost(code,'重装步兵',None,1))
        for setting in (0,None):self.assertIsNone(terrain_entry_cost(3,'重装步兵',0,setting))
        self.assertIsNone(terrain_entry_cost(3,'骑兵',1,1))
        for code in (None,255,-1,True):self.assertIsNone(terrain_entry_cost(code,'重装步兵',0,1))

    def test_collector_preserves_codes_and_distinguishes_failed_cell(self):
        import collector
        c=collector.Collector.__new__(collector.Collector);c.core=0x10000;c._terrain_grid=None
        header=bytearray(28);struct.pack_into('<I',header,4,0x20000);struct.pack_into('<II',header,20,2,2)
        pointers=struct.pack('<4I',0x30000,0x40000,0x50000,0)
        def read(a,n):
            if a==c.core+0x5fc:return bytes(header)
            if a==0x20000:return pointers
            return {0x3000a:b'\x0f',0x4000a:b'\x12',0x5000a:b'\x1c'}[a]
        c.read=read
        with patch.object(collector,'_known_grid',return_value={'id':'fixture'}):grid=c.terrain_grid()
        self.assertEqual(bytes.fromhex(grid['types']),bytes([15,18,28,255]))
        self.assertEqual(grid['encoding'],TERRAIN_ENCODING);self.assertEqual(grid['unknown_code'],255)

    def test_history_retains_both_indices_and_map_details_use_same_pair(self):
        from state_history import slim,military_chip_text
        from map_unit_labels import unit_label
        from unit_memory import memory_line
        s=fixture()['state'];enrich_unit_combat(s);u=s['entities']['field_units'][0]
        out=slim(s);saved=out['entities']['field_units'][0]
        for key in ('attack_model','native_attack_index','native_attack_index_full_morale',
                    'target_attack_full_morale','morale','move_remaining_raw','effective_skill_mask'):
            self.assertEqual(saved[key],u[key])
        self.assertEqual(out['movement_rules'],s['movement_rules'])
        self.assertEqual(out['build_sha256'],s['build_sha256'])
        self.assertIn('魏王(攻:[867/1024])',unit_label(s,u))
        self.assertIn('攻击[当前/陆地满士气] [867/1024]',memory_line(u))
        self.assertIn('满士气攻击1024',military_chip_text({'field':'出征','line':'出征 重装步兵','unit_snapshot':u}))

if __name__=='__main__':unittest.main()
