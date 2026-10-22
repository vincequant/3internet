import base64
import copy
import json
import unittest
from pathlib import Path

from command_transport import SourceCommandExporter, import_commands, MAX_TRANSFER
from command_display import command_groups
from test_command_display import window
import test_native_command_evidence as native_tests


class CommandTransportTests(unittest.TestCase):
    def setUp(self):
        fixture=native_tests.CommandEvidenceTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f=fixture;self.payload=fixture.payload
        self.payload['state']['history']={'quarters':[window(0,'09:00:00','09:10:00')]}
        fixture.write([fixture.event()])
        self.exporter=SourceCommandExporter(fixture.root)
        self.wire=self.exporter.attach(self.payload)

    def test_actual_original_lines_roundtrip_without_local_journals_or_training_claims(self):
        result=import_commands(self.wire)
        self.assertEqual(result['status'],'partial_native_queue_evidence')
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(command_groups(result['rows'],{})[0]['label'],'200年春')
        row=result['rows'][0]
        self.assertEqual(row['raw_hex'],native_tests.packet().hex())
        self.assertIsNone(row['game_quarter']);self.assertIsNone(row['match_id'])
        self.assertFalse(row['action_training_eligible']);self.assertFalse(result['complete_command_stream'])
        self.assertNotIn('source_line_b64',row)
        self.assertNotIn('native_command_transfer',self.payload['state'])
        self.assertTrue(self.f.reader.read(self.wire,remote=True)['rows'])

    def test_wrong_source_process_build_line_hash_operands_and_provenance_fail_closed(self):
        changes=[lambda p:p.update(source_id='OTHER'),
                 lambda p:p['identity'].update(creation_filetime=99),
                 lambda p:p['state']['native_command_transfer']['rows'][0].update(action='伪造'),
                 lambda p:p['state']['native_command_transfer']['rows'][0].update(source_line_sha256='bad'),
                 lambda p:p['state']['native_command_transfer']['rows'][0].update(source_file='../secret'),
                 lambda p:p['state']['native_command_transfer']['rows'][0].update(source_line_b64='bad!'),
                 lambda p:p['state']['native_command_transfer'].update(complete_command_stream=True)]
        for change in changes:
            p=copy.deepcopy(self.wire);change(p)
            result=import_commands(p)
            self.assertFalse(result['rows']);self.assertEqual(result['status'],'remote_invalid')

    def test_missing_or_stale_source_has_explicit_status_never_local_fallback(self):
        self.assertEqual(import_commands(self.payload)['status'],'remote_not_imported')
        stale=dict(self.wire,fresh=False)
        self.assertEqual(import_commands(stale)['status'],'remote_unavailable')
        self.assertNotIn('native_command_transfer',self.exporter.attach(dict(self.payload,fresh=False))['state'])
        bad=copy.deepcopy(self.wire);bad['state']['native_command_transfer']['rows']*=513
        self.assertEqual(import_commands(bad)['status'],'remote_invalid')
        bad=copy.deepcopy(self.wire);bad['state']['native_command_transfer']['padding']='x'*MAX_TRANSFER
        self.assertEqual(import_commands(bad)['status'],'remote_invalid')

    def test_export_rejects_original_replacement_and_does_not_change_journal(self):
        original=self.f.path.read_bytes()
        self.exporter.export(self.payload)
        self.assertEqual(self.f.path.read_bytes(),original)
        self.f.path.write_bytes(original.replace(b'"metadata_raw": 45',b'"metadata_raw": 46'))
        result=self.exporter.export(self.payload)
        self.assertFalse(result['rows'])
        self.assertGreater(result['errors'],0)

    def test_exporter_keeps_known_calendars_after_history_disappears(self):
        payload=copy.deepcopy(self.payload);payload['state'].pop('history')
        result=import_commands(self.exporter.attach(payload))
        self.assertEqual(command_groups(result['rows'],{})[0]['label'],'200年春')


if __name__=='__main__':unittest.main()
