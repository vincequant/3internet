import copy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))
from wild_locations import wild_location_groups
from decision_support import recommend_officers
from talent_filters import TalentFilters
from city_talent import city_wild_officers, summarize


def state():
    def officer(i, location, name='诸葛亮'):
        return dict(general_id_raw=i, container_index=i, name=name, status_code=1,
                    owner_raw=65535, location_city_id=location,
                    attributes=dict(lead=100, war=100, intel=100, pol=100, cha=100))
    return {'entities': {'generals': [officer(1, 0), officer(2, 1), officer(3, None)],
                         'cities_and_barriers': [dict(city_id=0, type='city', name='关城'),
                                                 dict(city_id=1, type='barrier', name='虎牢')],
                         'lords': []}}


class WildLocations(unittest.TestCase):
    def test_uses_live_type_not_names_and_keeps_unknown_distinct(self):
        s = state(); before = copy.deepcopy(s)
        visible, hidden = wild_location_groups(s)
        self.assertEqual([g['general_id_raw'] for g in visible], [1, 3])
        self.assertEqual([g['general_id_raw'] for g in hidden], [2])
        self.assertEqual(s, before)

    def test_moves_to_city_then_back_are_recomputed(self):
        s = state(); g = s['entities']['generals'][1]
        self.assertNotIn(g, wild_location_groups(s)[0])
        g['location_city_id'] = 0
        self.assertIn(g, wild_location_groups(s)[0])
        g['location_city_id'] = 1
        self.assertNotIn(g, wild_location_groups(s)[0])

    def test_unknown_and_duplicate_ids_are_not_guessed(self):
        s = state(); s['entities']['cities_and_barriers'].append(dict(city_id=1, type='city'))
        self.assertEqual(len(wild_location_groups(s)[0]), 3)
        s = state(); s['entities']['generals'][1]['location_city_id'] = True
        self.assertEqual(len(wild_location_groups(s)[0]), 3)

    def test_active_captured_and_owned_are_not_wild(self):
        s = state(); s['entities']['generals'][0]['status_code'] = 0
        s['entities']['generals'][1]['status_code'] = 4
        s['entities']['generals'][2]['owner_raw'] = 1
        self.assertEqual(wild_location_groups(s), ([], []))

    def test_both_list_and_recommendations_hide_barriers(self):
        s = state()
        filters = SimpleNamespace(task=SimpleNamespace(get=lambda: '全部在野'),
                                  role='全部人才', selected=set())
        self.assertEqual([r['officer']['general_id_raw'] for r in TalentFilters.rank(filters, s)], [1, 3])
        for task in ['战斗', '训练 / 内政', '计略', '网站攻击力', '网站计略', '网站外交力', '五维总和']:
            with self.subTest(task=task):
                self.assertEqual([r['officer']['general_id_raw'] for r in recommend_officers(s, task)], [1, 3])

    def test_city_totals_exclude_barriers_but_keep_unknown_count(self):
        rows, meta = summarize(state())
        self.assertEqual(meta, dict(total=2, hidden_barriers=1, unlocated=1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['total'], 1)
        self.assertNotIn('g450', rows[0])
        self.assertEqual(rows[0]['blade'], 200)
        self.assertEqual(rows[0]['pol'], 100)
        self.assertEqual(rows[0]['ride'], 0)
        self.assertNotIn('unknown', rows[0])

    def test_city_wild_officers_are_that_city_only(self):
        s = state()
        rows = city_wild_officers(s, s['entities']['cities_and_barriers'][0])
        self.assertEqual([g['general_id_raw'] for g in rows], [1])
        self.assertEqual(city_wild_officers(s, s['entities']['cities_and_barriers'][1]), [])
        self.assertEqual(city_wild_officers(s, {'city_id': None}), [])


if __name__ == '__main__':
    unittest.main()
