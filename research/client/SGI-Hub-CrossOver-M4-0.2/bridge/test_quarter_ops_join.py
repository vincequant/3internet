import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


class QuarterOpsJoinImport(unittest.TestCase):
    def test_join_helpers_are_module_globals(self):
        import quarter_ops_panel as panel
        officer = {'name': 'SGI测试将'}
        self.assertEqual(panel.officer_event_text(officer, '洛阳', '主动加入'), '加入 SGI测试将：洛阳')
        self.assertEqual(panel.hire_command_text(officer, '洛阳'), '录用 SGI测试将：洛阳')
        self.assertTrue(callable(panel.QuarterOpsPanel._officer_chip))
