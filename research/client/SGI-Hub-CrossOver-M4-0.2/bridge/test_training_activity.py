from copy import deepcopy
import unittest

from training_activity import activity_counts


def packet(subtype=0, parameter=1, entry='entry1', season=0, actor=5):
    return dict(native_type=18, subtype=subtype, parameter_raw=parameter,
                actor_force_id=actor, queue_entry_hex=entry, raw_sha256='same-payload',
                observed_at='2026-10-11T08:30:00+00:00', observations=50,
                command_committed=None, action_training_eligible=False,
                sampling_calendar=dict(year_u16=200, season_u16=season, basis='sampling_time_correlation'))


def quarter(ops, season=0, owner=5):
    return dict(phase=dict(year_u16=200, season_u16=season),
                forces=[dict(owner=owner, operations=ops)])


class TrainingActivityTests(unittest.TestCase):
    def test_queue_reobservations_dedup_but_distinct_entries_and_seasons_count(self):
        a = packet()
        state = {'native_command_evidence': {'rows': [a, deepcopy(a), packet(entry='entry2'), packet(entry='entry3', season=1)]}}
        before = deepcopy(state)
        for _ in range(2):
            result = activity_counts(state, 5)
            self.assertEqual(result['training'], 3)
            self.assertEqual(result['by_kind']['cavalry']['training'], 3)
            self.assertEqual(result['building'], 0)
            self.assertEqual(result['coverage'], 'retained_records')
        self.assertEqual(state, before)

    def test_all_kinds_and_only_construction_orders_not_scout_traps_or_demolition(self):
        rows = [packet(parameter=p, entry=f't{p}') for p in range(3)]
        rows += [packet(subtype=4, parameter=p, entry=f'b{p}') for p in (7, 8, 9)]
        rows += [packet(subtype=s, parameter=p, entry=f'other{s}{p}') for s, p in ((4, 6), (5, 7), (8, 7), (0, 99))]
        result = activity_counts({'native_command_evidence': {'rows': rows}}, 5)
        self.assertEqual((result['training'], result['building']), (3, 3))
        self.assertTrue(all(v == {'training': 1, 'building': 1} for v in result['by_kind'].values()))

    def test_state_and_native_views_overlap_without_double_counting_multi_camp_rows(self):
        ops = [dict(field='训练骑兵', line='训练骑兵 80→100', before='80', after='100'),
               dict(field='新建练兵所', line='新建 3 座练兵所：许昌、许昌、洛阳', places=['许昌', '许昌', '洛阳'])]
        later = [dict(field='训练骑兵', line='训练骑兵 100→130', before='100', after='130'),
                 dict(field='新建牧场', line='新建 2 座牧场')]
        first = quarter(ops)
        state = dict(native_command_evidence={'rows': [packet(), packet(entry='t2'), packet(4, 7, 'b1')]},
                     history={'quarters': [first], 'current_quarter': deepcopy(first)})
        result = activity_counts(state, 5)
        self.assertEqual((result['training'], result['building']), (2, 3))
        state['history']['current_quarter'] = quarter(later, season=1)
        result = activity_counts(state, 5)
        self.assertEqual((result['training'], result['building']), (3, 5))
        self.assertEqual(result['by_kind']['infantry']['building'], 3)
        self.assertEqual(result['by_kind']['cavalry']['building'], 2)

    def test_retained_camp_ledger_includes_each_build_but_not_current_owned_camps(self):
        row = dict(owner=5, kind='牧场', phase={'year_u16': 200, 'season_u16': 0},
                   line='新建 1 座牧场', places=['洛阳'], seq=12)
        state = dict(history={'camp_builds': [row, deepcopy(row), dict(row, seq=15), dict(row, owner=7)]},
                     entities={'production_buildings': [{'owner_raw': 5, 'type': 'parade_ground'}]})
        result = activity_counts(state, 5)
        self.assertEqual(result['building'], 2)
        self.assertEqual(result['by_kind']['infantry']['building'], 0)
        self.assertEqual(result['training'], 0)

    def test_source_peer_duplicates_and_other_forces_do_not_inflate_totals(self):
        a = packet()
        state = dict(native_command_evidence={'binding': {'source_id': 'PRIMARY'},
                     'rows': [a, packet(actor=7)],
                     'supplemental_sources': [{'binding': {'source_id': 'PEER'}, 'rows': [deepcopy(a)]}]},
                     history={'quarters': [quarter([dict(field='训练步兵', line='训练步兵 10→30')], owner=7)]})
        self.assertEqual(activity_counts(state, 5)['training'], 1)
        self.assertEqual(activity_counts(state, 7)['training'], 2)
        self.assertEqual(activity_counts(state, 2)['training'], 0)
        self.assertEqual(activity_counts(state, None)['training'], 0)
        self.assertEqual(activity_counts({}, 5)['building'], 0)

    def test_missing_packet_date_does_not_add_a_second_view_of_the_same_training(self):
        row = packet()
        row.pop('sampling_calendar')
        state = dict(native_command_evidence={'rows': [row]},
                     history={'quarters': [quarter([dict(field='训练骑兵', line='训练骑兵 80→100')])]})
        self.assertEqual(activity_counts(state, 5)['training'], 1)
        state['native_command_evidence']['rows'].append(dict(row, queue_entry_hex='entry2'))
        self.assertEqual(activity_counts(state, 5)['training'], 2)


if __name__ == '__main__':
    unittest.main()
