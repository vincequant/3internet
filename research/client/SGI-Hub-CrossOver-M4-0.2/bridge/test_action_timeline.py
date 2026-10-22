import copy
import unittest

from action_timeline import timeline_groups, diplomacy_text, observation_text
from native_command_evidence import decode

CREATE = 'ffff010018004353616e496e6574556e69744e6574436d6443726561746510000000000000000000000000000005002a02ffffffff881300008813000001000100ffffffffffff'


def fixture():
    row = decode(bytes.fromhex(CREATE))
    row.update(observed_at='2026-10-11T07:52:32+00:00',
               sampling_calendar=dict(year_u16=200, season_u16=0, basis='sampling_time_correlation'))
    unit = dict(unit_id=0, owner_raw=5, general_ids=[554, None, None], soldiers_candidate=5000,
                training_degree=50, target_attack_unit='54')
    item = dict(field='出征', line='出征 步兵#0（老子） 出现于 (73,19)', command=True,
                target=dict(kind='field_units', unit_id=0), unit_snapshot=unit)
    history = dict(quarters=[dict(phase=dict(year_u16=200, season_u16=0),
                                forces=[dict(owner=5, operations=[item])])])
    entities = dict(generals=[dict(general_id_raw=554, name='老子')], lords=[dict(force_id=16, name='代')])
    return row, item, history, entities


class ActionTimelineTests(unittest.TestCase):
    def test_three_sorties_merge_response_stays_unnumbered_and_evidence_unchanged(self):
        row, item, history, entities = fixture()
        rows=[]; ops=[]
        for i, gid in enumerate((554, 560, 656)):
            r=copy.deepcopy(row);r['general_ids_raw']=[gid,-1,-1];rows.append(r)
            o=copy.deepcopy(item);o['unit_snapshot']['general_ids']=[gid,None,None];ops.append(o)
        history['quarters'][0]['forces'][0]['operations']=ops
        rows.append(dict(row, native_type=19, subtype=1, flags_raw=[30,0,0,0,0], other_raw=16, other2_raw=-1))
        original=copy.deepcopy((rows,history))
        group=timeline_groups(rows,history,5,entities)[0]
        self.assertEqual(len(group['entries']),3)
        self.assertTrue(all(e['evidence']=='封包＋观察' for e in group['entries']))
        self.assertEqual(len(group['responses']),1)
        self.assertEqual(diplomacy_text(group['responses'][0]['raw'],entities),'外交回应 接受 → 代')
        self.assertEqual((rows,history),original)

    def test_selected_cards_come_from_flags_not_remaining_hand(self):
        row=dict(native_type=19, subtype=0,flags_raw=[7,0,0,0,0],cards_raw=[14,12,9,12,0],other_raw=16,other2_raw=554)
        entities=fixture()[3]
        text=diplomacy_text(row,entities)
        self.assertEqual(text,'外交 援助友军 → 代 · 老子')
        self.assertNotIn('援助金钱',text)
        self.assertIsNone(diplomacy_text(dict(row,subtype=3),entities))

    def test_other_force_and_other_season_never_merge(self):
        row,item,history,entities=fixture()
        row['actor_force_id']=1
        group=timeline_groups([row],history,5,entities)[0]
        self.assertEqual(group['entries'][0]['evidence'],'观察')
        row['actor_force_id']=5;row['sampling_calendar']['season_u16']=1
        groups=timeline_groups([row],history,5,entities)
        self.assertEqual([g['label'] for g in groups],['200年夏','200年春'])
        self.assertEqual([g['entries'][0]['evidence'] for g in groups],['封包','观察'])

    def test_duplicate_packets_do_not_hide_ambiguous_appearance(self):
        row,item,history,entities=fixture()
        group=timeline_groups([row,copy.deepcopy(row)],history,5,entities)[0]
        self.assertEqual(len(group['entries']),3)
        self.assertEqual(group['entries'][-1]['evidence'],'观察')

    def test_old_unit_id_alone_is_not_a_match(self):
        row,item,history,entities=fixture()
        item['unit_snapshot']['general_ids']=[999,None,None]
        group=timeline_groups([row],history,5,entities)[0]
        self.assertEqual(len(group['entries']),2)

    def test_peer_packet_does_not_acquire_local_sortie_stats(self):
        row,item,history,entities=fixture();row['display_source']='COM'
        group=timeline_groups([row],history,5,entities)[0]
        self.assertEqual([e['evidence'] for e in group['entries']],['封包','观察'])

    def test_multiple_observed_automatic_joins_with_no_packets(self):
        row,item,history,entities=fixture()
        history['quarters'][0]['forces'][0]['operations']=[
            dict(field='主动加入',after='甲',general_id=1,command=True),
            dict(field='主动加入',after='乙',general_id=2,command=True)]
        group=timeline_groups([],history,5,entities)[0]
        self.assertEqual(group['entries'],[])
        self.assertEqual(len(group['automatic_joins']),2)

    def test_frozen_sortie_values_and_movement_lanes(self):
        row,item,history,entities=fixture()
        text=observation_text(item)
        self.assertIn('攻击54',text);self.assertIn('训练50/100',text)
        history['quarters'][0]['forces'][0]['operations'].append(dict(field='部队移动',line='部队移动 步兵#0 73,19 → 74,19',command=True))
        groups=timeline_groups([row],history,5,entities)
        civil=next(g for g in groups if g['lane']=='civil')
        military=next(g for g in groups if g['lane']=='military')
        self.assertEqual(len(civil['entries']),1)
        self.assertEqual(military['entries'][0]['observation']['field'],'部队移动')

    def test_automatic_join_does_not_take_a_number(self):
        row,item,history,entities=fixture()
        row.update(native_type=20,subtype=1,target_raw=554)
        history['quarters'][0]['forces'][0]['operations']=[dict(field='主动加入',after='老子',general_id=554,command=True)]
        g=timeline_groups([row],history,5,entities)[0]
        self.assertEqual(g['entries'],[])
        self.assertEqual(len(g['automatic_joins']),1)
        self.assertEqual(g['automatic_joins'][0]['evidence'],'封包＋观察')


if __name__=='__main__':unittest.main()
