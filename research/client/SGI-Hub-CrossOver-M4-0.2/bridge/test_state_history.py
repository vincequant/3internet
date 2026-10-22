import json
import tempfile
import unittest
from pathlib import Path

from state_history import (
    CAPTURE_BUILDING_GRACE_FRAMES, History, attach_history, calendar_label, census_rows,
    annotate_hire_kinds, differences, implied_recruit_raw, is_civil_op, is_military_op, kind_label,
    kind_line, military_chip_text, military_note, phase_label, recent_capture_ids, recent_quarter_ops,
    record_city_captures, relabel_field_units, merge_prestige_commands, refresh_account, season_round,
    hire_quarter_lanes, prestige_command_ops, short_quarter_label, slim, split_quarter_lanes,
    synthesize_force, unit_display,
)


def lord(fid, name, stock, raw, gold=10000, **extra):
    row = {
        'force_id': fid, 'name': name, 'gold': gold, 'rice': 20000, 'prestige': 50,
        'troop_stock': dict(zip(('infantry', 'cavalry', 'bow'), stock)),
        'armament_raw': dict(zip(('infantry', 'cavalry', 'bow'), raw)),
    }
    row.update(extra)
    return row


def building(kind, owner, amount, xy, city=1, oid=1):
    return {
        'type': kind, 'owner_raw': owner, 'building_ui_amount': amount,
        'world_xy_raw': xy, 'linked_city_id': city, 'object_id_candidate': oid,
    }


def snapshot(lords, buildings=None, year=200, season=1, filetime=1, extra=None,
             units=None, generals=None, cities=None):
    state = {
        'snapshot_id': f'{year}{season}',
        'capture_end': f'2026-09-14T0{season}:00:00+00:00',
        'identity': {'pid': 1, 'path': 'game', 'creation_filetime': filetime},
        'core_address': '0xabc',
        'clock_candidates': {'year_u16': year, 'season_u16': season},
        'entities': {
            'lords': lords,
            'cities_and_barriers': cities or [{
                'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                'population': 80000, 'world_xy_raw': [50, 100],
            }],
            'production_buildings': buildings or [],
            'field_units': units or [],
            'generals': generals or [],
        },
        'current_local_projection': {},
    }
    if extra:
        state.update(extra)
    return state


