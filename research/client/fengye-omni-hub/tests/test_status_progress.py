import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fengye_source import one_click_progress, recount_patches, status_items


def _view(patches, skip):
    return {
        'opening_skip': skip,
        'session': {'room_name': '房', 'ghost_registered': True, 'alive': True},
        'status': {
            'present': True,
            'age': 1,
            'line': '多线3（备用）',
            'link': {'connected': True},
            'hide': {'verified': True},
            'patches': patches,
        },
    }


class SkipCountTests(unittest.TestCase):
    def test_configured_skip_counts_as_installed(self):
        patches = {
            'ready': False,
            'opening': {'ok': 16, 'total': 18, 'missing': ['myforce-a', 'myforce-b']},
            'guard': {'ok': 21, 'total': 21, 'missing': []},
            'suppress': {'ok': 2, 'total': 2, 'missing': []},
        }
        items = status_items(_view(patches, ['myforce-a', 'myforce-b']), now=100)
        labels = [item['label'] for item in items]
        self.assertIn('補丁已裝好', labels)
        self.assertNotIn('補丁還沒裝齊', labels)
        self.assertNotIn('還不能按「開始」', labels)
        detail = next(item['detail'] for item in items if item['label'] == '補丁已裝好')
        self.assertIn('守衛 18/18（2 站依設定跳過）', detail)

    def test_real_miss_still_blocks(self):
        patches = {
            'ready': False,
            'opening': {'ok': 15, 'total': 18, 'missing': ['myforce-a', 'myforce-b', 'round-city']},
            'guard': {'ok': 21, 'total': 21, 'missing': []},
            'suppress': {'ok': 2, 'total': 2, 'missing': []},
        }
        updated = recount_patches(patches, ['myforce-a', 'myforce-b'])
        self.assertEqual(updated['opening']['ok'], 17)
        self.assertEqual(updated['opening']['missing'], ['round-city'])
        self.assertFalse(updated.get('ready'))

    def test_does_not_add_skipped_twice(self):
        patches = {
            'ready': True,
            'opening': {'ok': 18, 'total': 18, 'missing': [], 'skipped': ['myforce-a', 'myforce-b']},
            'guard': {'ok': 21, 'total': 21, 'missing': []},
            'suppress': {'ok': 2, 'total': 2, 'missing': []},
        }
        updated = recount_patches(patches, ['myforce-a', 'myforce-b'])
        self.assertEqual(updated['opening']['ok'], 18)


class ProgressTests(unittest.TestCase):
    def test_done_is_100(self):
        got = one_click_progress({'step': 'done', 'status': 'ok'}, '占席')
        self.assertEqual(got['percent'], 100)
        self.assertFalse(got['failed'])

    def test_stages_follow_the_log(self):
        self.assertEqual(one_click_progress({'step': 'launcher', 'status': 'running'}, '')['percent'], 8)
        waiting = one_click_progress({'step': 'launcher', 'status': 'running'}, '已拉起；等待三个『游戏选择』')
        self.assertEqual(waiting['label'], '等遊戲選擇')
        self.assertEqual(waiting['percent'], 22)
        arrived = one_click_progress({'step': 'launcher', 'status': 'running'}, '三台都到『游戏选择』')
        self.assertEqual(arrived['percent'], 38)
        patching = one_click_progress({'step': 'stealth', 'status': 'running'}, '6c) 三台开局守卫')
        self.assertEqual(patching['label'], '補丁')
        seated = one_click_progress({'step': 'stealth', 'status': 'running'}, '7.5) 风夜先占空席')
        self.assertEqual(seated['percent'], 92)

    def test_early_roster_line_is_not_the_hide_step(self):
        got = one_click_progress(
            {'step': 'room', 'status': 'running'},
            '未见幽灵行（继续尝试补丁/摘席）')
        self.assertEqual(got['percent'], 52)
        self.assertEqual(got['label'], '建房／進房')

    def test_failure_keeps_the_stage(self):
        got = one_click_progress({'step': 'stealth', 'status': 'failed'}, '6c) 三台开局守卫')
        self.assertTrue(got['failed'])
        self.assertEqual(got['percent'], 68)


if __name__ == '__main__':
    unittest.main()
