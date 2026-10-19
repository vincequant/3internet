import copy
import hashlib
import json
from pathlib import Path
import struct
import unittest
from p28_wire import inspect_packet
from p30_ready import Preparation, CMD9, checksum


class ReadyTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2]/'protocol-archive/evidence/p28-window-receive-20261015/run-090744/p28_live.jsonl'
        r = next(json.loads(l) for l in path.read_text().splitlines() if json.loads(l)['ev'] == 'received_packet')
        data = bytes.fromhex(r['raw_hex'])
        self.initial = inspect_packet(struct.pack('<III', r['sender'], r['target'], len(data))+data, 4)
        self.state = Preparation(r['target'], r['sender'], '风夜', lambda n: (b'123456789', 'fixture'))

    def cmd(self, cmd, a=0, b=0):
        return {'sender': self.state.host_id, 'object': {'class_name': 'CSanInetCmdObject',
                'cmd': cmd, 'a': a, 'b': b, 'derived_tail_length': 0}}

    def start(self):
        packet = copy.deepcopy(self.initial)
        packet['object']['cmd'] = 7
        return packet

    def test_cmd9_bytes_match_frozen_native_template(self):
        self.assertEqual(hashlib.sha256(CMD9).hexdigest(), '6841b7aa7f5148621004a67e94cf049ee51c657867ece0b21679db15bcf48664')

    def test_full_initial_then_full_cmd7_only_once(self):
        self.assertEqual(self.state.accept(self.start())['ev'], 'prep_blocked')
        self.assertEqual(self.state.accept(self.initial)['ev'], 'snapshot_stored')
        self.assertEqual(self.state.accept(self.start())['ev'], 'ready_once')
        self.assertEqual(self.state.accept(self.start())['ev'], 'prep_blocked')

    def test_malformed_or_wrong_identity_blocks(self):
        self.state.accept(self.initial)
        p = self.start()
        p['snapshot']['rows'][1]['id'] += 1
        self.assertEqual(self.state.accept(p)['ev'], 'prep_blocked')
        self.assertFalse(self.state.sent)

    def test_scenario_must_match_native_checksum(self):
        self.assertEqual(checksum(b'123456789'), 0x906e)
        self.state.accept(self.initial)
        receipt = self.state.accept(self.cmd(6, 1, 123))
        self.assertFalse(receipt['matched'])
        self.assertEqual(self.state.accept(self.start())['ev'], 'prep_blocked')

    def test_valid_scenario_held_in_memory(self):
        self.state.accept(self.initial)
        self.assertTrue(self.state.accept(self.cmd(6, 1, 0x906e))['matched'])
        self.assertEqual(self.state.scenario, b'123456789')
        self.assertEqual(self.state.accept(self.start())['ev'], 'ready_once')

    def test_nonhost_and_unsupported_archive_never_ready(self):
        self.state.accept(self.initial)
        p = self.start(); p['sender'] += 1
        self.assertEqual(self.state.accept(p)['ev'], 'prep_ignored')
        self.state.accept(self.cmd(8))
        self.assertEqual(self.state.accept(self.start())['ev'], 'prep_ignored')


if __name__ == '__main__':
    unittest.main()
