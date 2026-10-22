import copy
import unittest

from command_display import command_groups, sampling_calendar, short_command


def window(season, start, end):
    return {'phase': {'year_u16': 200, 'season_u16': season},
            'from': '2026-10-10T' + start + '+00:00',
            'to': '2026-10-10T' + end + '+00:00'}


class CommandDisplayTests(unittest.TestCase):
    def test_calendar_is_sampling_correlation_not_an_order_or_match_binding(self):
        history = {'quarters': [window(0, '08:00:00', '09:00:00')],
                   'current_quarter': window(1, '09:00:00', '10:00:00')}
        old = dict(native_type=18, action='步兵训练', observed_at='2026-10-10T08:30:00+00:00',
                   game_quarter=None, match_id=None, command_committed=None, action_training_eligible=False)
        new = dict(old, observed_at='2026-10-10T09:30:00+00:00')
        original = copy.deepcopy([old, new])
        groups = command_groups([old, new], history)
        self.assertEqual([g['label'] for g in groups], ['200年夏', '200年春'])
        self.assertEqual([old, new], original)
        self.assertEqual(groups[0]['lane'], 'civil')

    def test_boundaries_overlaps_missing_invalid_and_outside_dates_stay_unknown(self):
        history = {'quarters': [window(0, '08:00:00', '09:00:00'), window(1, '09:00:00', '10:00:00')]}
        for stamp in ('2026-10-10T09:00:00+00:00', '2026-10-10T08:59:59+00:00',
                      '2026-10-10T09:00:01+00:00', '2026-10-10T07:00:00+00:00',
                      '2026-10-10T08:30:00', 'bad', None):
            self.assertIsNone(sampling_calendar({'observed_at': stamp}, history))
        overlap = {'quarters': [window(0, '08:00:00', '10:00:00'), window(1, '08:00:00', '10:00:00')]}
        self.assertIsNone(sampling_calendar({'observed_at':'2026-10-10T08:30:00+00:00'}, overlap))
        self.assertIsNone(sampling_calendar({'observed_at':'2026-10-10T08:30:00+00:00'}, {}))

    def test_compact_lines_keep_actions_but_move_parameters_to_details(self):
        row = dict(native_type=19, subtype=4, action='外交卡片排序', cards_raw=[26, 12, 24, 13])
        self.assertEqual(short_command(row), '外交卡排序')
        self.assertEqual(short_command(dict(native_type=20, subtype=5, target_raw=589)), '加增 武将#589')
        self.assertEqual(short_command(dict(native_type=18, subtype=0, action='步兵训练', value_raw=240)), '步兵训练')
        group = command_groups([dict(row, observed_at='2026-10-10T08:30:00+00:00')], {})[0]
        self.assertEqual(group['label'], '日期未确认')
        # Unknown native types cannot silently become military commands.
        unknown = command_groups([dict(row, native_type=999)], {})[0]
        self.assertEqual(unknown['lane'], 'unknown')

    def test_hire_line_shows_best_of_blade_half_intel_or_politics(self):
        ming = dict(native_type=20, subtype=0, personnel_reference={
            'city_name': '真定', 'result': {'name': '铭哥', 'general_id': 7}})
        pang = dict(native_type=20, subtype=0, personnel_reference={
            'city_name': '朱提', 'result': {'name': '庞媛', 'general_id': 8}})
        generals = [
            {'general_id_raw': 7, 'name': '铭哥', 'attributes': {'lead': 98, 'war': 76, 'intel': 93, 'pol': 109, 'cha': 98}},
            {'general_id_raw': 8, 'name': '庞媛', 'attributes': {'lead': 75, 'war': 99, 'intel': 73, 'pol': 54, 'cha': 82}},
        ]
        self.assertEqual(short_command(ming, generals), '录用 真定 → 铭哥(政治:109)（观测）')
        self.assertEqual(short_command(pang, generals), '录用 朱提 → 庞媛(统武:174)（观测）')
        tied = {'name': '甲', 'attributes': {'lead': 40, 'war': 40, 'intel': 40, 'pol': 10}}
        self.assertEqual(short_command(dict(native_type=20, subtype=0, personnel_reference={
            'city_name': '洛阳', 'result': {'name': '甲', 'general_id': 1}}), [dict(tied, general_id_raw=1)]),
            '录用 洛阳 → 甲(统武:80)（观测）')


if __name__ == '__main__':
    unittest.main()
