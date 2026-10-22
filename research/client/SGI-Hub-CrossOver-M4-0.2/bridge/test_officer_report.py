import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'), str(Path(__file__).resolve().parent)]

from officer_report import own_city_reports, parse_blade_floor, qualifying_officers, report_line


def officer(gid, city_id, name, lead, war, status=1, owner=65535):
    return {
        'general_id_raw': gid, 'name': name, 'status_code': status, 'owner_raw': owner,
        'location_city_id': city_id,
        'attributes': {'lead': lead, 'war': war, 'intel': 40, 'pol': 40, 'cha': 40},
    }


def state():
    return {
        'player_force_id': 1,
        'player_identity': {'status': 'confirmed', 'force_id': 1},
        'entities': {
            'lords': [{'force_id': 1, 'name': '我'}, {'force_id': 2, 'name': '敌'}],
            'cities_and_barriers': [
                {'city_id': 1, 'name': '卢江', 'type': 'city', 'owner_raw': 1},
                {'city_id': 2, 'name': '建业', 'type': 'city', 'owner_raw': 2},
                {'city_id': 3, 'name': '武关', 'type': 'barrier', 'owner_raw': 1},
                {'city_id': 4, 'name': '柴桑', 'type': 'city', 'owner_raw': 1},
            ],
            'generals': [
                officer(1, 1, '白起', 90, 81),
                officer(2, 1, '霍去病', 100, 90),
                officer(3, 1, '平常', 80, 80),
                officer(4, 1, '刚好', 90, 80),
                officer(5, 1, '小将', 50, 40),
                officer(6, 1, '已仕', 100, 100, status=0, owner=1),
                officer(7, 2, '敌城名将', 100, 100),
                officer(8, 3, '关隘名将', 100, 100),
                officer(9, 4, '低统武', 70, 70),
            ],
        },
    }


class OfficerReportTests(unittest.TestCase):
    def test_line_matches_teammate_format(self):
        self.assertEqual(report_line('卢江', [{'name': '白起'}, {'name': '霍去病'}], 5), '卢江 白起 霍去病  2/5')

    def test_own_cities_only_above_170(self):
        lines = own_city_reports(state())
        self.assertEqual(lines, ['卢江 霍去病 白起  2/5'])

    def test_floor_can_be_raised(self):
        self.assertEqual(own_city_reports(state(), 180), ['卢江 霍去病  1/5'])
        self.assertIsNone(parse_blade_floor(''))
        self.assertIsNone(parse_blade_floor('  '))
        self.assertEqual(parse_blade_floor('180'), 180)
        self.assertIs(parse_blade_floor('甲'), False)
        names = [row['name'] for row in qualifying_officers([
            officer(1, 1, '白起', 90, 81), officer(3, 1, '平常', 80, 80),
        ], None)]
        self.assertEqual(names, ['白起', '平常'])

    def test_exact_170_stays_out(self):
        picked = qualifying_officers([officer(4, 1, '刚好', 90, 80)])
        self.assertEqual(picked, [])

    def test_unconfirmed_player_reports_nothing(self):
        doc = state()
        doc['player_identity'] = {'status': 'unconfirmed', 'force_id': 1}
        self.assertIsNone(own_city_reports(doc))

    def test_tab_is_under_officer_pages(self):
        hub = (Path(__file__).resolve().parents[1] / 'app' / 'omni_window.py').read_text(encoding='utf-8')
        self.assertIn("self.global_book.add(self.officer_report,text='报将')", hub)
        self.assertLess(hub.index("text='武将资料'"), hub.index("text='报将'"))
        self.assertIn('self.officer_report.refresh()', hub)
        report = (Path(__file__).resolve().parents[1] / 'app' / 'officer_report.py').read_text(encoding='utf-8')
        self.assertIn("text='复制'", report)
        self.assertIn('pbcopy', report)
        self.assertIn('win_clipboard_once.py', report)