class HistoryTests(unittest.TestCase):
    def test_sortie_appearance_freezes_attack_and_training_in_slim_history(self):
        from state_history import unit_command_ops
        before=slim(snapshot([lord(0,'魏',(10000,0,0),(80,0,0))]))
        unit=dict(unit_id=3,owner_raw=0,unit_kind='步兵',general_ids=[3],world_xy_raw=[50,100],
                  soldiers_candidate=5000,target_attack_unit='54',website_attack_power=54,training_degree=50)
        after=slim(snapshot([lord(0,'魏',(5000,0,0),(80,0,0))],units=[unit]))
        item=unit_command_ops(before,after,0)[0]
        after['entities']['field_units'][0]['training_degree']=99
        self.assertEqual(item['unit_snapshot']['training_degree'],50)
        self.assertIn('攻击54',military_chip_text(item));self.assertIn('训练50/100',military_chip_text(item))

    def test_implied_summer_recruit_near_180(self):
        self.assertAlmostEqual(implied_recruit_raw(10000, 300, 15000, 260), 180)
        self.assertIsNone(implied_recruit_raw(15000, 260, 15000, 260))

    def test_dilution_note_and_training_note(self):
        text = military_note(10000, 300, 15000, 260)
        self.assertIn('新兵摊薄', text)
        self.assertIn('180', text)
        self.assertIn('训练上升', military_note(10000, 80, 10000, 120))

    def test_census_includes_enemy_and_baseline_numbers(self):
        wei = lord(0, '魏', (12000, 8000, 5000), (121, 40, 10))
        wu = lord(1, '吴', (9000, 2000, 4000), (90, 20, 5))
        state = slim(snapshot([wei, wu], [building('parade_ground', 0, 8000, [1, 2])]))
        rows = census_rows(state, state)
        owners = {row['owner'] for row in rows}
        self.assertEqual(owners, {0, 1})
        step = next(row for row in rows if row['owner'] == 0 and row['field'] == '步库存')
        self.assertEqual(step['after'], '12,000')
        self.assertTrue(step['flat'])
        barracks = next(row for row in rows if row['owner'] == 0 and row['field'] == '练兵所')
        self.assertIn('1座', barracks['after'])
        empty = next(row for row in rows if row['owner'] == 1 and row['field'] == '练兵所')
        self.assertEqual(empty['after'], '—')

    def test_new_barracks_and_training_are_captured(self):
        before = slim(snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))]))
        after = slim(snapshot([
            lord(0, '魏', (10000, 0, 0), (120, 0, 0), gold=8000)
        ], [building('parade_ground', 0, 5000, [3, 4], oid=9)]))
        fields = {row['field'] for row in differences(before, after)}
        self.assertIn('步训练', fields)
        self.assertIn('记录有无', fields)
        self.assertIn('金钱', fields)
        training = next(row for row in differences(before, after) if row['field'] == '步训练')
        self.assertIn('练兵', training['interpretation'])
        self.assertIn('金钱减少', training['interpretation'])
        born = next(row for row in differences(before, after) if row['entity'] == 'production_buildings')
        self.assertIn('练兵所', born['interpretation'])

    def test_first_observe_writes_session_and_census(self):
        root = tempfile.mkdtemp()
        store = History(root)
        wei = lord(0, '魏', (12000, 8000, 5000), (121, 40, 10))
        wu = lord(11, '宋', (3000, 1000, 1000), (50, 10, 10))
        out = store.observe(snapshot([wei, wu]), session='abc')
        self.assertEqual(out['player_session_id'], 'abc')
        self.assertNotIn('宋·操作层', json.dumps(out, ensure_ascii=False))
        self.assertGreaterEqual(len(out['census_rows']), 18)
        self.assertTrue(any(row['owner'] == 11 and row['field'] == '步库存' for row in out['census_rows']))
        self.assertIn('正在记2个势力', out['banner'])
        self.assertEqual(out['quarter_rows'], [])
        self.assertEqual(out['current_quarter']['closed'], False)

    def test_quarter_boundary_keeps_last_ledger(self):
        root = tempfile.mkdtemp()
        store = History(root)
        start = snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))], year=200, season=1)
        store.observe(start, session='s')
        nxt = snapshot([lord(0, '魏', (15000, 0, 0), (120, 0, 0))], year=200, season=2)
        nxt['capture_end'] = '2026-09-14T02:00:00+00:00'
        out = store.observe(nxt, session='s')
        self.assertEqual(len(out['quarters']), 1)
        self.assertTrue(out['last_quarter']['closed'])
        train = next(row for row in out['last_quarter']['rows'] if row['field'] == '训练步兵')
        self.assertTrue(train['line'].startswith('训练步兵'))
        self.assertFalse(any(row['field'].startswith('募') for row in out['quarter_rows']))
        current = next(row for row in out['census_rows'] if row['field'] == '步库存')
        self.assertTrue(current['flat'])
        self.assertEqual(current['after'], '15,000')

    def test_resume_same_instance(self):
        root = tempfile.mkdtemp()
        first = History(root)
        state = snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))])
        first.observe(state, session='a')
        later = snapshot([lord(0, '魏', (11000, 0, 0), (70, 0, 0))])
        later['capture_end'] = '2026-09-14T01:10:00+00:00'
        second = History(root)
        out = second.observe(later, session='b')
        self.assertEqual(out['player_session_id'], 'b')
        stock = next(row for row in out['census_rows'] if row['field'] == '步库存')
        self.assertEqual(stock['before'], '10,000')
        self.assertEqual(stock['after'], '11,000')

    def test_new_process_does_not_reuse_old_baseline(self):
        root = tempfile.mkdtemp()
        store = History(root)
        store.observe(snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))], filetime=1), session='a')
        out = store.observe(snapshot([lord(0, '魏', (20000, 0, 0), (10, 0, 0))], filetime=2), session='a')
        stock = next(row for row in out['census_rows'] if row['field'] == '步库存')
        self.assertEqual(stock['before'], '20,000')
        self.assertTrue(stock['flat'])

    def test_attach_history_keeps_player_session(self):
        root = tempfile.mkdtemp()
        payload = {
            'fresh': True,
            'player_force_id': 0,
            'player_identity': {'session_id': 'sess-1'},
            'state': snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))]),
        }
        out = attach_history(payload, History(root))
        self.assertEqual(out['state']['history']['player_session_id'], 'sess-1')
        self.assertTrue(out['state']['history']['census_rows'])

    def test_keeps_every_closed_quarter(self):
        root = tempfile.mkdtemp()
        store = History(root)
        store.observe(snapshot([lord(0, '魏', (10000, 0, 0), (300, 0, 0))], year=200, season=1), session='s')
        store.observe(snapshot([lord(0, '魏', (15000, 0, 0), (260, 0, 0))], year=200, season=2), session='s')
        third = snapshot([lord(0, '魏', (15000, 0, 0), (280, 0, 0), gold=8000)], year=200, season=3)
        third['capture_end'] = '2026-09-14T03:00:00+00:00'
        out = store.observe(third, session='s')
        self.assertEqual(len(out['quarters']), 2)
        ops = [row['field'] for row in out['quarter_rows'] if row['owner'] == 0 and row.get('metric') == 'operation']
        self.assertNotIn('募步兵', ops)
        self.assertIn('训练步兵', ops)
        self.assertEqual(ops, ['训练步兵'])

    def test_synthesize_barracks_and_training(self):
        before = slim(snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))]))
        after = slim(snapshot([lord(0, '魏', (10000, 0, 0), (120, 0, 0), gold=8000)],
                              [building('parade_ground', 0, 5000, [3, 4], oid=9)]))
        acc = synthesize_force(before, after, 0)
        kinds = {item['field'] for item in acc['operations']}
        self.assertIn('训练步兵', kinds)
        self.assertIn('新建练兵所', kinds)
        self.assertTrue(any(item['line'] == '新建 1 座练兵所：许昌' for item in acc['operations']))
        self.assertTrue(any(item['line'].startswith('训练步兵') for item in acc['operations']))
        self.assertIn('许昌', acc['after_text'])
        self.assertNotIn('步10,000', acc['after_text'])
        self.assertFalse(acc['flat'])

    def test_captured_city_buildings_are_not_construction(self):
        before = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 9,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
            buildings=[building('parade_ground', 9, 5000, [61, 111], city=2, oid=20)],
        ))
        after = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 0,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
            buildings=[building('parade_ground', 0, 5000, [61, 111], city=2, oid=20)],
        ))
        acc = synthesize_force(before, after, 0)
        fields = [item['field'] for item in acc['operations']]
        self.assertIn('得城', fields)
        self.assertNotIn('新建练兵所', fields)

    def test_delayed_captured_city_buildings_are_not_construction(self):
        held = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 0,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
        ))
        later = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 0,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
            buildings=[building('parade_ground', 0, 5000, [61, 111], city=2, oid=20)],
        ))
        leaked = synthesize_force(held, later, 0)
        self.assertIn('新建练兵所', [item['field'] for item in leaked['operations']])
        filtered = synthesize_force(held, later, 0, ignore_city_ids={2})
        self.assertNotIn('新建练兵所', [item['field'] for item in filtered['operations']])
        own_city = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 0,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
            buildings=[
                building('parade_ground', 0, 5000, [61, 111], city=2, oid=20),
                building('horse_farm', 0, 4000, [51, 101], city=1, oid=21),
            ],
        ))
        kept = synthesize_force(later, own_city, 0, ignore_city_ids={2})
        fields = [item['field'] for item in kept['operations']]
        self.assertIn('新建牧场', fields)
        self.assertNotIn('新建练兵所', fields)

    def test_event_index_skips_buildings_after_recent_capture(self):
        from replay_view import event_index
        start = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 9,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
        )
        taken = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 0,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
            extra={'snapshot_id': 'taken'},
        )
        delayed = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 0,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
            buildings=[building('parade_ground', 0, 5000, [61, 111], city=2, oid=20)],
            extra={'snapshot_id': 'delayed'},
        )
        fields = [row.get('field') for row in event_index([start, taken, delayed])]
        self.assertIn('得城', fields)
        self.assertNotIn('新建练兵所', fields)
        captured_at = {}
        record_city_captures(slim(start), slim(taken), 2, captured_at)
        self.assertEqual(recent_capture_ids(0, captured_at, 2 + CAPTURE_BUILDING_GRACE_FRAMES), {2})
        self.assertEqual(recent_capture_ids(0, captured_at, 3 + CAPTURE_BUILDING_GRACE_FRAMES), set())

    def test_event_index_skips_buildings_before_city_owner_updates(self):
        from replay_view import event_index
        start = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 9,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
        )
        early = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 9,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
            buildings=[building('parade_ground', 0, 5000, [61, 111], city=2, oid=20)],
            extra={'snapshot_id': 'early'},
        )
        taken = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            cities=[
                {'city_id': 1, 'name': '许昌', 'type': 'city', 'owner_raw': 0,
                 'population': 80000, 'world_xy_raw': [50, 100]},
                {'city_id': 2, 'name': '南阳', 'type': 'city', 'owner_raw': 0,
                 'population': 60000, 'world_xy_raw': [60, 110]},
            ],
            buildings=[building('parade_ground', 0, 5000, [61, 111], city=2, oid=20)],
            extra={'snapshot_id': 'taken'},
        )
        fields = [row.get('field') for row in event_index([start, early, taken])]
        self.assertIn('得城', fields)
        self.assertNotIn('新建练兵所', fields)

    def test_resume_keeps_closed_quarters(self):
        root = tempfile.mkdtemp()
        first = History(root)
        first.observe(snapshot([lord(0, '魏', (10000, 0, 0), (300, 0, 0))], year=200, season=1), session='a')
        first.observe(snapshot([lord(0, '魏', (12000, 0, 0), (260, 0, 0))], year=200, season=2), session='a')
        later = snapshot([lord(0, '魏', (13000, 0, 0), (250, 0, 0))], year=200, season=2)
        later['capture_end'] = '2026-09-14T02:10:00+00:00'
        out = History(root).observe(later, session='b')
        self.assertEqual(len(out['quarters']), 1)
        self.assertFalse(any(str(row.get('field') or '').startswith('募') for row in out['quarter_rows']))
        self.assertEqual(len(out['quarters']), 1)

    def test_slim_keeps_terrain_grid_and_unit_terrain(self):
        raw = bytearray(101 * 202)
        raw[4] = 4
        state = snapshot(
            [lord(0, '魏', (1, 0, 0), (0, 0, 0))],
            units=[{
                'unit_id': 1, 'unit_kind': '步兵', 'owner_raw': 0,
                'soldiers_candidate': 1000, 'world_xy_raw': [1, 2], 'general_ids': [],
                'terrain_type_raw': 9, 'on_water': False,
            }],
            extra={
                'terrain_grid': {
                    'width': 101, 'height': 202, 'types': raw.hex(),
                    'source': 'static_map_lookup_0x469f6f', 'unread_cells': 3,
                },
            },
        )
        out = slim(state)
        self.assertEqual(out['terrain_grid']['width'], 101)
        self.assertEqual(out['terrain_grid']['height'], 202)
        self.assertEqual(out['terrain_grid']['types'], raw.hex())
        self.assertEqual(out['terrain_grid']['source'], 'static_map_lookup_0x469f6f')
        self.assertNotIn('unread_cells', out['terrain_grid'])
        self.assertEqual(out['entities']['field_units'][0]['terrain_type_raw'], 9)
        self.assertIs(out['entities']['field_units'][0]['on_water'], False)

    def test_unit_move_and_sortie_lines(self):
        generals = [{'general_id_raw': 7, 'name': '张辽'}]
        before = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            units=[{
                'unit_id': 12, 'unit_kind': '强化步兵', 'owner_raw': 0,
                'soldiers_candidate': 5000, 'world_xy_raw': [53, 120], 'general_ids': [7],
            }],
            generals=generals,
        ))
        after = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            units=[
                {
                    'unit_id': 12, 'unit_kind': '强化步兵', 'owner_raw': 0,
                    'soldiers_candidate': 5000, 'world_xy_raw': [54, 118], 'general_ids': [7],
                },
                {
                    'unit_id': 13, 'unit_kind': '骑兵', 'owner_raw': 0,
                    'soldiers_candidate': 2000, 'world_xy_raw': [10, 10], 'general_ids': [],
                },
            ],
            generals=generals,
        ))
        self.assertEqual(before['entities']['field_units'][0]['world_xy_raw'], [53, 120])
        self.assertEqual(before['entities']['generals'][0]['name'], '张辽')
        acc = synthesize_force(before, after, 0)
        lines = [item['line'] for item in acc['operations']]
        self.assertIn('部队移动 强化步兵#12（张辽） (53,120) → (54,118)', lines)
        self.assertIn('出征 骑兵#13 出现于 (10,10)', lines)
        iron = {'unit_id': 9, 'unit_kind': '重装骑兵', 'general_ids': [7]}
        self.assertEqual(unit_display(iron, {7: '匡章'}), '铁骑兵#9（匡章）')
        self.assertEqual(military_chip_text({
            'field': '出征',
            'line': '出征 重装骑兵#9（匡章） 出现于 (211,129)',
        }), '出征 铁骑兵#9（匡章）')
        self.assertEqual(military_chip_text({
            'field': '部队移动',
            'line': '部队移动 重装骑兵#7（程远志） (1,2) → (3,4)',
        }), '部队移动 铁骑兵#7（程远志）')
        self.assertEqual(kind_label('铁骑兵'), '铁骑兵')
        self.assertEqual(kind_label('重装步兵'), '重装步兵')
        self.assertEqual(kind_line('训练骑兵 铁骑兵 0/100'), '训练骑兵 铁骑兵 0/100')
        sample = {'entities': {'field_units': [{'unit_kind': '重装骑兵'}, {'unit_kind': '骑兵'}]}}
        relabel_field_units(sample)
        self.assertEqual([row['unit_kind'] for row in sample['entities']['field_units']], ['铁骑兵', '骑兵'])
        self.assertTrue(any(item['field'] == '部队移动' and item['note'] == '观察到部队位移' for item in acc['operations']))

    def test_sortie_chip_writes_ambush_only(self):
        import struct
        from native_unit_rules import AMBUSH, HORSE
        line = {'field': '出征', 'line': '出征 骑兵#1（甲） 出现于 (1,1)'}
        self.assertEqual(military_chip_text(line), '出征 骑兵#1（甲）')
        horse = military_chip_text({**line, 'unit_snapshot': {'effective_skill_mask': HORSE, 'training_degree': 0}})
        self.assertEqual(horse, '出征 骑兵#1（甲） · 训练0/100')
        self.assertNotIn('技能', horse)
        self.assertEqual(military_chip_text({
            **line, 'unit_snapshot': {'effective_skill_mask': AMBUSH, 'training_degree': 46},
        }), '出征 骑兵#1（甲） · 训练46/100 · [伏兵]')
        raw = bytearray(0x46)
        struct.pack_into('<I', raw, 0x2a, AMBUSH)
        struct.pack_into('<H', raw, 0x44, 0)
        state = {'entities': {'generals': [{'general_id_raw': 3, 'raw_hex': raw.hex()}]}}
        snapped = {**line, 'unit_snapshot': {'general_ids': [3], 'training_degree': 0}}
        self.assertEqual(military_chip_text(snapped, state), '出征 骑兵#1（甲） · 训练0/100 · [伏兵]')
        struct.pack_into('<I', raw, 0x2a, HORSE)
        state['entities']['generals'][0]['raw_hex'] = raw.hex()
        self.assertEqual(military_chip_text(snapped, state), '出征 骑兵#1（甲） · 训练0/100')

    def test_summer_stock_increase_is_not_a_command(self):
        before = slim(snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))]))
        after = slim(snapshot([lord(0, '魏', (15000, 2000, 0), (80, 0, 0))]))
        acc = synthesize_force(before, after, 0)
        self.assertEqual(acc['operations'], [])
        self.assertTrue(acc['flat'])

    def test_hire_officer_from_wild(self):
        before = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            generals=[{
                'general_id_raw': 7, 'name': '张辽', 'owner_raw': 65535,
                'status_code': 1, 'location_city_id': 1,
            }],
        ))
        after = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            generals=[{
                'general_id_raw': 7, 'name': '张辽', 'owner_raw': 0,
                'status_code': 0, 'location_city_id': 1,
            }],
        ))
        acc = synthesize_force(before, after, 0)
        self.assertTrue(any(item['line'] == '加入 张辽：许昌' and item['field'] == '主动加入' for item in acc['operations']))
        self.assertFalse(any(item.get('field') == '录用' for item in acc['operations']))
        self.assertIn('军事阶段后', acc['operations'][0]['note'])

    def test_pending_hire_is_a_recruit_command(self):
        before = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            generals=[{
                'general_id_raw': 7, 'name': '张辽', 'owner_raw': 65535,
                'status_code': 1, 'location_city_id': 1,
            }],
        ))
        after = slim(snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
            generals=[{
                'general_id_raw': 7, 'name': '张辽', 'owner_raw': 0,
                'status_code': 9, 'location_city_id': 1,
            }],
        ))
        acc = synthesize_force(before, after, 0)
        self.assertTrue(any(item.get('field') == '录用' for item in acc['operations']))
        self.assertFalse(any(item.get('field') == '主动加入' for item in acc['operations']))

    def test_annotate_splits_recruit_from_walk_in(self):
        history = {'quarters': [{
            'phase': {'year_u16': 200, 'season_u16': 2, 'round_u8': 0},
            'forces': [{'owner': 13, 'operations': [
                {'field': '主动加入', 'after': '公叔痤', 'general_id': 1, 'line': '加入 公叔痤：柴桑'},
                {'field': '主动加入', 'after': '黄祖', 'general_id': 2, 'line': '加入 黄祖：临晋'},
            ]}],
        }]}
        annotate_hire_kinds(history, [
            {'force_id': 13, 'general_id': 1, 'name': '公叔痤', 'kind': '募将'},
            {'force_id': 13, 'general_id': 2, 'name': '黄祖', 'kind': '自动加入'},
        ])
        ops = history['quarters'][0]['forces'][0]['operations']
        self.assertEqual([item['hire_kind'] for item in ops], ['募将', '自动加入'])

    def test_founding_season0_starting_officers_are_not_commands(self):
        root = tempfile.mkdtemp()
        store = History(root)
        first = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))], year=200, season=0,
            generals=[{
                'general_id_raw': 2, 'name': '甄宓', 'owner_raw': 65535,
                'status_code': 1, 'location_city_id': 1,
            }],
        )
        store.observe(first, session='s', player_force_id=0)
        closed = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))], year=200, season=1,
            generals=[{
                'general_id_raw': 2, 'name': '甄宓', 'owner_raw': 0,
                'status_code': 0, 'location_city_id': 1,
            }],
        )
        closed['capture_end'] = '2026-09-14T02:00:00+00:00'
        out = store.observe(closed, session='s', player_force_id=0)
        lines = [row.get('line') for row in (out.get('last_quarter') or {}).get('rows') or []]
        self.assertTrue((out.get('last_quarter') or {}).get('founding'))
        self.assertFalse(any(line and ('甄宓' in line or '录用' in str(line) or '加入' in str(line)) for line in lines))

    def test_refresh_drops_founding_recorded_hires(self):
        account = {
            'label': '年200·季候选0（已过季）', 'phase': {'year_u16': 200, 'season_u16': 0},
            'founding': True,
            'forces': [{'owner': 0, 'name': '宋', 'operations': [
                {'field': '新建练兵所', 'line': '新建 2 座练兵所：商丘、寿春', 'before': '', 'after': '', 'note': ''},
                {'field': '录用', 'line': '录用 甄宓：西河', 'before': '在野', 'after': '甄宓', 'note': ''},
            ]}],
        }
        refresh_account(account)
        self.assertEqual([item['field'] for item in account['forces'][0]['operations']], ['新建练兵所'])

    def test_incomplete_general_baseline_is_not_hire(self):
        before = slim(snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
                               generals=[{'general_id_raw': 7, 'name': '张辽'}]))
        after = slim(snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))],
                              generals=[{
                                  'general_id_raw': 7, 'name': '张辽', 'owner_raw': 0,
                                  'status_code': 0, 'location_city_id': 1,
                              }]))
        acc = synthesize_force(before, after, 0)
        self.assertFalse(any(item.get('field') == '录用' for item in acc['operations']))

    def test_recent_quarter_ops_last_two(self):
        hist = {
            'quarters': [{'label': '季0', 'forces': [{'owner': 0, 'operations': [{'line': '新建 1 座练兵所：许昌'}]}]}],
            'current_quarter': {'label': '季1', 'forces': [{'owner': 0, 'operations': [{'line': '出征 骑兵#1 出现于 (1,1)'}]}]},
        }
        blocks = recent_quarter_ops(hist, 0, 2)
        self.assertEqual([b['label'] for b in blocks], ['季0', '季1'])
        self.assertEqual(blocks[1]['operations'][0]['line'], '出征 骑兵#1 出现于 (1,1)')
        three = recent_quarter_ops(hist, 0)
        self.assertEqual(len(three), 2)

    def test_split_quarter_lanes_civil_and_military(self):
        hist = {
            'quarters': [{
                'label': '年200·季候选0（已过季）',
                'forces': [{'owner': 0, 'operations': [
                    {'field': '新建练兵所', 'line': '新建 3 座练兵所：陈留、许昌、汝南'},
                ]}],
            }, {
                'label': '年200·季候选1（已过季）',
                'forces': [{'owner': 0, 'operations': [
                    {'field': '录用', 'after': '黄祖', 'line': '录用 黄祖：陈留'},
                    {'field': '录用', 'after': '苏飞', 'line': '录用 苏飞：汝南'},
                    {'field': '出征', 'line': '出征 强弓兵#0（军神） 出现于 (61,79) 近陈留'},
                ]}],
            }],
            'current_quarter': {'label': '年200·季候选2（进行中）', 'forces': [{'owner': 0, 'operations': []}]},
        }
        lanes = split_quarter_lanes(hist, 0, 3)
        self.assertEqual([row['short'] for row in lanes], ['200年春', '200年夏', '200年秋'])
        self.assertEqual([item['after'] for item in lanes[1]['civil']], ['黄祖', '苏飞'])
        self.assertEqual(military_chip_text(lanes[1]['military'][0]), '出征 强弓兵#0（军神）')
        hist['quarters'][1]['forces'][0]['operations'].append(
            {'field': '主动加入', 'after': '邓艾', 'line': '加入 邓艾：庐江'})
        mixed = split_quarter_lanes(hist, 0, 3)
        self.assertTrue(any(item.get('after') == '邓艾' for item in mixed[1]['civil']))
        self.assertFalse(any(item.get('after') == '邓艾' for item in mixed[1]['military']))
        self.assertTrue(is_civil_op({'field': '主动加入'}))
        self.assertTrue(is_civil_op({'field': '录用'}))
        hired = hire_quarter_lanes(hist, 0)
        self.assertEqual([row['short'] for row in hired], ['200年春', '200年夏', '200年秋'])
        self.assertEqual(hired[0]['hires'], [])
        self.assertEqual([item['after'] for item in hired[1]['hires']], ['黄祖', '苏飞', '邓艾'])
        self.assertEqual(hired[2]['hires'], [])
        self.assertTrue(all(item.get('field') in ('录用', '主动加入') for item in hired[1]['hires']))

    def test_prestige_commands_alms_and_green_card(self):
        def lord(fid, name, prestige, cards, relations):
            return {
                'force_id': fid, 'name': name, 'prestige': prestige,
                'hand_cards': {'slots': [{'card_id': cid} for cid in cards]},
                'diplomacy_relations': relations,
            }
        duo_before = [lord(1, '义渠', 148, [8, 26], [0] * 22), lord(2, '西凉', 85, [13], [0] * 22)]
        duo_after = [lord(1, '义渠', 153, [8, 26], [0] * 22), lord(2, '西凉', 85, [13], [0] * 22)]
        alms = prestige_command_ops(duo_before, duo_after)
        self.assertEqual([item['field'] for item in alms], ['布施'])
        self.assertIn('+5', alms[0]['line'])
        self.assertTrue(is_civil_op(alms[0]))
        small = prestige_command_ops(
            [lord(1, '义渠', 100, [], [0] * 22), lord(2, '西凉', 80, [], [0] * 22)],
            [lord(1, '义渠', 101, [], [0] * 22), lord(2, '西凉', 80, [], [0] * 22)],
        )
        self.assertEqual(small, [])
        rel_a = [0] * 22
        rel_b = [0] * 22
        rel_a[2] = 3
        rel_b[1] = 3
        rel_c = [0] * 22
        before = [
            lord(1, '齐', 140, [13, 8], rel_a),
            lord(2, '燕', 163, [12], rel_b),
            lord(3, '晋', 135, [8], rel_c),
        ]
        after = [
            lord(1, '齐', 140, [8], rel_a),
            lord(2, '燕', 181, [12], rel_b),
            lord(3, '晋', 135, [8], rel_c),
        ]
        gift = prestige_command_ops(before, after)
        self.assertTrue(any(item['owner'] == 1 and '援助军粮' in item['line'] and '燕' in item['line'] for item in gift))
        self.assertTrue(any(item['owner'] == 2 and item['field'] == '赠绿卡' for item in gift))
        self.assertFalse(any(item['field'] == '布施' for item in gift))
        swap = prestige_command_ops(
            [lord(1, '齐', 140, [14], rel_a), lord(2, '燕', 163, [], rel_b)],
            [lord(1, '齐', 140, [13], rel_a), lord(2, '燕', 181, [], rel_b)],
        )
        self.assertFalse(any(item['field'] == '赠绿卡' for item in swap))

    def test_merge_prestige_opens_the_round_the_ledger_has_not_closed(self):
        history = {'quarters': [{
            'phase': {'year_u16': 201, 'season_u16': 0, 'round_u8': 0},
            'label': '201年春 · 内政',
            'forces': [{'owner': 14, 'name': '西凉', 'operations': []}],
        }]}
        merge_prestige_commands(history, [{
            'field': '布施', 'line': '布施：信望 85 → 112（+27）', 'owner': 14, 'name': '西凉',
            'phase': {'year_u16': 201, 'season_u16': 0, 'round_u8': 1, 'turn_u16': 2},
            'command': True,
        }])
        lanes = split_quarter_lanes(history, 14, None)
        self.assertEqual(lanes[-1]['short'], '201年春 第2回合')
        self.assertEqual(lanes[-1]['civil'][0]['field'], '布施')
        self.assertFalse(is_military_op({'field': '主动加入'}))
        self.assertTrue(is_military_op({'field': '出征'}))
        self.assertEqual(short_quarter_label('年200·季候选1（已过季）'), '200年夏')
        self.assertEqual(short_quarter_label('季0', {'year_u16': 200, 'season_u16': 0}), '200年春 · 内政')
        self.assertEqual(short_quarter_label('200年冬 第1回合（已过季）'), '200年冬 第1回合')
        self.assertEqual(short_quarter_label('进行中', {'year_u16': 200, 'season_u16': 3, 'round_u8': 2}), '200年冬 第3回合')
        winter = {
            'quarters': [
                {'label': '200年冬 第1回合（已过季）', 'phase': {'year_u16': 200, 'season_u16': 3, 'round_u8': 0},
                 'forces': [{'owner': 0, 'operations': []}]},
                {'label': '200年冬 第2回合（已过季）', 'phase': {'year_u16': 200, 'season_u16': 3, 'round_u8': 1},
                 'forces': [{'owner': 0, 'operations': []}]},
                {'label': '200年冬 第2回合（已过季）', 'phase': {'year_u16': 200, 'season_u16': 3, 'round_u8': 1},
                 'forces': [{'owner': 0, 'operations': []}]},
            ],
            'current_quarter': {
                'label': '200年冬 第3回合（进行中）', 'phase': {'year_u16': 200, 'season_u16': 3, 'round_u8': 2},
                'forces': [{'owner': 0, 'operations': [{'field': '主动加入', 'line': '加入 孙乾：武都'}]}],
            },
        }
        winter_lanes = split_quarter_lanes(winter, 0, 3)
        self.assertEqual([row['short'] for row in winter_lanes], ['200年冬 第1回合', '200年冬 第2回合', '200年冬 第3回合'])
        self.assertEqual(phase_label({'year_u16': 200, 'season_u16': 0}), '200年春 · 内政')
        self.assertEqual(phase_label({'year_u16': 202, 'season_u16': 2}), '202年秋')
        self.assertEqual(phase_label({'year_u16': 201, 'season_u16': 3}), '201年冬')
        self.assertEqual(phase_label({'year_u16': 200, 'season_u16': 1, 'round_u8': 0}), '200年夏 第1回合')
        self.assertEqual(phase_label({'year_u16': 200, 'season_u16': 1, 'round_u8': 2}), '200年夏 第3回合')
        self.assertEqual(season_round(0), 0)
        self.assertEqual(season_round(1), 0)
        self.assertEqual(season_round(4), 2)
        self.assertEqual(season_round(5), 2)
        self.assertEqual(short_quarter_label('200年春'), '200年春')
        self.assertEqual(calendar_label(200, 0), '200年春')
        self.assertEqual(calendar_label(200, 3), '200年冬')

    def test_refresh_account_drops_summer_recruit(self):
        account = {
            'label': '季1', 'phase': {'year_u16': 200, 'season_u16': 1},
            'forces': [{'owner': 0, 'name': '魏', 'operations': [
                {'field': '募步兵', 'line': '募步兵 1,000', 'before': '', 'after': '', 'note': ''},
                {'field': '出征', 'line': '出征 x', 'before': '', 'after': '', 'note': ''},
            ]}],
        }
        refresh_account(account)
        self.assertEqual([item['field'] for item in account['forces'][0]['operations']], ['出征'])
        self.assertTrue(any(row.get('line') == '出征 x' for row in account['rows']))
        self.assertFalse(any(str(row.get('field') or '').startswith('募') for row in account['rows']))

    def test_status9_backfill_last_quarter_when_old_slim_lacks_owner(self):
        root = tempfile.mkdtemp()
        store = History(root)
        first = snapshot(
            [lord(0, '魏', (10000, 0, 0), (80, 0, 0))], year=200, season=1,
            generals=[{'general_id_raw': 123, 'name': '黄祖'}],
        )
        store.observe(first, session='s', player_force_id=0)
        closed = snapshot(
            [lord(0, '魏', (15000, 0, 0), (80, 0, 0))], year=200, season=2,
            generals=[{'general_id_raw': 123, 'name': '黄祖'}],
        )
        closed['capture_end'] = '2026-09-14T02:00:00+00:00'
        store.observe(closed, session='s', player_force_id=0)
        live = snapshot(
            [lord(0, '魏', (15000, 0, 0), (80, 0, 0))], year=200, season=2,
            generals=[{
                'general_id_raw': 123, 'name': '黄祖', 'owner_raw': 0,
                'status_code': 9, 'location_city_id': 1,
            }],
        )
        live['capture_end'] = '2026-09-14T02:10:00+00:00'
        out = store.observe(live, session='s', player_force_id=0)
        lines = [row.get('line') for row in (out.get('last_quarter') or {}).get('rows') or []]
        self.assertIn('录用 黄祖：许昌', lines)
        current_lines = [item.get('line') for force in out['current_quarter']['forces']
                         for item in force.get('operations') or []]
        self.assertNotIn('录用 黄祖：许昌', current_lines)
        self.assertTrue(any(row.get('line') == '录用 黄祖：许昌' for row in out['quarter_rows']))

    def test_no_commands_empty_quarter_rows(self):
        root = tempfile.mkdtemp()
        store = History(root)
        first = store.observe(snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))]), session='s')
        self.assertEqual(first['quarter_rows'], [])
        later = snapshot([lord(0, '魏', (10000, 0, 0), (80, 0, 0))])
        later['capture_end'] = '2026-09-14T01:10:00+00:00'
        out = store.observe(later, session='s')
        self.assertEqual(out['quarter_rows'], [])

    def test_no_song_hardcode_in_source(self):
        text = Path(__file__).with_name('state_history.py').read_text(encoding='utf-8')
        self.assertNotIn('宋·操作层', text)
        self.assertNotIn("'owner':11", text.replace(' ', ''))

    def test_troop_series_keeps_each_quarter_without_app_on_path(self):
        import sys
        app = str(Path(__file__).resolve().parents[1] / 'app')
        saved = list(sys.path)
        sys.modules.pop('force_troop_totals', None)
        sys.path[:] = [p for p in saved if Path(p).resolve() != Path(app).resolve()]
        try:
            root = tempfile.mkdtemp()
            store = History(root)
            spring = snapshot([lord(0, '魏', (10000, 0, 0), (40, 0, 0))], year=200, season=0)
            winter = snapshot([lord(0, '魏', (18000, 4000, 0), (80, 50, 0))], year=200, season=3)
            winter['capture_end'] = '2026-09-14T03:00:00+00:00'
            first = store.observe(spring, session='s')
            later = store.observe(winter, session='s')
            labels = [row.get('label') for row in later.get('troop_series') or []]
            self.assertGreaterEqual(len(labels), 2)
            self.assertIn('春', labels[0])
            self.assertIn('冬', labels[-1])
            self.assertNotEqual(labels[0], labels[-1])
            self.assertGreaterEqual(len(first.get('troop_series') or []), 1)
        finally:
            sys.path[:] = saved
            sys.modules.pop('force_troop_totals', None)


if __name__ == '__main__':
    unittest.main()
