import copy
import unittest
from unittest.mock import patch

from native_command_evidence import CommandEvidenceReader
from command_view_store import CommandViewStore
from command_transport import SourceCommandExporter, import_commands, import_retained
from command_display import short_command, retain_calendars
from command_personnel import retain_personnel, valid_personnel
from command_phase_values import settlement_sample, retain_phase_values, phase_summaries, valid_phase_value
from command_effects import anomaly_reason
import test_native_command_evidence as native
from test_native_command_evidence import packet


class CommandRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=native.CommandEvidenceTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        s=f.payload['state'];s.update(identity=f.payload['identity'],snapshot_id='frame',capture_end='2026-10-10T09:10:00+00:00')

    def window(self):
        return dict(phase=dict(year_u16=200,season_u16=0,turn_u16=0),
                    phase_after=dict(year_u16=200,season_u16=0,turn_u16=2),
                    **{'from':'2026-10-10T09:00:00+00:00','to':'2026-10-10T09:05:00+00:00'},forces=[])

    def commands(self, events):
        self.f.write(events)
        return retain_calendars(CommandEvidenceReader(self.f.root).read(self.f.payload),{'quarters':[self.window()]})

    def test_unconfirmed_player_still_reads_opponent_but_wrong_process_rejected(self):
        self.f.write([self.f.event(packet(actor=19))])
        p=copy.deepcopy(self.f.payload);p['state'].update(player_force_id=None,player_identity={'status':'unknown'})
        self.assertEqual(self.f.reader.read(p)['rows'][0]['actor_force_id'],19)
        p['state']['identity']['pid']+=1
        self.assertFalse(self.f.reader.read(p)['rows'])

    def test_cold_start_drains_early_segments_without_recounting_then_reads_append(self):
        for n in range(5):self.f.write([self.f.event(pointer=0x222220+n)],self.f.folder/f'{n}-seg-0001.jsonl')
        with patch('native_command_evidence.MAX_FILES',2):
            first=self.f.reader.read(self.f.payload);self.assertEqual(len(first['rows']),2);self.assertTrue(first['scan_pending'])
            self.assertEqual(len(self.f.reader.read(self.f.payload)['rows']),4)
            result=self.f.reader.read(self.f.payload);self.assertEqual(len(result['rows']),5)
            self.assertFalse(result['files_limited']);self.assertFalse(result['scan_pending'])
            original=copy.deepcopy(result['rows']);self.assertEqual(self.f.reader.read(self.f.payload)['rows'],original)
            self.f.write([self.f.event(pointer=0x333333)],self.f.folder/'0-seg-0001.jsonl',mode='ab')
            self.assertEqual(len(self.f.reader.read(self.f.payload)['rows']),6)

    def test_cache_merge_keeps_earlier_rows_on_empty_and_partial_restart_batches(self):
        self.f.write([self.f.event()]);store=CommandViewStore(self.f.root)
        a=store.remember(self.f.payload,self.f.reader.read(self.f.payload));old=a['rows'][0]
        self.f.write([self.f.event(pointer=0x333333)],mode='ab')
        all_rows=self.f.reader.read(self.f.payload)
        partial=dict(all_rows,rows=all_rows['rows'][1:])
        b=CommandViewStore(self.f.root).remember(self.f.payload,partial)
        self.assertEqual(len(b['rows']),2);self.assertIn(old['raw_sha256'],[r['raw_sha256'] for r in b['rows']])
        self.assertEqual(len(store.remember(self.f.payload,dict(all_rows,rows=[]))['rows']),2)
        foreign=dict(all_rows,binding=dict(all_rows['binding'],created=99),rows=[])
        self.assertFalse(store.remember(self.f.payload,foreign)['rows'])

    def personnel_fixture(self):
        commands=self.commands([self.f.event(packet('CSanInetPersonnelCmd',0,actor=16,target=33))])
        self.f.payload['state']['entities']['cities_and_barriers']=[dict(city_id=33,name='零陵')]
        w=self.window();w['forces']=[dict(owner=16,operations=[dict(field='录用',via='pending_hire',after='褒姒',general_id=586,target={'city_id':33})])]
        self.f.payload['state']['history']={'quarters':[w]}
        return commands,w

    def test_city_target_and_unique_pending_hire_name_not_officer_id(self):
        commands,w=self.personnel_fixture();row=retain_personnel(commands,self.f.payload['state'])['rows'][0]
        self.assertEqual(short_command(row),'录用 零陵 → 褒姒(政治:83)（观测）')
        self.assertTrue(valid_personnel(row,row['personnel_reference'],commands['binding']))
        self.assertFalse(row['action_training_eligible']);self.assertIsNone(row['command_committed'])
        w['forces'][0]['operations'][0]['via']='owner_change'
        self.assertEqual(short_command(retain_personnel(commands,self.f.payload['state'])['rows'][0]),'录用 零陵 · 未观察到结果')

    def test_hire_wrong_force_city_season_multiple_candidates_and_source_are_not_claimed(self):
        commands,w=self.personnel_fixture()
        for edit in (lambda s:s['history']['quarters'][0]['forces'][0].update(owner=19),
                     lambda s:s['history']['quarters'][0]['forces'][0]['operations'][0]['target'].update(city_id=34),
                     lambda s:s['history']['quarters'][0]['phase'].update(season_u16=1)):
            s=copy.deepcopy(self.f.payload['state']);edit(s)
            self.assertNotIn('result',retain_personnel(commands,s)['rows'][0]['personnel_reference'])
        multiple=copy.deepcopy(commands);multiple['rows'].append(dict(multiple['rows'][0],source_line_sha256='b'*64))
        self.assertNotIn('result',retain_personnel(multiple,self.f.payload['state'])['rows'][0]['personnel_reference'])
        s=copy.deepcopy(self.f.payload['state']);s['identity']['pid']+=1
        self.assertNotIn('personnel_reference',retain_personnel(commands,s)['rows'][0])

    def numeric_fixture(self):
        commands=self.commands([self.f.event(packet(actor=16)),self.f.event(packet(actor=16),pointer=0x333333)])
        w=self.window()
        before=dict(phase_candidate=dict(year_u16=200,season_u16=0,turn_u16=1),capture_end='2026-10-10T09:04:56+00:00',
                    entities={'lords':[dict(force_id=16,gold=5000,rice=400000,prestige=120,armament_raw={'infantry':150})]})
        after=copy.deepcopy(before);after.update(capture_end=w['to'],phase_candidate=w['phase_after'])
        after['entities']['lords'][0]['armament_raw']['infantry']=185
        w['settlement_sample']=settlement_sample(before,after)
        return commands,{'quarters':[w]},before,after

    def test_delayed_training_is_shared_net_observation_once_not_two_per_action_gains(self):
        commands,h,_,_=self.numeric_fixture()
        out=retain_phase_values(commands,h);lines=phase_summaries(out['rows'],out['binding'])
        self.assertEqual(len(lines),1);self.assertIn('2笔',lines[0]);self.assertIn('50/100→强化步兵 85/100（+35）',lines[0])
        self.assertTrue(all(not anomaly_reason(row) for row in out['rows']))
        self.assertTrue(all(row['command_committed'] is None for row in out['rows']))
        # Military, cross-season, or a missing boundary never produces a gain.
        for change in ({'turn_u16':3},{'season_u16':1}):
            other=copy.deepcopy(h);other['quarters'][0]['phase_after'].update(change)
            self.assertFalse(phase_summaries(retain_phase_values(commands,other)['rows'],commands['binding']))

    def test_unchanged_rice_cap_is_observed_zero_and_net_resource_loss_not_buy_gain(self):
        _,h,before,after=self.numeric_fixture()
        commands=self.commands([self.f.event(packet(subtype=3,parameter=1,actor=16))])
        after['entities']['lords'][0].update(gold=3000)
        h['quarters'][0]['settlement_sample']=settlement_sample(before,after)
        out=retain_phase_values(commands,h);line=phase_summaries(out['rows'],out['binding'])[0]
        self.assertIn('金 5,000→3,000（-2000）',line);self.assertIn('粮 400,000→400,000（+0）',line)
        self.assertIn('观测净值',line)

    def test_legacy_changed_values_fallback_uses_boundary_not_season_net(self):
        commands,h,_,_=self.numeric_fixture();h['quarters'][0].pop('settlement_sample')
        h['recent_changes']=[dict(entity='lords',owner=16,metric='training',kind='infantry',raw_before=150,raw_after=185,
                                  time=h['quarters'][0]['to'],gap_seconds=4)]
        out=retain_phase_values(commands,h);self.assertTrue(out['rows'][0]['phase_changes'])
        h['recent_changes'][0]['time']='2026-10-10T09:09:00+00:00'
        self.assertFalse(retain_phase_values(commands,h)['rows'][0]['phase_changes'])

    def test_instant_trade_payment_and_later_boundary_chain_excludes_earlier_income(self):
        _,h,before,after=self.numeric_fixture()
        commands=self.commands([self.f.event(packet(subtype=3,parameter=1,actor=16)),
                                self.f.event(packet(subtype=3,parameter=1,actor=16),pointer=0x333333)])
        before['entities']['lords'][0]['gold']=3000;after['entities']['lords'][0]['gold']=1000
        h['quarters'][0]['settlement_sample']=settlement_sample(before,after)
        h['recent_changes']=[dict(entity='lords',owner=16,field='金钱',before='1000',after='5000',
                                  time='2026-10-10T09:00:30+00:00',gap_seconds=1),
                             dict(entity='lords',owner=16,field='金钱',before='5000',after='3000',
                                  time='2026-10-10T09:03:00+00:00',gap_seconds=1)]
        out=retain_phase_values(commands,h);line=phase_summaries(out['rows'],out['binding'])[0]
        self.assertIn('金 5,000→1,000（-4000）',line)
        self.assertTrue(line.startswith('阶段金粮'))
        value=out['rows'][0]['phase_changes'][0];self.assertEqual(len(value['segments']),2)
        self.assertTrue(valid_phase_value(out['rows'][0],value,out['binding']))
        bad=copy.deepcopy(value);bad['segments'][0]['after']=2999
        self.assertFalse(valid_phase_value(out['rows'][0],bad,out['binding']))

    def test_construction_correlates_gold_but_cannot_claim_rice_trade(self):
        _,h,before,after=self.numeric_fixture()
        commands=self.commands([self.f.event(packet(subtype=4,parameter=6,actor=16))])
        after['entities']['lords'][0].update(gold=3000,rice=399000)
        h['quarters'][0]['settlement_sample']=settlement_sample(before,after)
        out=retain_phase_values(commands,h)
        self.assertEqual(out['rows'][0]['action'],'建陷阱')
        self.assertEqual([v['metric'] for v in out['rows'][0]['phase_changes']],['gold'])
        self.assertNotIn('粮',phase_summaries(out['rows'],out['binding'])[0].split('观测净值：')[-1])

    def test_named_results_phase_values_and_offline_remote_roundtrip_validate_and_stay_stale(self):
        _,w=self.personnel_fixture()
        self.f.write([self.f.event(packet('CSanInetPersonnelCmd',0,actor=16,target=33)),self.f.event(packet(actor=16),pointer=0x333333)])
        _,h,_,_=self.numeric_fixture();h['quarters'][0]['forces']=w['forces']
        # numeric_fixture rewrote the source file; install the final journal once.
        self.f.write([self.f.event(packet('CSanInetPersonnelCmd',0,actor=16,target=33)),self.f.event(packet(actor=16),pointer=0x333333)])
        self.f.payload['state']['history']=h
        exporter=SourceCommandExporter(self.f.root);wire=exporter.attach(self.f.payload)
        live=import_commands(wire);self.assertEqual(len(live['rows']),2)
        self.assertIn('零陵 → 褒姒',short_command(live['rows'][0]))
        self.assertTrue(live['rows'][1]['phase_changes'])
        offline_payload=exporter.attach(dict(self.f.payload,fresh=False,state=None,identity=None))
        offline=import_retained(offline_payload);self.assertTrue(offline['retained_only'])
        self.assertNotIn('state',offline);self.assertNotIn('player_identity',offline)
        self.assertIn('零陵 → 褒姒',short_command(offline['native_command_evidence']['rows'][0]))
        bad=copy.deepcopy(offline_payload);bad['source_id']='OTHER';self.assertIsNone(import_retained(bad))
        bad=copy.deepcopy(offline_payload);bad['retained_command_transfer']['native_command_evidence']['rows'][1]['phase_changes'][0]['binding_sha256']='f'*64
        self.assertIsNone(import_retained(bad))


if __name__=='__main__':unittest.main()
