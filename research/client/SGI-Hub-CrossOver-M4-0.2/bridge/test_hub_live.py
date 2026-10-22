import json
import unittest

from hub_live import hub_live_document, kind_label


def payload():
    return {
        'fresh': True,
        'phase': 'live',
        'release_version': '1.1.274',
        'source_id': 'VKQUANT',
        'snapshot_age_s': 0.4,
        'state': {
            'snapshot_id': 'snap-1',
            'capture_end': '2026-09-25T04:55:22+00:00',
            'player_identity': {'status': 'unknown', 'force_id': None},
            'player_context': {'status': 'unknown'},
            'history': {
                'phase_label': '200年春 · 内政',
                'quarters': [],
                'current_quarter': {
                    'label': '200年秋',
                    'phase': {'year_u16': 200, 'season_u16': 2},
                    'forces': [{
                        'owner': 3,
                        'operations': [
                            {'field': '训练', 'line': '训练骑兵 铁骑兵 0/100 → 铁骑兵 92/100'},
                            {'field': '出征', 'line': '出征 重装骑兵#9（匡章） 出现于 (1,2)'},
                        ],
                    }],
                },
            },
            'entities': {
                'lords': [{
                    'force_id': 3, 'name': '魏', 'color_index_raw': 1,
                    'gold': 10, 'rice': 20, 'prestige': 30,
                    'troop_stock': {'infantry': 1, 'cavalry': 2, 'bow': 3},
                    'armament_raw': {'infantry': 204, 'cavalry': 221, 'bow': 80},
                }],
                'generals': [
                    {'general_id_raw': 7, 'name': '匡章', 'owner_raw': 3, 'status_code': 2,
                     'status_label': '出阵', 'location_city_name': '零陵',
                     'attributes': {'lead': 80, 'war': 77, 'intel': 1, 'pol': 1, 'cha': 1},
                     'soldiers': 1000},
                    {'general_id_raw': 8, 'name': '未出场', 'owner_raw': 3, 'status_code': 3,
                     'status_label': '未登场'},
                ],
                'cities_and_barriers': [
                    {'city_id': 1, 'name': '蓟', 'type': 'city', 'owner_raw': 3,
                     'population': 50000, 'morale': 80, 'world_xy_raw': [66, 21]},
                ],
                'traps': [
                    {'trap_id': 1, 'trap_kind': '落石', 'world_xy_raw': [67, 22]},
                ],
                'field_units': [{
                    'unit_id': 9, 'unit_kind': '重装骑兵', 'owner_raw': 3,
                    'world_xy_raw': [67, 22], 'soldiers_candidate': 2400,
                    'general_ids': [7], 'morale': 70,
                }],
            },
        },
    }


class HubLive(unittest.TestCase):
    def test_slim_document_uses_iron_cavalry_and_drops_undeployed(self):
        doc = hub_live_document(payload())
        self.assertEqual(doc['snapshot_id'], 'snap-1')
        self.assertFalse(doc['player']['confirmed'])
        self.assertEqual(doc['forces'][0]['training']['cavalry']['name'], '铁骑兵')
        self.assertEqual(doc['forces'][0]['training']['cavalry']['progress'], 21)
        self.assertEqual(doc['units'][0]['kind'], '铁骑兵')
        self.assertEqual(doc['units'][0]['generals'], ['匡章'])
        self.assertTrue(doc['cities'][0]['traps'])
        self.assertEqual([row['name'] for row in doc['officers']], ['匡章'])
        self.assertEqual(doc['forces'][0]['best_blade'], {'name': '匡章', 'value': 157, 'boosted': False})
        self.assertEqual(doc['forces'][0]['best_politics']['value'], 1)
        line = doc['quarters'][-1]['forces'][0]['operations'][1]['line']
        self.assertIn('铁骑兵#9', line)
        self.assertNotIn('重装骑兵', json.dumps(doc, ensure_ascii=False))
        self.assertNotIn('raw_hex', json.dumps(doc))
        self.assertEqual(kind_label('重装步兵'), '重装步兵')

    def test_missing_snapshot_is_skipped(self):
        self.assertIsNone(hub_live_document({'state': {}}))


if __name__ == '__main__':
    unittest.main()
