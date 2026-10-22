import copy
import unittest
from types import SimpleNamespace
from test_preparation import state
from unit_target_attack import BUILD, LIFETIME_HOTFIX_BUILD, DIAGNOSTIC_HOTFIX_BUILD, FINALIZE_HOTFIX_BUILD, NETWORK_HOTFIX_BUILD, DESTRUCTOR_HOTFIX_BUILD, enrich_targets, supported_combat_build
from preparation_model import recommend
from military_summary import MilitarySummary


class Cell:
    def config(self, **kw):
        self.text = kw['text']


class HotfixCombat(unittest.TestCase):
    def test_recommendation_matches_original(self):
        original = state()
        patched = copy.deepcopy(original)
        patched['build_sha256'] = LIFETIME_HOTFIX_BUILD
        self.assertTrue(recommend(patched, target=0, leader_id=1)['rows'])
        self.assertEqual(recommend(original, target=0, leader_id=1), recommend(patched, target=0, leader_id=1))

    def test_attack_and_summary_all_builds(self):
        for sha, supported in ((BUILD, True), (LIFETIME_HOTFIX_BUILD, True), (DIAGNOSTIC_HOTFIX_BUILD, True), (FINALIZE_HOTFIX_BUILD, True), (NETWORK_HOTFIX_BUILD, True), (DESTRUCTOR_HOTFIX_BUILD, True), ('unknown', False), (None, False)):
            with self.subTest(sha=sha):
                s = state(); s['build_sha256'] = sha
                self.assertEqual(supported_combat_build(sha), supported)
                unit = dict(unit_kind='步兵', size_index=0, training_degree=93, basic_combat_power=90)
                s['entities']['field_units'] = [unit]
                enrich_targets(s)
                self.assertEqual(bool(unit['target_attack_components']), supported)
                panel = SimpleNamespace(tiles={k: [Cell() for _ in range(5)] for k in ('infantry', 'cavalry', 'bow')})
                MilitarySummary.update_force(panel, s['entities']['lords'][0], s)
                self.assertEqual(panel.tiles['infantry'][4].text, '90%')
                if not supported:
                    self.assertFalse(recommend(s)['rows'])


if __name__ == '__main__':
    unittest.main()
