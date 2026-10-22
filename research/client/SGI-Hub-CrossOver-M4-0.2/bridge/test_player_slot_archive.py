"""Identity observations survive replay deltas without leaking later names."""
import copy
from pathlib import Path
import tempfile
import unittest

from game_archive import ArchiveReader, build_demo_state, write_packed_archive


class PlayerSlotArchiveTests(unittest.TestCase):
    def test_identity_changes_and_missing_names_follow_replay_cursor(self):
        states = [build_demo_state(i) for i in range(1, 4)]
        names = ('测试玩家甲', None, '测试玩家乙')
        for state, name in zip(states, names):
            state['player_slots_layout'] = {'status': 'test_fixture', 'ansi_code_page': 936}
            state['player_slots'] = [{
                'slot': 0, 'force_id': 7, 'source_metadata': 42,
                'nickname': name,
                'raw_hex': name.encode('gbk').hex() if name else '',
                'status': 'confirmed' if name else 'unknown',
            }]
        before = copy.deepcopy(states)
        with tempfile.TemporaryDirectory() as folder:
            archive = write_packed_archive(Path(folder) / 'synthetic-test-only', states,
                                           simulated=True, keyframe_every=10)
            with ArchiveReader(archive, read_only=True) as reader:
                self.assertEqual([x['kind'] for x in reader.frames], ['keyframe', 'delta', 'delta'])
                for seq in (3, 1, 2, 1):
                    recovered = reader.load_frame(seq)
                    self.assertEqual(recovered['player_slots'], states[seq - 1]['player_slots'])
                    self.assertEqual(recovered['player_slots_layout'], states[seq - 1]['player_slots_layout'])
        self.assertEqual(states, before)


if __name__ == '__main__':
    unittest.main()
