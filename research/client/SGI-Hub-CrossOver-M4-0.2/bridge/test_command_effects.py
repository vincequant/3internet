import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from command_effects import retain_effects, effect_text, anomaly_reason, abnormal_force_ids, badge_text
from command_display import retain_calendars
from state_history import slim, differences
from test_command_display import window


def fixture(training=False):
    row = dict(native_type=18, subtype=0 if training else 2, parameter_raw=0,
               value_raw=240, extra_raw=1, actor_force_id=11,
               action='步兵训练' if training else '施舍',
               observed_at='2026-10-10T08:30:00+00:00', source_line_sha256='one')
    change = dict(entity='lords', owner=11, field='步训练' if training else '信望',
                  before='140', after='146', time='2026-10-10T08:30:01+00:00',
                  gap_seconds=1.5, phase={'year_u16':200,'season_u16':0})
    if training:
        change.update(metric='training', kind='infantry', raw_before=150, raw_after=226,
                      training_politics_upper_before=112, training_stock_before=30000)
    history=dict(quarters=[window(0,'08:00:00','09:00:00')], recent_changes=[change])
    return row, history


class CommandEffectsTests(unittest.TestCase):
    def test_real_style_alms_correlation_is_display_only_and_nonmutating(self):
        row,h=fixture();commands={'rows':[row]};original=copy.deepcopy(commands)
        annotated=retain_effects(commands,h)['rows'][0]
        self.assertEqual(effect_text(annotated),'施舍 信望 140→146（+6，观测）')
        self.assertFalse(anomaly_reason(annotated));self.assertEqual(commands,original)
        self.assertNotIn('command_committed',annotated)

    def test_missing_wrong_force_gap_season_and_ambiguous_pairs_stay_unknown(self):
        row,h=fixture()
        variants=[]
        for edits in ({'owner':0},{'gap_seconds':30},{'phase':{'year_u16':200,'season_u16':1}},
                      {'time':'2026-10-10T08:29:59+00:00'}):
            other=copy.deepcopy(h);other['recent_changes'][0].update(edits);variants.append(other)
        variants.append({})
        for history in variants:
            result=retain_effects({'rows':[row]},history)['rows'][0]
            self.assertIn('数值未确认',effect_text(result));self.assertFalse(anomaly_reason(result))
        result=retain_effects({'rows':[row,dict(row,source_line_sha256='two')]},h)
        self.assertTrue(all(not r['state_changes'] for r in result['rows']))

    def test_training_includes_tier_transition_and_pre_action_politics_bound(self):
        row,h=fixture(True);annotated=retain_effects({'rows':[row]},h)['rows'][0]
        self.assertIn('强化步兵 50/100→重装步兵 26/100（+76，观测）',effect_text(annotated))
        self.assertIn('240',anomaly_reason(annotated));self.assertIn('112',anomaly_reason(annotated))
        annotated['value_raw']=112;self.assertFalse(anomaly_reason(annotated))

    def test_no_fixed100_cap_for_custom_officers_and_no_accumulated_gain_verdict(self):
        row,h=fixture(True);h['recent_changes'][0]['training_politics_upper_before']=280
        annotated=retain_effects({'rows':[row]},h)['rows'][0]
        self.assertFalse(anomaly_reason(annotated))
        self.assertFalse(anomaly_reason(row)) # no historical officer stats: conservative357
        self.assertTrue(anomaly_reason(dict(row,value_raw=1000)))
        row,h=fixture();h['recent_changes'][0].update(after='190')
        self.assertEqual(badge_text(retain_effects({'rows':[row]},h)['rows'][0]),'疑似外挂')
        self.assertTrue(anomaly_reason(dict(row,extra_raw=22))) # operand+5=27
        self.assertFalse(anomaly_reason(dict(row,extra_raw=5))) # wider documented upper10

    def test_training_gain_only_is_suspected_and_stock_mixing_is_excluded(self):
        row,h=fixture(True);row['value_raw']=80
        h['recent_changes'][0]['training_stock_after']=30000
        annotated=retain_effects({'rows':[row]},h)['rows'][0]
        self.assertEqual(badge_text(annotated),'疑似外挂')
        h['recent_changes'][0]['training_stock_after']=31000
        self.assertFalse(badge_text(retain_effects({'rows':[row]},h)['rows'][0]))

    def test_force_badge_is_source_history_scoped(self):
        row,h=fixture();row['extra_raw']=22
        state={'native_command_evidence':{'rows':[row]},'history':h}
        self.assertEqual(abnormal_force_ids(state),{11})
        state['history']={'quarters':[window(1,'09:00:00','10:00:00')]}
        self.assertFalse(abnormal_force_ids(state))
        self.assertFalse(abnormal_force_ids({}))

    def test_before_context_includes_custom_stats_and_conservative_book_bonus(self):
        state={'entities':{'lords':[{'force_id':11,'armament_raw':{'infantry':150},
                  'troop_stock':{'infantry':30000}}],
                  'generals':[{'owner_raw':11,'attributes':{'pol':200}}]}}
        before=slim(state);self.assertEqual(before['entities']['lords'][0]['training_politics_upper'],280)
        after=copy.deepcopy(before);after['entities']['lords'][0]['armament_raw']['infantry']=226
        change=next(c for c in differences(before,after) if c.get('metric')=='training')
        self.assertEqual(change['training_politics_upper_before'],280)
        self.assertEqual(change['training_stock_before'],30000)
        state['entities']['generals'].append({'owner_raw':11,'attributes':{}})
        self.assertIsNone(slim(state)['entities']['lords'][0]['training_politics_upper'])

    def test_cache_and_remote_keep_correlations_without_upgrading_raw_evidence(self):
        import test_native_command_evidence as native
        from command_view_store import CommandViewStore
        from command_transport import SourceCommandExporter, import_commands
        f=native.CommandEvidenceTests();f.setUp();self.addCleanup(f.doCleanups)
        event=f.event(native.packet(subtype=2,actor=11));event['captured_at']='2026-10-10T08:30:00+00:00'
        f.write([event]);_,h=fixture();f.payload['state']['history']=h
        store=CommandViewStore(f.root);commands=f.reader.read(f.payload)
        row=store.remember(f.payload,commands)['rows'][0]
        self.assertIn('140→146',effect_text(row))
        exporter=SourceCommandExporter(f.root)
        wire=exporter.attach(f.payload);remote=import_commands(wire)['rows'][0]
        self.assertEqual(remote['state_changes'],row['state_changes'])
        f.payload['state'].pop('history')
        offline=CommandViewStore(f.root).load('MAC')['native_command_evidence']['rows'][0]
        self.assertIn('140→146',effect_text(offline))
        self.assertFalse(offline['server_result_verified']);self.assertFalse(offline['action_training_eligible'])
        wire['state']['native_command_transfer']['rows'][0]['state_changes'][0]['gap_seconds']=99
        self.assertEqual(import_commands(wire)['status'],'remote_invalid')


if __name__=='__main__':unittest.main()
