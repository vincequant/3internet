import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'), str(Path(__file__).resolve().parent)]
from officer_reference import SPELLING, officer_metrics, website_compatibility
from officer_sortie import roster_skill_flags


def officer(name, stats):
    lead, war, intel, pol, cha = stats
    return {'name': name, 'attributes': {'lead': lead, 'war': war, 'intel': intel, 'pol': pol, 'cha': cha}}


class SpellingMatch(unittest.TestCase):
    def test_game_luyunxun_shows_ambush_when_stats_match_website(self):
        row = officer('陆云讯', (98, 80, 89, 98, 87))
        metrics = officer_metrics(row)
        self.assertIn('埋伏', metrics['skills'].split(' / '))
        self.assertIsNotNone(metrics['current_diplomacy'])
        self.assertIn('差一字', metrics['match'])
        self.assertTrue(roster_skill_flags(row)['ambush'])
        self.assertEqual(website_compatibility(row), 60)

    def test_wrong_stats_do_not_borrow_the_near_name(self):
        row = officer('陆云讯', (98, 80, 89, 98, 1))
        metrics = officer_metrics(row)
        self.assertEqual(metrics['skills'], '未匹配')
        self.assertIsNone(metrics['current_diplomacy'])
        self.assertFalse(roster_skill_flags(row)['ambush'])
        self.assertIsNone(website_compatibility(row))

    def test_same_stats_do_not_bind_a_different_name(self):
        row = officer('秦王', (100, 70, 91, 110, 80))
        self.assertEqual(officer_metrics(row)['skills'], '未匹配')
        self.assertFalse(roster_skill_flags(row)['ambush'])

    def test_exact_luxun_still_matches_by_name(self):
        row = officer('陆逊', (98, 73, 96, 91, 88))
        metrics = officer_metrics(row)
        self.assertIn('埋伏', metrics['skills'].split(' / '))
        self.assertIn('同名唯一', metrics['match'])

    def test_listed_spellings_match_only_with_website_stats(self):
        from officer_reference import INDEX
        for game_name, site_name in SPELLING.items():
            ref = INDEX[site_name][0]
            stats = tuple(ref['stats'][key] for key in ('leadership', 'power', 'intelligence', 'politics', 'charm'))
            self.assertIsNotNone(officer_metrics(officer(game_name, stats))['current_diplomacy'], game_name)
            shifted = list(stats)
            shifted[-1] = 0 if shifted[-1] else 1
            self.assertIsNone(officer_metrics(officer(game_name, tuple(shifted)))['current_diplomacy'], game_name)
