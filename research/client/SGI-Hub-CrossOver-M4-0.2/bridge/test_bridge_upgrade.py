import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'app'),str(ROOT/'bridge')]
from service_startup import bridge_upgrade_due
import bridge_autostart as b

class BridgeUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'RELEASE.json').write_text(json.dumps({'version':'new'}))
        self.h={'service':b.SERVICE,'release_version':'old','phase':'waiting_for_player',
                'identity':{'pid':788},'snapshot_age_s':.5,'error':None,
                'replay_archive':{'open':False,'recording':False}}
    def test_no_restart_for_live_recovering_recording_stale_or_same_version(self):
        self.assertTrue(bridge_upgrade_due(self.h,self.root))
        for update in ({'phase':'live'},{'phase':'recovering'},{'snapshot_age_s':9},
                       {'replay_archive':{'open':True}},{'replay_archive':{'recording':True}},
                       {'training_archive':{'open':True,'recording':True}},
                       {'release_version':'new'},{'error':'fault'},{'identity':None}):
            with self.subTest(update=update):self.assertFalse(bridge_upgrade_due(dict(self.h,**update),self.root))
        self.assertTrue(bridge_upgrade_due(dict(self.h,phase='waiting_for_game',identity=None),self.root))
    def test_mac_updates_only_owned_collector_after_second_lobby_check(self):
        listing=f'123 {self.root/"bridge/python/python.exe"} -c windows_bridge.py\n789 /other/bridge/python/python.exe -c windows_bridge.py\n555 SANPK.exe'
        with patch.object(b,'configure_local_runtime'),patch.object(b,'probe',side_effect=[self.h,self.h,None]),patch.object(b.subprocess,'check_output',return_value=listing),patch.object(b.os,'kill',side_effect=[None,ProcessLookupError()]) as kill,patch.object(b,'bridge_command',return_value=(['collector'],'test.log')),patch.object(b,'ensure_service',return_value={'mode':'started'}) as start:
            self.assertEqual(b.ensure_bridge(self.root)['mode'],'started')
            self.assertEqual(kill.call_args_list[0].args[0],123)
            self.assertEqual(start.call_count,1)
    def test_room_start_race_cancels_collector_restart(self):
        listing=f'123 {self.root/"bridge/python/python.exe"} -c windows_bridge.py'
        with patch.object(b,'configure_local_runtime'),patch.object(b,'probe',side_effect=[self.h,dict(self.h,phase='live')]),patch.object(b.subprocess,'check_output',return_value=listing),patch.object(b.os,'kill') as kill:
            self.assertEqual(b.ensure_bridge(self.root)['mode'],'reused');kill.assert_not_called()

if __name__=='__main__':unittest.main()
