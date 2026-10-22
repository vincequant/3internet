"""Force-specific exclusion preserves opponents and immutable replay evidence."""
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'bridge')]
from game_archive import ArchiveReader, write_packed_archive
from quick_control_model import BUILD, binding
from quick_plain_training import PlainTraining
from quick_effects import SITES
from replay_modifications import record_intent, summary, registry_path, context, SIDECAR, require_training_force, label
from replay_training import export_observations
from test_game_archive import make_computer_state


def fixture(root, session='session-A'):
    states=[]
    for i in range(3):
        s=make_computer_state(i)
        s.update(build_sha256=BUILD,core_address='0x100000',
                 identity=dict(pid=10,creation_filetime=1234,path=r'C:\game\SANPK.exe'),
                 player_force_id=0, player_identity=dict(status='confirmed',force_id=0,session_id=session),
                 capture_end=(datetime.now(timezone.utc)+timedelta(seconds=i-3)).isoformat())
        states.append(s)
    archive=root/'game-archives'/session
    write_packed_archive(archive,states,simulated=False,extra_manifest={'source_id':'test'})
    manifest=json.loads((archive/'manifest.json').read_text())
    payload=dict(source_id='test',fresh=True,identity=states[-1]['identity'],state=states[-1],
                 replay_archive=dict(recording=True,directory=str(archive),match_id=manifest['match_id']))
    bound=binding(payload)
    return archive,payload,bound,dict(document=bound['core']-0x912,phase=1)


class ModificationProvenanceTests(unittest.TestCase):
    def test_auto_x3_intent_excludes_own_force_before_any_confirmed_order(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive,p,b,s=fixture(root)
            record_intent(b,s,'auto_x3',p,0,root)
            report=summary(archive,root=root)
            self.assertEqual(report['excluded_training_force_ids'],[0])
            self.assertFalse(report['exclude_entire_replay'])
            self.assertTrue(report['opponent_reference_allowed'])

    def test_force_only_export_and_copied_archive_keep_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive,p,b,s=fixture(root)
            original={n:(archive/n).read_bytes() for n in ('manifest.json','index.json','frames.jsonl')}
            record_intent(b,s,'cavalry',p,0,root)
            provenance=summary(archive,root=root)
            self.assertEqual(provenance['excluded_training_force_ids'],[0])
            self.assertFalse(provenance['exclude_entire_replay'])
            self.assertTrue(provenance['opponent_reference_allowed'])
            self.assertIn('国0',label(provenance))
            with self.assertRaisesRegex(ValueError,'排除'):require_training_force(provenance,0)
            require_training_force(provenance,1)
            with self.assertRaises(ValueError):require_training_force(provenance,None)
            # Portable sidecar still works when local registry is unavailable.
            copied=root/'copy';shutil.copytree(archive,copied)
            report=export_observations(copied,root/'opponent',force_id=1)
            self.assertEqual(report['training_force_policy']['excluded_training_force_ids'],[0])
            self.assertIn(1,report['training_force_policy']['reference_force_ids'])
            self.assertFalse(report['formal_evaluation_eligible'])
            with self.assertRaisesRegex(ValueError,'排除'):
                export_observations(copied,root/'own',force_id=0)
            self.assertFalse((root/'own').exists())
            row=json.loads((root/'opponent/observations.jsonl').read_text().splitlines()[0])
            self.assertEqual(set(row['features']),{'state_before'})
            self.assertNotIn('modification_provenance',row['features']['state_before'])
            self.assertEqual(row['training_force_policy']['excluded_training_force_ids'],[0])
            self.assertFalse(row['action_label_known'])
            for n,raw in original.items():self.assertEqual((archive/n).read_bytes(),raw)

    def test_new_game_same_process_does_not_inherit_and_unmarked_not_clean(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a,p,b,s=fixture(root)
            record_intent(b,s,'extend',p,0,root)
            other,_,_,_=fixture(root,'session-B')
            report=summary(other,root=root)
            self.assertEqual(report['excluded_training_force_ids'],[])
            self.assertFalse(report['unmarked_means_clean'])

    def test_mismatch_normal_action_and_failed_storage_prevent_marker(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a,p,b,s=fixture(root)
            for action,fid,payload in [('recruit',0,p),('alms',1,p),
                    ('bow',0,{**p,'source_id':'enemy'})]:
                with self.subTest(action=action,fid=fid), self.assertRaises(ValueError):
                    record_intent(b,s,action,payload,fid,root)
            self.assertFalse((root/'modification-records').exists())
            with patch('replay_modifications.immutable_json',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):record_intent(b,s,'alms',p,0,root)
            self.assertEqual(summary(a,root=root)['event_count'],0)

    def test_deferred_registry_marker_attaches_to_new_frames(self):
        from replay_modifications import attach_pending
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a,p,b,s=fixture(root)
            p.pop('replay_archive')
            result=record_intent(b,s,'bow',p,0,root)
            self.assertEqual(result['attached_match_ids'],[])
            self.assertEqual(summary(a,root=root)['excluded_training_force_ids'],[0])
            with ArchiveReader(a,read_only=True) as reader:
                attach_pending(a,reader.manifest,reader.load_frame(3),reader.meta(3),root)
            self.assertEqual(len(list((a/SIDECAR).glob('*.json'))),1)

    def test_last_second_intent_is_durable_without_scanning_archive(self):
        from replay_modifications import attach_pending
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a,p,b,s=fixture(root)
            original=(a/'frames.jsonl').read_bytes()
            with patch('game_archive.ArchiveReader',side_effect=AssertionError('deadline must not scan archive')):
                result=record_intent(b,s,'extend',p,0,root,attach_archives=False)
            self.assertEqual(len(list(registry_path(context(p),root).glob('*.json'))),1)
            self.assertEqual(result['attached_match_ids'],[])
            self.assertFalse((a/SIDECAR).exists())
            with ArchiveReader(a,read_only=True) as reader:
                attach_pending(a,reader.manifest,reader.load_frame(3),reader.meta(3),root)
            self.assertEqual(len(list((a/SIDECAR).glob('*.json'))),1)
            self.assertEqual((a/'frames.jsonl').read_bytes(),original)

    def test_corrupt_sidecar_is_visible_and_blocks_action_import(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a,p,b,s=fixture(root)
            record_intent(b,s,'alms',p,0,root)
            marker=next((a/SIDECAR).glob('*.json'));doc=json.loads(marker.read_text())
            doc['event']['force_id']=1;marker.write_text(json.dumps(doc))
            provenance=summary(a,root=root)
            self.assertTrue(provenance['evidence_errors'])
            with self.assertRaisesRegex(ValueError,'证据异常'):require_training_force(provenance,1)

    def test_patch_guard_failure_precedes_all_native_allocations_and_writes(self):
        from contextlib import nullcontext
        native=Mock();native.bound={'core':0x100000};native.capture.return_value=dict(view=123,document=456)
        native.number.return_value=0x100000;native.read.side_effect=lambda a,n:SITES[a]
        effect=PlainTraining(native,Mock());effect.values=Mock(return_value={'armaments':[0,0,0],'prestige':10})
        effect.patch.writer=Mock(return_value=nullcontext('handle'))
        effect.patch.frozen=Mock(return_value=nullcontext())
        effect.patch.code=Mock()
        effect.before_modify=Mock(side_effect=OSError('marker failed'))
        with patch('quick_effects.require_menu'):
            with self.assertRaises(OSError):effect.install('infantry',native.capture.return_value)
        native.k.VirtualAllocEx.assert_not_called();effect.patch.code.assert_not_called()


if __name__=='__main__':unittest.main()
