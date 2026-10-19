#!/usr/bin/env python3
"""Tests for the P57 in-client cmd9 (ready) agent.

The agent is a one-shot: on a trigger file it submits the 36-byte
CSanInetCmdObject(kind=9, a=1) through the verified reliable path
(0x4C80 GetHostOrSelfID -> 0x4B60 submit) and writes an 'SHG9' receipt.

Golden payload comes from p30_ready.CMD9 (the blob that run-091557 used
live to take the host out of "waiting for player" into cmd10).

Run:  ~/.venvs/fengye/bin/python -m unittest test_p57_cmd9 -v
"""
from __future__ import annotations

import os
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import p30_ready  # noqa: E402
from test_p51_shadow import OWN, TARGET, TICK, run_payload  # noqa: E402

BUILD = Path(os.environ.get(
    'P57_BUILD_DIR',
    Path(__file__).resolve().parents[2] / 'protocol-archive/evidence/p57-cmd9-agent-20261019/build'))
AGENT = BUILD / 'agent_cmd9.bin'
CMD9 = p30_ready.CMD9


class TestCmd9Agent(unittest.TestCase):
    def test_golden_payload_shape(self):
        self.assertEqual(len(CMD9), 36)
        self.assertEqual(CMD9[:2], b'\xff\xff')
        self.assertEqual(CMD9[6:23], b'CSanInetCmdObject')
        self.assertEqual(struct.unpack_from('<III', CMD9, 23), (9, 1, 0))
        self.assertEqual(CMD9[35], 0)

    def test_build_present(self):
        self.assertTrue(AGENT.exists(), 'run p51_shadow_agent_build.py first')

    def test_one_shot_submit(self):
        log = run_payload(AGENT)
        self.assertIsNone(log['error'])
        self.assertEqual(len(log['c60']), 1, 'exactly one reliable submit')
        call = log['c60'][0]
        self.assertEqual(call['netobj'], 0x300000)
        self.assertEqual(call['target'], TARGET, 'target must be the host id, never self')
        self.assertEqual(call['len'], 36)
        self.assertEqual(call['body'], CMD9, 'wire bytes must equal the live-verified cmd9 blob')
        self.assertEqual(log['c80'], 1)
        self.assertEqual(len(log['wfa']), 1)
        self.assertEqual(log['wfa'][0], struct.pack('<IIIIII', 0x39474853, 1, OWN, TARGET, TICK, 0))
        self.assertTrue(log['cfa'] and log['cfa'][0].endswith('receipt'))
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 1, 'once-only flag set')

    def test_no_trigger_no_send(self):
        log = run_payload(AGENT, trigger=False)
        self.assertIsNone(log['error'])
        self.assertEqual(log['c60'], [])
        self.assertEqual(log['c80'], 0)
        self.assertEqual(struct.unpack_from('<I', log['blob'], 4)[0], 0)

    def test_zero_own_id_no_send(self):
        log = run_payload(AGENT, own=0)
        self.assertIsNone(log['error'])
        self.assertEqual(log['c60'], [])

    def test_host_is_self_no_send(self):
        log = run_payload(AGENT, c80_is_own=True)
        self.assertIsNone(log['error'])
        self.assertEqual(log['c60'], [])


if __name__ == '__main__':
    unittest.main()
