"""Complementary sender evidence is opt-in and never re-bound to the viewer."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from command_peer import CommandPeer, scope
from command_display import display_rows, command_groups
from command_transport import SourceCommandExporter, import_commands
from test_command_display import window
import test_native_command_evidence as native_tests
from test_native_command_evidence import packet


class PeerTests(unittest.TestCase):
    def setUp(self):
        f=native_tests.CommandEvidenceTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        f.payload['state']['history']={'quarters':[window(1,'09:00:00','09:10:00')]}
        f.write([f.event(packet(subtype=3)),f.event(packet(subtype=2),pointer=0x222333)])
        self.peer=SourceCommandExporter(f.root).attach(f.payload)
        self.primary=copy.deepcopy(self.peer);self.primary['source_id']='PRIMARY'
        self.primary['identity']['creation_filetime']+=1
        self.primary['state']['identity']=copy.deepcopy(self.primary['identity'])
        self.primary['state']['player_identity']['session_id']='primary-session'
        self.config=dict(schema=1,confirmed_same_game=True,primary=scope(self.primary),peer=scope(self.peer),
                         connection=dict(mode='local',label='MAC',expected_source='MAC',port=8770))
        (f.root/'command-peer.local.json').write_text(json.dumps(self.config))
        self.commands=dict(binding=scope(self.primary)['binding'],rows=[])
        self.reader=CommandPeer(f.root,fetch=lambda:self.peer)

    def test_summer_restored_with_original_peer_binding_and_no_primary_mutation(self):
        result=self.reader.attach(self.primary,self.commands)
        rows=display_rows(result)
        self.assertEqual([r['action'] for r in rows],['卖米','施舍'])
        self.assertEqual(command_groups(rows,{})[0]['label'],'200年夏')
        self.assertEqual(self.commands['rows'],[])
        self.assertEqual(result['binding'],self.commands['binding'])
        self.assertTrue(all(r['display_binding']==scope(self.peer)['binding'] for r in rows))
        self.assertTrue(all(r['display_source']=='MAC' and r['match_id'] is None
                            and r['action_training_eligible'] is False for r in rows))

    def test_no_pairing_or_another_primary_game_cannot_import(self):
        (self.f.root/'command-peer.local.json').unlink()
        self.assertEqual(CommandPeer(self.f.root,fetch=lambda:self.peer).attach(self.primary,self.commands),self.commands)
        for alter in (lambda p:p['identity'].update(creation_filetime=99),
                      lambda p:p['state']['player_identity'].update(session_id='new-game')):
            changed=copy.deepcopy(self.primary);alter(changed)
            self.assertEqual(self.reader.attach(changed,self.commands),self.commands)

    def test_bad_peer_hash_or_game_scope_never_added(self):
        for alter in (lambda p:p['state']['native_command_transfer']['rows'][0].update(raw_sha256='bad'),
                      lambda p:p['identity'].update(creation_filetime=99),
                      lambda p:p['state']['player_identity'].update(session_id='new-game')):
            changed=copy.deepcopy(self.peer);alter(changed)
            reader=CommandPeer(self.f.root,fetch=lambda:changed)
            self.assertEqual(reader.attach(self.primary,self.commands),self.commands)

    def test_temporary_disconnect_keeps_verified_batch_as_retained(self):
        first=self.reader.attach(self.primary,self.commands)
        self.reader.last_poll=0
        def offline():raise OSError('offline')
        self.reader.fetch=offline
        second=self.reader.attach(self.primary,self.commands)
        self.assertEqual(display_rows(first),display_rows(second))
        self.assertEqual(second['supplemental_sources'][0]['capture_status']['error'],'peer_offline')

    def test_shared_packets_display_once_but_keep_both_sources_evidence(self):
        row=import_commands(self.peer)['rows'][0]
        commands=dict(self.commands,rows=[copy.deepcopy(row)])
        result=self.reader.attach(self.primary,commands)
        self.assertEqual(len(display_rows(result)),2)
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(len(result['supplemental_sources'][0]['rows']),2)
        self.assertEqual(commands['rows'],[row])
        # Equal payload in another sampling quarter does not suppress a row.
        commands['rows'][0]['sampling_calendar']['season_u16']=0
        self.assertEqual(len(display_rows(self.reader.attach(self.primary,commands))),3)

    def test_viewer_restart_and_empty_batch_do_not_erase_summer(self):
        self.reader.attach(self.primary,self.commands)
        empty=copy.deepcopy(self.peer);empty['state']['native_command_transfer']['rows']=[]
        restarted=CommandPeer(self.f.root,fetch=lambda:empty)
        result=restarted.attach(self.primary,self.commands)
        self.assertEqual(len(display_rows(result)),2)
        cache=json.loads(restarted.cache.read_bytes());cache['rows'][0]['source_line_sha256']='bad'
        restarted.cache.write_text(json.dumps(cache))
        invalid=CommandPeer(self.f.root,fetch=lambda:empty)
        self.assertEqual(display_rows(invalid.attach(self.primary,self.commands)),[])


if __name__=='__main__':unittest.main()
