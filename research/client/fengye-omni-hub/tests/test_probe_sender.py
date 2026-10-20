import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import probe_sender


class RecordTests(unittest.TestCase):
    def test_build_record_packs_coords_and_fields(self):
        rec = probe_sender.build_record({'preset': 'build', 'actor': 3, 'build_type': 8,
                                          'city': 6, 'x': 79, 'y': 49, 'extra': 2000})
        self.assertEqual(rec, {'actor': 3, 'parameter': 8, 'value': 6, 'extra': 2000,
                               'subtype': 4, 'operand': (49 << 16) | 79})

    def test_build_record_train(self):
        rec = probe_sender.build_record({'preset': 'train', 'actor': 3, 'troop': 1,
                                          'value': 75, 'extra': 0})
        self.assertEqual(rec['subtype'], 0)
        self.assertEqual(rec['parameter'], 1)
        self.assertEqual(rec['operand'], 0)

    def test_unknown_preset_rejected(self):
        with self.assertRaises(ValueError):
            probe_sender.build_record({'preset': 'personnel', 'actor': 3})


class SenderTests(unittest.TestCase):
    def test_send_writes_request_and_reads_result(self):
        with tempfile.TemporaryDirectory() as d:
            sender = probe_sender.ProbeSender(d, 'Z:\\x', lambda *a: '', timeout=3)
            seen = {}

            def fake_probe():
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if sender.control.exists():
                        req = json.loads(sender.control.read_text())
                        seen.update(req)
                        sender.result.write_text(json.dumps(
                            {'id': req['id'], 'op': 'd5', 'rc': 1, 'raw_rc': 1, 'target': 42}))
                        return
                    time.sleep(0.02)

            t = threading.Thread(target=fake_probe)
            t.start()
            res = sender.send({'actor': 3, 'parameter': 8, 'value': 6, 'extra': 2000,
                               'subtype': 4, 'operand': (49 << 16) | 79})
            t.join(3)
            self.assertTrue(res['ok'])
            self.assertEqual(res['raw_rc'], 1)
            self.assertEqual(res['target'], 42)
            self.assertEqual(seen['op'], 'd5')
            self.assertEqual(seen['record']['operand'], (49 << 16) | 79)

    def test_arm_writes_p40_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            sender = probe_sender.ProbeSender(d, 'Z:\\x', lambda *a: '')
            sender.arm(11, 22, now=1000.0)
            receipt = json.loads(sender.auth.read_text())
            self.assertEqual(receipt['contract'], 'P40')
            self.assertTrue(receipt['enable_d5'])
            self.assertEqual((receipt['own_id'], receipt['host_id']), (11, 22))
            self.assertEqual(receipt['observed_wall'], 1000.0)

    def test_timeout_is_reported_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            sender = probe_sender.ProbeSender(d, 'Z:\\x', lambda *a: '', timeout=0.3, poll=0.05)
            res = sender.send({'actor': 3})
            self.assertFalse(res['ok'])
            self.assertEqual(res['error'], 'probe_control_timeout')


if __name__ == '__main__':
    unittest.main()
