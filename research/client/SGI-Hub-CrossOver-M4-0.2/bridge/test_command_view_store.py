import json
import sys
import unittest
from pathlib import Path

from command_display import command_groups
from command_view_store import CommandViewStore, _digest
from test_command_display import window
import test_native_command_evidence as native_tests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))


class CommandViewStoreTests(unittest.TestCase):
    def setUp(self):
        fixture = native_tests.CommandEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        fixture.write([fixture.event()])
        self.payload = fixture.payload
        self.payload['state']['history'] = {'quarters': [window(0,'09:00:00','09:10:00')]}
        self.payload['state']['snapshot_id'] = 'source-frame'
        self.commands = fixture.reader.read(self.payload)
        self.store = CommandViewStore(fixture.root)

    def test_disconnect_preserves_sampling_date_but_revokes_live_identity_and_history(self):
        from portable_client import invalidate_player
        state = dict(self.payload['state'], native_command_evidence=self.commands)
        stale = invalidate_player(state)
        self.assertNotIn('history',stale)
        self.assertIsNone(stale['player_force_id'])
        stale = invalidate_player(stale)
        groups = command_groups(stale['native_command_evidence']['rows'],{})
        self.assertEqual(groups[0]['label'],'200年春')
        self.assertNotIn('sampling_calendar',self.commands['rows'][0])
        self.assertIsNone(groups[0]['rows'][0]['game_quarter'])
        self.assertFalse(groups[0]['rows'][0]['action_training_eligible'])

    def test_offline_restart_restores_dates_from_hash_checked_original_packets(self):
        original = self.fixture.path.read_bytes()
        self.store.remember(self.payload,self.commands)
        restored = CommandViewStore(self.fixture.root).load('MAC')
        self.assertTrue(restored['retained_only'])
        self.assertEqual(restored['native_command_evidence']['capture_status']['phase'],'waiting')
        groups = command_groups(restored['native_command_evidence']['rows'],{})
        self.assertEqual(groups[0]['label'],'200年春')
        self.assertEqual(self.fixture.path.read_bytes(),original)
        self.assertNotIn('state',restored)
        self.assertNotIn('player_identity',restored)

    def test_source_remote_and_corrupt_originals_cannot_restore_cache(self):
        self.store.remember(self.payload,self.commands)
        self.assertIsNone(CommandViewStore(self.fixture.root).load('OTHER'))
        self.assertIsNone(CommandViewStore(self.fixture.root).load('MAC',remote=True))
        self.fixture.path.write_bytes(b'corrupt original\n')
        self.assertIsNone(CommandViewStore(self.fixture.root).load('MAC'))

    def test_tampered_cache_cannot_relabel_a_packet_or_change_its_source(self):
        self.store.remember(self.payload,self.commands)
        path = self.store.path('MAC'); original = path.read_bytes()
        wrapper=json.loads(original)
        wrapper['data']['native_command_evidence']['rows'][0]['action']='伪造命令'
        wrapper['sha256']=_digest(wrapper['data'])
        path.write_text(json.dumps(wrapper))
        self.assertIsNone(CommandViewStore(self.fixture.root).load('MAC'))
        path.write_bytes(original)
        wrapper=json.loads(original);wrapper['data']['binding']['source_id']='OTHER'
        wrapper['sha256']=_digest(wrapper['data']);path.write_text(json.dumps(wrapper))
        self.assertIsNone(CommandViewStore(self.fixture.root).load('MAC'))

    def test_legacy_trade_labels_redecode_original_bytes_without_losing_dates(self):
        from command_effects import valid_change
        from command_phase_values import retain_phase_values, settlement_sample
        from copy import deepcopy
        self.fixture.write([self.fixture.event(native_tests.packet(subtype=4,parameter=6)),
                            self.fixture.event(native_tests.packet(subtype=3,parameter=1),pointer=0x333333)])
        original=self.fixture.path.read_bytes()
        commands=native_tests.CommandEvidenceReader(self.fixture.root).read(self.payload)
        self.store.remember(self.payload,commands)
        path=self.store.path('MAC');wrapper=json.loads(path.read_bytes())
        data=wrapper['data'];rows=data['native_command_evidence']['rows']
        before=dict(phase_candidate=dict(year_u16=200,season_u16=0,turn_u16=1),capture_end='2026-10-10T09:09:56+00:00',
                    entities={'lords':[dict(force_id=16,gold=5000,rice=10000)]})
        after=deepcopy(before);after.update(capture_end='2026-10-10T09:10:00+00:00',
                                          phase_candidate=dict(year_u16=200,season_u16=0,turn_u16=2))
        after['entities']['lords'][0].update(gold=3000,rice=12000)
        w=self.payload['state']['history']['quarters'][0]
        w['phase']['turn_u16']=1
        w.update(phase_after=after['phase_candidate'],settlement_sample=settlement_sample(before,after))
        # Reproduce the pre-312 interpretation and its otherwise-valid rice
        # correlation. This is derived-cache migration, never raw rewriting.
        rows[0]['action']='买米';rows[0].pop('target_xy_raw');rows[0].pop('base_value_semantics')
        rows[1]['action']='卖米'
        legacy=deepcopy(data['native_command_evidence'])
        legacy['rows'][0].update(subtype=3,parameter_raw=1)
        effects=retain_phase_values(legacy,{'quarters':[w]})
        for row,annotated in zip(rows,effects['rows']):row['phase_changes']=annotated['phase_changes']
        rows[0]['state_changes']=[dict(basis='state_sample_correlation',metric='rice',before=10000,after=12000,
                                      sample_end='2026-10-10T09:02:01+00:00',gap_seconds=2)]
        self.assertTrue(valid_change(legacy['rows'][0],rows[0]['state_changes'][0]))
        wrapper['sha256']=_digest(data);path.write_text(json.dumps(wrapper))
        old=path.read_bytes()
        loaded=CommandViewStore(self.fixture.root).load('MAC')
        restored=loaded['native_command_evidence']['rows']
        self.assertEqual([r['action'] for r in restored],['建陷阱','买米'])
        self.assertEqual(restored[0]['target_xy_raw'],[0,0])
        self.assertEqual([v['metric'] for v in restored[0]['phase_changes']],['gold'])
        self.assertFalse(restored[0]['state_changes'])
        self.assertEqual({v['metric'] for v in restored[1]['phase_changes']},{'gold','rice'})
        self.assertEqual(command_groups(restored,{})[0]['label'],'200年春')
        self.assertEqual(self.fixture.path.read_bytes(),original)
        corrected=path.read_bytes();self.assertNotEqual(old,corrected)
        self.assertIsNotNone(CommandViewStore(self.fixture.root).load('MAC'))
        self.assertEqual(path.read_bytes(),corrected)

    def test_legacy_label_cannot_hide_changed_operands_or_injected_coordinates(self):
        self.fixture.write([self.fixture.event(native_tests.packet(subtype=4,parameter=6))])
        self.store.remember(self.payload,native_tests.CommandEvidenceReader(self.fixture.root).read(self.payload))
        path=self.store.path('MAC');original=path.read_bytes()
        for edit in (lambda r:r.update(parameter_raw=8),lambda r:r.update(target_xy_raw=[99,99]),
                     lambda r:r.update(action='伪造命令')):
            wrapper=json.loads(original);row=wrapper['data']['native_command_evidence']['rows'][0]
            row['action']='买米';row.pop('target_xy_raw');row.pop('base_value_semantics');edit(row)
            wrapper['sha256']=_digest(wrapper['data']);path.write_text(json.dumps(wrapper))
            self.assertIsNone(CommandViewStore(self.fixture.root).load('MAC'))

    def test_history_loss_and_new_snapshots_do_not_erase_or_rewrite_known_dates(self):
        self.store.remember(self.payload,self.commands)
        path=self.store.path('MAC');original=path.read_bytes()
        self.payload['state']['snapshot_id']='later-frame'
        self.store.remember(self.payload,self.commands)
        self.assertEqual(path.read_bytes(),original)
        self.payload['state'].pop('history')
        result=self.store.remember(self.payload,self.commands)
        self.assertEqual(command_groups(result['rows'],{})[0]['label'],'200年春')
        restarted=CommandViewStore(self.fixture.root)
        result=restarted.remember(self.payload,self.commands)
        self.assertEqual(command_groups(result['rows'],{})[0]['label'],'200年春')

    def test_missing_dates_stay_unknown_and_stale_payloads_do_not_create_cache(self):
        self.payload['fresh']=False
        self.store.remember(self.payload,self.commands)
        self.assertFalse(self.store.path('MAC').exists())
        self.payload['fresh']=True;self.payload['state'].pop('history')
        result=self.store.remember(self.payload,self.commands)
        self.assertEqual(command_groups(result['rows'],{})[0]['label'],'日期未确认')


if __name__=='__main__':unittest.main()
