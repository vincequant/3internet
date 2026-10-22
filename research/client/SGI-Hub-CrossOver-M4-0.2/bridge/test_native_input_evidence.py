import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native_input_evidence import InputEvidenceReader, input_line


def fixture():
    process=dict(pid=684,creation_filetime=12345,path=r'C:\sgi\SANPK.exe')
    ctx=dict(source_id='MAC',process=process,game_build='abc',core_address='0x100000',
             player_session_id='session-one',force_id=16,force_name='代')
    bound=dict(pid=684,created=12345,image=process['path'],build='abc',core=0x100000,source_id='MAC')
    payload=dict(fresh=True,source_id='MAC',identity=process,state=dict(build_sha256='abc',core_address='0x100000',
        player_force_id=16,player_identity=dict(status='confirmed',force_id=16,session_id='session-one'),
        entities=dict(lords=[dict(force_id=16,name='代')])))
    intent=dict(ctx,action='auto_x3',stage='before_mutation_intent')
    operand=dict(kind='auto_x3_operand',at='2026-10-10T08:29:37+00:00',action='infantry',
        operand_before=80,operand_after=240,new_hits=1,omitted_intermediate_operands=0,operand_verified=True)
    return payload,[dict(kind='bound',bound=bound),dict(kind='modification_recorded',event=intent)],operand


class InputEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.path=self.folder/'20261010-012846-33270.jsonl'
        self.reader=InputEvidenceReader(self.folder);self.payload,self.prefix,self.operand=fixture()

    def write(self, rows, mode='wb'):
        with self.path.open(mode) as file:
            for row in rows:file.write(json.dumps(row).encode()+b'\n')

    def test_receipt_keeps_original_line_hash_and_unknown_commit_without_rewriting_log(self):
        self.write(self.prefix+[self.operand]);original=self.path.read_bytes()
        evidence=self.reader.read(self.payload);row=evidence['rows'][0]
        source=original[row['source_byte_offset']:].splitlines(keepends=True)[0]
        self.assertEqual(hashlib.sha256(source).hexdigest(),row['source_line_sha256'])
        self.assertEqual(row['scope']['force_id'],16);self.assertIsNone(row['command_committed'])
        self.assertFalse(row['server_result_verified']);self.assertFalse(evidence['complete_command_stream'])
        self.assertIn('80→240',input_line(row));self.assertIn('未确认',input_line(row))
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(self.reader.read(self.payload)['rows'],evidence['rows'])

    def test_source_process_build_core_session_and_force_cannot_leak(self):
        self.write(self.prefix+[self.operand])
        for mutate in (
            lambda p:p.update(source_id='OTHER'),
            lambda p:p['identity'].update(creation_filetime=12346),
            lambda p:p['identity'].update(path=r'C:\other.exe'),
            lambda p:p['state'].update(build_sha256='other'),
            lambda p:p['state'].update(core_address='0x200000'),
            lambda p:p['state']['player_identity'].update(session_id='session-two'),
            lambda p:(p['state'].update(player_force_id=17),p['state']['player_identity'].update(force_id=17)),
        ):
            other=copy.deepcopy(self.payload);mutate(other)
            self.assertFalse(self.reader.read(other)['rows'])
        self.assertEqual(len(self.reader.read(self.payload)['rows']),1)

    def test_bound_mismatch_missing_intent_or_state_difference_are_not_inputs(self):
        self.write([self.operand,dict(kind='result',action='inspect',result={'state':{'orders_used':3}})])
        self.assertFalse(self.reader.read(self.payload)['rows'])
        prefix=copy.deepcopy(self.prefix);prefix[0]['bound']['source_id']='OTHER'
        self.write(prefix+[self.operand]);self.reader=InputEvidenceReader(self.folder)
        self.assertFalse(self.reader.read(self.payload)['rows'])

    def test_partial_append_and_rebinding_do_not_duplicate_or_reattribute(self):
        self.write(self.prefix);raw=json.dumps(self.operand).encode()
        with self.path.open('ab') as file:file.write(raw[:30])
        self.assertFalse(self.reader.read(self.payload)['rows'])
        with self.path.open('ab') as file:file.write(raw[30:]+b'\n')
        self.assertEqual(len(self.reader.read(self.payload)['rows']),1)
        changed=copy.deepcopy(self.prefix[0]);changed['bound']['created']+=1
        self.write([changed,self.operand],'ab')
        self.assertEqual(len(self.reader.read(self.payload)['rows']),1)

    def test_omitted_operands_are_disclosed_and_alms_uses_actual_gain(self):
        alms=dict(self.operand,action='alms',operand_before=4,operand_after=22,new_hits=3,omitted_intermediate_operands=2)
        self.write(self.prefix+[alms]);evidence=self.reader.read(self.payload)
        self.assertEqual(len(evidence['rows']),1)
        self.assertIn('9→27',input_line(evidence['rows'][0]));self.assertIn('另有2次',input_line(evidence['rows'][0]))

    def test_invalid_values_untrusted_verification_and_remote_or_stale_views_are_empty(self):
        bad=[dict(self.operand,operand_after=241),dict(self.operand,operand_verified=False),
             dict(self.operand,operand_before=True),dict(self.operand,at='invalid'),
             dict(self.operand,new_hits=2,omitted_intermediate_operands=0)]
        self.write(self.prefix+bad);self.assertFalse(self.reader.read(self.payload)['rows'])
        self.write(self.prefix+[self.operand]);self.reader=InputEvidenceReader(self.folder)
        self.assertFalse(self.reader.read(self.payload,remote=True)['rows'])
        self.assertFalse(self.reader.read(dict(self.payload,fresh=False))['rows'])

    def test_bounded_retention_reports_omissions(self):
        self.write(self.prefix+[self.operand]*5)
        with patch('native_input_evidence.MAX_ROWS',2):
            evidence=self.reader.read(self.payload)
        self.assertEqual(len(evidence['rows']),2);self.assertEqual(evidence['omitted_rows'],3)

