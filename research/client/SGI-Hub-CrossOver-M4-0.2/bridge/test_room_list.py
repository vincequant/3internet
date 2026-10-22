import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from room_list_model import apply_layout_freshness,compare_record,decode_room,AlertState,listbox_agreement,parse_list_count,ui_list_agreement

def record(current=1, maximum=8):
    data=bytearray(80)
    struct.pack_into('<I',data,0,123)
    data[4:8]=b'room'
    data[35:39]=b'host'
    struct.pack_into('<III',data,68,maximum,current,0)
    return bytes(data)

class RoomTests(unittest.TestCase):
    def test_record(self):
        self.assertEqual(decode_room(record())['name'],'room[host]')
        self.assertEqual(decode_room(record())['current'],1)
        self.assertEqual(decode_room(record())['maximum'],8)
    def test_invalid(self):
        for value in (b'',record(9),record(0),record(1,100)):
            with self.assertRaises(ValueError):decode_room(value)
    def test_nonterminated(self):
        data=bytearray(record());data[4:35]=b'a'*31
        with self.assertRaises(ValueError):decode_room(bytes(data))
    def test_ui_list_agreement(self):
        rooms=[decode_room(record(5))]
        self.assertEqual(ui_list_agreement([],['★看不到主机，刷新一下。']),'empty_agree')
        self.assertEqual(ui_list_agreement(rooms,['★看不到主机，刷新一下。']),'mismatch')
        self.assertEqual(ui_list_agreement(rooms,[]),'rooms_present')
        self.assertEqual(ui_list_agreement([],[]),'unknown')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
        from room_watch import snapshot_for_alerts
        mismatched={'status':'fresh','rooms':rooms,'ui_list':'mismatch'}
        self.assertEqual(snapshot_for_alerts(mismatched)['status'],'cached')
        self.assertEqual(AlertState().update(snapshot_for_alerts(mismatched)),[])
        self.assertTrue(AlertState().update({'status':'fresh','rooms':rooms}))
        hidden=apply_layout_freshness({'status':'fresh','rooms':rooms,'ui_layout':{'select_visible':False}})
        self.assertEqual(hidden['status'],'cached')
        self.assertEqual(AlertState().update(hidden),[])
        shown=apply_layout_freshness({'status':'fresh','rooms':rooms,'ui_list':'rooms_present',
                                     'ui_layout':{'select_visible':True}})
        self.assertEqual(shown['status'],'fresh')
        reader_mismatch=apply_layout_freshness({'status':'fresh','rooms':rooms,'ui_list':'mismatch',
                                               'ui_layout':{'select_visible':True}})
        self.assertEqual(reader_mismatch['status'],'cached')
        self.assertEqual(AlertState().update(reader_mismatch),[])
        hint_but_list=apply_layout_freshness({'status':'fresh','rooms':rooms,'ui_list':'mismatch',
                                             'ui_listbox':'rooms_agree',
                                             'ui_layout':{'select_visible':True}})
        self.assertEqual(hint_but_list['status'],'fresh')
        self.assertTrue(AlertState().update(hint_but_list))
        hint_snap={'status':'fresh','rooms':rooms,'ui_list':'mismatch','ui_listbox':'rooms_agree'}
        self.assertEqual(snapshot_for_alerts(hint_snap)['status'],'fresh')
        self.assertTrue(AlertState().update(snapshot_for_alerts(hint_snap)))
        source=(Path(__file__).parent/'room_list_reader.py').read_text(encoding='utf8')
        self.assertIn('def game_select_hints',source)
        self.assertIn('def game_select_layout',source)
        self.assertIn('def listbox_snapshot',source)
        self.assertIn('请只打开一个游戏选择窗口',source)
        self.assertIn('无法定位指定实例的游戏选择窗口',source)
        self.assertIn('parse_target_argv',source)
        self.assertIn('tries=3',source)
        self.assertIn('lb_getcount_failed',source)
        self.assertIn('SendMessageTimeoutA',source)
        self.assertIn('IsWindowUnicode',source)
        self.assertIn("decode('gbk','replace')",source)
        self.assertIn('create_string_buffer(512)',source)
        self.assertNotIn('create_string_buffer(length+1)',source)
        self.assertIn('persist_compare',source)
        self.assertIn('apply_layout_freshness',source)
        self.assertIn('ui_list_agreement',source)
        self.assertNotIn('LVM_GETITEMTEXT',source)
        self.assertIn('LB_GETTEXT',source)
        self.assertIn('SendMessageTimeoutW',source)
        self.assertEqual(listbox_agreement([],[]),'empty_agree')
        self.assertEqual(listbox_agreement(rooms,[]),'mismatch')
        self.assertEqual(listbox_agreement(rooms,['SGZWLB[host] 5/8']),'rooms_agree')
        self.assertEqual(listbox_agreement(rooms,['SGZWLB[host] ５／８']),'rooms_agree')
        self.assertEqual(parse_list_count('1/2练习 SGZWLB[小白白] 3/8'), (3, 8))
        self.assertEqual(listbox_agreement(rooms,['1/2练习 room[host] 5/8']),'rooms_agree')
        self.assertEqual(listbox_agreement(rooms,['SGZWLB[host] 4/8']),'mismatch')
        recorded=[{'name':'SGZWLB[小白白]','current':3,'maximum':8}]
        self.assertEqual(listbox_agreement(recorded,['SGZWLB[小白白] 3/8']),'rooms_agree')
        self.assertEqual(AlertState(4,1).update({'status':'fresh','rooms':recorded,'observed_at':time.time()}),[])
        watch=(Path(__file__).resolve().parents[1]/'app/room_watch.py').read_text(encoding='utf-8')
        self.assertIn('列表原文',watch)
        self.assertIn("value.get('ui_listbox')=='mismatch'",watch)
        self.assertEqual(listbox_agreement(rooms,None),'unknown')
        self.assertEqual(listbox_agreement(rooms,None,1),'count_agree')
        self.assertEqual(listbox_agreement(rooms,None,2),'mismatch')
        boxed=apply_layout_freshness({'status':'fresh','rooms':rooms,'ui_listbox':'mismatch',
                                     'ui_layout':{'select_visible':True}})
        self.assertEqual(boxed['status'],'cached')
        self.assertEqual(AlertState().update(boxed),[])
        boxed_ui={'status':'fresh','rooms':rooms,'ui_listbox':'mismatch'}
        self.assertEqual(snapshot_for_alerts(boxed_ui)['status'],'cached')
        self.assertEqual(AlertState().update(snapshot_for_alerts(boxed_ui)),[])
        inspect_src=source[source.find('def inspect_ui'):]
        self.assertIn('records(h,hwnd)',inspect_src)
        self.assertIn("result['rooms']=records(h,hwnd)",inspect_src)
        self.assertIn("result['ui_listbox']='unknown'",inspect_src)
        self.assertIsNone(compare_record({'ui_listbox':'empty_agree','rooms':[]}))
        kept=compare_record({'ui_listbox':'rooms_agree','rooms':rooms,'ui_listbox_items':['room[host] 5/8'],
                             'ui_listbox_count':1,'status':'fresh'})
        self.assertEqual(kept['rooms'][0]['current'],5)
        self.assertEqual(compare_record({'ui_listbox':'count_agree','rooms':[]}),None)
        flashed={'status':'fresh','rooms':rooms,'confirm_first_visible':True,'observed_at':time.time()}
        self.assertEqual(snapshot_for_alerts(flashed)['status'],'fresh')
        self.assertTrue(AlertState().update(snapshot_for_alerts(flashed)))
        self.assertIn('搜寻确认框曾短暂可见',watch)

    def test_strict_threshold(self):
        state=AlertState()
        self.assertEqual(state.update({'status':'fresh','rooms':[decode_room(record(4))]}),[])
        self.assertEqual(len(state.update({'status':'fresh','rooms':[decode_room(record(5))]})),1)
    def test_cached_never_alerts(self):
        self.assertEqual(AlertState().update({'status':'cached','rooms':[decode_room(record(8))]}),[])
    def test_no_duplicate_and_rearm(self):
        state=AlertState();high={'status':'fresh','rooms':[decode_room(record(5))]}
        self.assertEqual(len(state.update(high,now=0)),1)
        self.assertEqual(state.update(high,now=20),[])
        self.assertEqual(state.update({'status':'unavailable','rooms':[]}),[])
        self.assertEqual(state.update(high,now=30),[])
        state.update({'status':'fresh','rooms':[decode_room(record(4))]})
        self.assertEqual(state.update(high,now=59),[])
        self.assertEqual(len(state.update(high,now=60)),1)
    def test_unknown_is_not_zero(self):
        self.assertEqual(AlertState().update({'status':'unavailable','rooms':[]}),[])
    def test_waiting_or_stale_never_alerts(self):
        room=decode_room(record(8))
        self.assertEqual(AlertState().update({'status':'waiting_lobby','rooms':[room]}),[])
        self.assertEqual(AlertState().update({'status':'fresh','rooms':[room],'observed_at':time.time()-46}),[])
        self.assertEqual(AlertState().update({'status':'fresh','rooms':[room]},enabled=False),[])
    def test_windows_command(self):
        path=Path(__file__).resolve().parents[1]/'app/room_watch.py'
        sys.path.insert(0,str(path.parent))
        spec=importlib.util.spec_from_file_location('room_watch_test',path)
        app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
        with patch.object(sys,'platform','win32'), patch.object(app,'wine_prefix',return_value=None):
            cmd,env=app.command(True)
        self.assertEqual(cmd[-1],'--refresh')
        self.assertTrue(any('room_list_reader.py' in x for x in cmd))
        self.assertFalse(any('wine' in x.lower() for x in cmd))
        with patch.object(sys,'platform','win32'), patch.object(app,'wine_prefix',return_value='/tmp/main-prefix'):
            scoped,_=app.command(True)
        self.assertEqual(scoped[-1],'--refresh')
        self.assertEqual(scoped[scoped.index('--prefix')+1],'/tmp/main-prefix')
    def test_native_probe_read_only_cache(self):
        # Live refresh is a separate opt-in flag, never part of a cached read.
        source=(Path(__file__).parent/'room_list_reader.py').read_text(encoding='utf8')
        lobby=(Path(__file__).parent/'lobby_titles.py').read_text(encoding='utf8')
        for forbidden in ('WriteProcessMemory','VirtualAllocEx','CreateRemoteThread','TerminateProcess',
                          'SendInput','mouse_event','keybd_event','SetForegroundWindow','BringWindowToTop',
                          'LVM_GETITEMTEXT','AccessibleObjectFromWindow'):
            self.assertNotIn(forbidden,source)
        self.assertIn('LB_GETTEXT',source)
        self.assertIn('SendMessageTimeoutW',source)
        self.assertIn("click(hwnd,pid,TITLE,1006,'刷新列表(&S)',allow_hidden=quiet)",source)
        self.assertIn("click(dialog,pid,CONFIRM,1,'确定',allow_hidden=quiet)",source)
        self.assertIn('SW_HIDE',source)
        self.assertNotIn('SW_SHOWMAXIMIZED',source)
        self.assertNotIn('def hide_pid',source)
        self.assertIn('hide_wait_windows',source)
        self.assertIn("WAIT_TITLES = (CONFIRM,)",source)
        self.assertNotIn("WAIT_TITLES = (TITLE, CONFIRM)",source)
        self.assertIn('NetHookCoreWindow2012',source)
        self.assertGreaterEqual(source.count('hide_wait_windows('),4)
        self.assertIn('confirm_first_visible',source)
        self.assertIn('confirm_first_visible=bool(u.IsWindowVisible(dialog))',source)
        self.assertIn('offscreen=True',source)
        self.assertIn('SWP_NOREDRAW',source)
        self.assertIn("NETHOOK_TITLE, ''",source)
        self.assertIn('spin=time.monotonic()+0.5',source)
        self.assertNotIn("name==TITLE",source[source.find('def refresh'):source.find('def read')])
        self.assertNotIn('hide_wait_windows(pid)\n            hide_window(hwnd)',source)
        self.assertNotIn('hide_window(hwnd)\n            return',source)
        self.assertNotIn('DestroyWindow',source)
        self.assertIn('def restore_select_if_modal_hidden',source)
        self.assertIn('restore_select_if_modal_hidden(hwnd, pid)',source)
        self.assertIn('EnableWindow',source)
        self.assertIn("'enabled':bool(u.IsWindowEnabled(top))",source)
        self.assertNotIn('elif quiet:hide_pid',source)
        self.assertEqual(source.count("click(hwnd,pid,TITLE,1006"),1)
        self.assertNotIn("click(hwnd,pid,TITLE,1024",source)
        self.assertIn('已离开游戏选择，观察已暂停',source)
        self.assertNotIn("click(hwnd,pid,TITLE,1005",source)
        for forbidden in ('SendMessageW','PostMessageW','LVM_GETITEMTEXT','WriteProcessMemory','SetForegroundWindow'):
            self.assertNotIn(forbidden,lobby)
        self.assertIn('GetWindowTextW',lobby)

    def test_configurable_repeat(self):
        state=AlertState(6,2)
        value={'status':'fresh','rooms':[decode_room(record(6))]}
        self.assertFalse(state.update(value,now=0))
        value['rooms']=[decode_room(record(7))]
        self.assertEqual(len(state.update(value,now=1)),1)
        self.assertFalse(state.update(value,now=120))
        self.assertEqual(len(state.update(value,now=121)),1)

    def test_multiple_rooms_shared_interval(self):
        state=AlertState(4,1);r=decode_room(record(5))
        value={'status':'fresh','rooms':[r]}
        self.assertTrue(state.update(value,now=0))
        value['rooms'].append(dict(r,id='other'))
        self.assertFalse(state.update(value,now=10))
        self.assertEqual(len(state.update(value,now=60)),2)

    def test_muted_and_stale_never_alert(self):
        state=AlertState();value={'status':'fresh','rooms':[decode_room(record(5))]}
        self.assertFalse(state.update(value,now=0,enabled=False))
        value['observed_at']=time.time()-120
        self.assertFalse(state.update(value,now=0))
        value['observed_at']=time.time()
        self.assertTrue(state.update(value,now=0))

    def test_settings_round_trip_and_validation(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
        from room_watch_settings import load,save,update,read_file
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'room-watch.local.json'
            self.assertEqual(load(path),(4,1))
            self.assertEqual(read_file(path)['threshold'],4)
            self.assertEqual(read_file(path)['minutes'],1.0)
            update(path,audio_original=1,audio_muted=True)
            # drop xy to simulate this machine's old local file
            stored=read_file(path); stored.pop('threshold',None); stored.pop('minutes',None)
            path.write_text(__import__('json').dumps(stored),encoding='utf-8')
            self.assertEqual(load(path),(4,1))
            self.assertEqual(read_file(path)['audio_original'],1)
            self.assertTrue(read_file(path)['audio_muted'])
            self.assertEqual(read_file(path)['threshold'],4)
            save(path,6,2.5);self.assertEqual(load(path),(6,2.5))
            for x,y in [('abc',1),(4,0),(4,-1),(4,'nan'),(4,'inf'),(4.5,1),(64,1)]:
                with self.assertRaises(ValueError):save(path,x,y)
            self.assertEqual(load(path),(6,2.5))

    def test_settings_not_published(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from publish import allowed
        self.assertFalse(allowed('room-watch.local.json'))
        self.assertTrue(allowed('Start-Room-Watch.command'))
        self.assertTrue(allowed('Start-Room-Watch.cmd'))
        self.assertTrue(allowed('Start-Quiet-Wait.command'))
        self.assertTrue(allowed('Start-Quiet-Wait.cmd'))
        self.assertTrue(allowed('app/quiet_wait_launch.py'))
        self.assertTrue(allowed('Start-Wine-Nav.command'))
        self.assertTrue(allowed('Start-Wine-Nav.cmd'))
        self.assertTrue(allowed('app/wine_nav.py'))
        self.assertTrue(allowed('app/panorama_map.py'))
        self.assertTrue(allowed('app/panorama_model.py'))
        self.assertTrue(allowed('Start-Replay.command'))
        self.assertTrue(allowed('Start-Replay.cmd'))
        self.assertTrue(allowed('Start-War-Query.command'))
        self.assertTrue(allowed('Start-War-Query.cmd'))
        self.assertTrue(allowed('WAR-QUERY.md'))
        self.assertTrue(allowed('GROK_WAR_PROMPT.md'))
        self.assertTrue(allowed('CHATGPT-MCP.md'))
        self.assertTrue(allowed('bridge/replay_query.py'))
        self.assertTrue(allowed('bridge/war_sync.py'))
        self.assertTrue(allowed('bridge/war_server.py'))
        self.assertTrue(allowed('bridge/sgi_war_cli.py'))
        self.assertTrue(allowed('REPLAY.md'))
        self.assertTrue(allowed('app/panorama_replay.py'))
        self.assertTrue(allowed('bridge/game_archive.py'))
        self.assertTrue(allowed('app/demo_replay_match/manifest.json'))
        self.assertTrue(allowed('app/demo_replay_match/frames.jsonl'))
        self.assertTrue(allowed('room_monitor/sgi_room_monitor/main_lobby.py'))
        self.assertTrue(allowed('room_monitor/sgi_room_monitor/lobby_ops.py'))
        self.assertTrue(allowed('room_monitor/tests/test_main_lobby.py'))
        self.assertFalse(allowed('room_monitor/sgi_room_monitor/credentials.json'))
        self.assertFalse(allowed('room_monitor/main-credentials.json'))

    def test_settings_preserve_audio_original(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
        from room_watch_settings import load,save,update,read_file
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'room-watch.local.json'
            update(path,audio_original=1)
            save(path,5,3)
            self.assertEqual(load(path),(5,3))
            self.assertEqual(read_file(path)['audio_original'],1)

    def test_audio_restore_does_not_guess(self):
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from room_watch_audio import read_play_bgm, write_play_bgm
        text=';背景音乐开关，0=关闭，1=打开\r\nPlayBGM=1\r\nPlaySE=1\r\n'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Setting.ini'
            path.write_bytes(text.encode('gbk'))
            self.assertEqual(read_play_bgm(path)[0],1)
            write_play_bgm(path,0)
            self.assertEqual(read_play_bgm(path)[0],0)
            write_play_bgm(path,1)
            raw=path.read_bytes()
            self.assertEqual(raw.decode('gbk').count('PlayBGM=1'),1)
            self.assertIn('PlaySE=1',raw.decode('gbk'))
            self.assertIn('背景音乐',raw.decode('gbk'))
        from room_watch_audio import resolve_setting_ini, setting_candidates
        with tempfile.TemporaryDirectory() as directory:
            exe=Path(directory)/'SANPK.exe'
            ini=Path(directory)/'Setting.ini'
            ini.write_bytes(text.encode('gbk'))
            self.assertEqual(resolve_setting_ini(str(exe), None), ini)
            with patch.dict(os.environ, {'SGI_GAME_EXE': str(exe)}, clear=False):
                self.assertEqual(resolve_setting_ini(None, None), ini)
        with patch.object(sys,'platform','win32'):
            paths=[str(path) for path in setting_candidates(None, None)]
            self.assertTrue(any(path.endswith('3I\\Setting.ini') or path.endswith('3I/Setting.ini') for path in paths))

    def test_quiet_and_reveal_flags(self):
        path=Path(__file__).resolve().parents[1]/'app/room_watch.py'
        sys.path.insert(0,str(path.parent))
        spec=importlib.util.spec_from_file_location('room_watch_flags',path)
        app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
        with patch.object(sys,'platform','win32'), patch.object(app,'wine_prefix',return_value=None):
            quiet,_=app.command(True,quiet=True)
            reveal,_=app.command(False,reveal=True)
            cache,_=app.command(False)
            inspect,_=app.command(False,inspect=True)
        self.assertIn('--refresh',quiet)
        self.assertIn('--quiet',quiet)
        self.assertIn('--reveal',reveal)
        self.assertNotIn('--refresh',reveal)
        self.assertIn('--inspect',inspect)
        self.assertNotIn('--refresh',inspect)
        self.assertTrue(str(cache[-1]).endswith('room_list_reader.py'))
        self.assertNotIn('--quiet',cache)

    def test_alert_uses_host_sound_not_game_ini(self):
        path=Path(__file__).resolve().parents[1]/'app/room_watch.py'
        source=path.read_text(encoding='utf-8')
        self.assertIn('afplay',source)
        self.assertIn('Ping.aiff',source)
        self.assertIn('mute_bgm',source)
        self.assertIn('只阻止下一首',source)
        self.assertNotIn('WriteProcessMemory',source)

    def test_launchers_do_not_autowatch(self):
        root=Path(__file__).resolve().parents[1]
        hub=(root/'app/mac_main.py').read_text(encoding='utf-8')
        self.assertNotIn('本机房间人数',hub)
        self.assertNotIn('安静等待',hub)
        self.assertNotIn('--watch',hub)
        launcher=(root/'Start-Room-Watch.command').read_text(encoding='utf-8')
        self.assertIn('exec "$PY" -B app/room_watch.py',launcher)
        self.assertNotIn('room_watch.py --watch',launcher)
        win=(root/'Start-Room-Watch.cmd').read_text(encoding='utf-8')
        self.assertNotIn('--watch',win)
        quiet=(root/'Start-Quiet-Wait.command').read_text(encoding='utf-8')
        self.assertIn('quiet_wait_launch.py',quiet)
        self.assertNotIn('room_watch.py --watch',quiet)
        nav=(root/'app/wine_nav.py').read_text(encoding='utf-8')
        self.assertIn('安静等待',nav)
        self.assertIn('本机房间人数',nav)
        self.assertIn('全景地图',nav)
        self.assertIn('spawn_detached',nav)
        self.assertTrue((root/'Start-Wine-Nav.command').is_file())
        self.assertTrue((root/'Start-Wine-Nav.cmd').is_file())
        launch=(root/'app/quiet_wait_launch.py').read_text(encoding='utf-8')
        self.assertNotIn('WriteProcessMemory',launch)
        self.assertIn('start_new_session',launch)
        self.assertIn('0x00000008',launch)
        self.assertIn('SGI_ROOM_WATCH_RESUME',launch)

    def test_command_is_game_ignores_helpers(self):
        from room_watch_audio import command_is_game
        self.assertTrue(command_is_game('./3I\\SANPK.exe /1an','SANPK.exe'))
        self.assertTrue(command_is_game('/Users/x/drive_c/sgi/run-3.5/SANGUO.exe','SANGUO.exe'))
        self.assertTrue(command_is_game('/Users/vk/Library/Application Support/SGI-Wine/prefix/drive_c/sgi/run-3.5/SANGUO.exe','SANGUO.exe'))
        self.assertFalse(command_is_game('python.exe Z:\\\\scripts\\\\sgi_wine_process_watch.py C:\\\\sgi\\\\run-3.5\\\\3I\\\\SANPK.exe','SANPK.exe'))
        self.assertFalse(command_is_game('python3 -B app/room_watch.py --watch','SANPK.exe'))
        self.assertFalse(command_is_game("pgrep -lf 'SANGUO.exe|SANPK.exe'",'SANPK.exe'))
        self.assertFalse(command_is_game("ps -axo command | awk '/SANPK.exe/'",'SANPK.exe'))
        self.assertFalse(command_is_game('SANPK.exe','SANGUO.exe'))
        self.assertTrue(command_is_game('SANPK.exe','SANPK.exe'))

    def test_quiet_wait_plan_does_not_touch_running_game(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
        from quiet_wait_launch import command_is_observer, plan
        self.assertTrue(command_is_observer('Python -B app/room_watch.py --quiet-wait'))
        self.assertFalse(command_is_observer('python3 -B app/quiet_wait_launch.py'))
        self.assertFalse(command_is_observer("pgrep -lf room_watch.py"))
        already=plan({'observer':True,'sanpk':False,'lobby':True},platform='darwin')
        self.assertFalse(already['prepare'])
        self.assertFalse(already['launch_lobby'])
        self.assertFalse(already['watch'])
        self.assertEqual(already['mode'],'already_open')
        blocked=plan({'sanpk':True,'lobby':True},platform='darwin')
        self.assertFalse(blocked['prepare'])
        self.assertFalse(blocked['launch_lobby'])
        self.assertEqual(blocked['mode'],'observe_existing')
        ready=plan({'sanpk':False,'lobby':False},platform='darwin')
        self.assertTrue(ready['prepare'])
        self.assertTrue(ready['launch_lobby'])
        self.assertEqual(ready['mode'],'quiet_wait')
        windows=plan({'sanpk':False,'lobby':False},platform='win32')
        self.assertTrue(windows['prepare'])
        self.assertFalse(windows['launch_lobby'])
        lobby_only=plan({'sanpk':False,'lobby':True},platform='darwin')
        self.assertTrue(lobby_only['prepare'])
        self.assertFalse(lobby_only['launch_lobby'])
        launch=(Path(__file__).resolve().parents[1]/'app/quiet_wait_launch.py').read_text(encoding='utf-8')
        self.assertIn('open_watch(True)',launch)
        self.assertNotIn("open_watch(step['mode'] == 'quiet_wait')",launch)
        self.assertIn("step['mode'] == 'already_open'",launch)

    def test_prepare_quiet_launch_saves_original(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
        from quiet_wait_launch import prepare_quiet_launch
        from room_watch_settings import read_file
        from room_watch_audio import read_play_bgm
        text=';背景音乐开关，0=关闭，1=打开\r\nPlayBGM=1\r\nPlaySE=1\r\n'
        with tempfile.TemporaryDirectory() as directory:
            ini=Path(directory)/'Setting.ini'
            settings=Path(directory)/'room-watch.local.json'
            ini.write_bytes(text.encode('gbk'))
            self.assertEqual(prepare_quiet_launch(settings,ini),1)
            self.assertEqual(read_play_bgm(ini)[0],0)
            self.assertEqual(read_file(settings)['audio_original'],1)
            self.assertTrue(read_file(settings)['quiet_launch'])
            self.assertIn('PlaySE=1',ini.read_bytes().decode('gbk'))
            prepare_quiet_launch(settings,ini)
            self.assertEqual(read_file(settings)['audio_original'],1)

    def test_quiet_wait_keeps_ini_until_restore(self):
        from room_watch_audio import should_restore_audio_on_exit
        self.assertFalse(should_restore_audio_on_exit({'quiet_launch':True},False))
        self.assertTrue(should_restore_audio_on_exit({'quiet_launch':True},True))
        self.assertTrue(should_restore_audio_on_exit({'quiet_launch':False},False))
        source=(Path(__file__).resolve().parents[1]/'app/room_watch.py').read_text(encoding='utf-8')
        self.assertIn('waiting_lobby',source)
        self.assertIn('sanpk_running()',source)
        self.assertNotIn('if not reveal and not sanpk_running()',source)
        self.assertIn('snapshot_without_game',source)
        from room_watch_audio import waiting_status
        self.assertIn('对战平台未运行',waiting_status(False,False))
        self.assertIn('进入游戏选择',waiting_status(False,True))
        self.assertIsNone(waiting_status(True,True))

    def test_waiting_polls_sooner_than_refresh(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
        from room_watch import next_poll_delay, should_apply_mute_after, should_keep_waiting
        self.assertEqual(next_poll_delay('waiting_lobby'),2.0)
        self.assertEqual(next_poll_delay('unavailable','已离开游戏选择，观察已暂停',True),2.0)
        self.assertEqual(next_poll_delay('unavailable','无法唯一识别房间列表对象',True),2.0)
        self.assertEqual(next_poll_delay('unavailable','列表刷新中，请稍候',True),2.0)
        self.assertEqual(next_poll_delay('fresh','后台搜索回复人数（含房主）',True),20.0)
        self.assertEqual(next_poll_delay('unavailable','窗口布局不匹配',True),20.0)
        self.assertEqual(next_poll_delay('unavailable','游戏版本未核验，不读取人数',True),20.0)
        self.assertFalse(should_keep_waiting('unavailable','无法唯一识别房间列表对象',False))
        self.assertTrue(should_keep_waiting('unavailable','观察进程超时，本轮未标为实时',True))
        self.assertTrue(should_keep_waiting('unavailable','观察进程退出；游戏进程未被终止',True))
        self.assertTrue(should_keep_waiting('unavailable','窗口已变化，已停止刷新',True))
        self.assertFalse(should_keep_waiting('unavailable','窗口已变化，已停止刷新',False))
        self.assertEqual(next_poll_delay('unavailable','窗口已变化，已停止刷新',True),2.0)
        self.assertEqual(next_poll_delay('unavailable','观察进程超时，本轮未标为实时',True),2.0)
        self.assertTrue(should_apply_mute_after({'status':'fresh','quiet':True},False,False))
        self.assertFalse(should_apply_mute_after({'status':'waiting_lobby','quiet':False},False,False))
        self.assertFalse(should_apply_mute_after({'status':'fresh','quiet':True},False,True))
        self.assertFalse(should_apply_mute_after({'status':'fresh','quiet':False},False,False))
        watch=(Path(__file__).resolve().parents[1]/'app/room_watch.py').read_text(encoding='utf-8')
        self.assertNotIn("elif value.get('quiet')",watch)
        self.assertNotIn('quiet_wait or running.get()',watch)
        self.assertIn('auto_refresh_keep(running.get())',watch)
        from room_watch import auto_refresh_keep
        self.assertTrue(auto_refresh_keep(True))
        self.assertFalse(auto_refresh_keep(False))
        self.assertTrue(should_keep_waiting('unavailable','观察进程超时，本轮未标为实时',auto_refresh_keep(True)))
        self.assertFalse(should_keep_waiting('unavailable','观察进程超时，本轮未标为实时',auto_refresh_keep(False)))
        self.assertIn('should_apply_mute_after(value',watch)
        self.assertIn('snapshot_for_alerts(value)',watch)
        self.assertIn('PROBE_TIMEOUT',watch)
        self.assertIn('TimeoutExpired',watch)
        self.assertNotIn('timeout=20',watch)
        self.assertIn('def kill_probe',watch)
        self.assertIn('os.killpg',watch)
        self.assertIn('start_new_session',watch)
        self.assertNotIn('SANPK',watch[watch.find('def kill_probe'):watch.find('def probe')])
        from room_watch import snapshot_without_game
        idle=snapshot_without_game(False,False)
        self.assertEqual(idle['status'],'waiting_lobby')
        self.assertIn('未代为启动',idle['message'])
        self.assertEqual(idle['rooms'],[])
        shown=snapshot_without_game(True,True)
        self.assertEqual(shown['status'],'waiting_lobby')
        self.assertIn('未探窗口',shown['message'])
        self.assertIn('进入游戏选择',shown['message'])

    @unittest.skipUnless(sys.platform == 'darwin', 'frontmost restore is macOS-only')
    def test_focus_restore_only_when_self_stole_it(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
        from room_watch import should_log_snapshot
        from room_watch_focus import adopt_resume, is_helper_front, is_locked_session, is_self_front, is_self_or_wine, parse_lsappinfo, restore_frontmost, usable_resume
        from room_watch_focus import resume_env_value, resume_from_env
        sample='"LSDisplayName"="QQ"\n"pid"=68619\n"CFBundleIdentifier"="com.tencent.qq"\n'
        saved=parse_lsappinfo(sample)
        self.assertEqual(saved['pid'],68619)
        self.assertEqual(saved['bundle'],'com.tencent.qq')
        self.assertFalse(is_self_front(saved,1))
        self.assertTrue(is_self_front({'pid':9,'name':'Python'},9))
        self.assertFalse(is_self_front({'pid':26669,'name':'Python'},25058))
        self.assertTrue(is_self_or_wine({'pid':9,'name':'wine64-preloader'},1))
        self.assertFalse(is_self_or_wine({'pid':26669,'name':'Python'},25058))
        wine_calls=[]
        self.assertTrue(restore_frontmost(saved,current={'pid':80,'name':'wine64-preloader'},self_pid=1,
                                         activate=lambda pid:wine_calls.append(pid) or True,
                                         stolen_by=is_self_or_wine))
        self.assertEqual(wine_calls,[68619])
        calls=[]
        self.assertTrue(restore_frontmost(saved,current={'pid':1,'name':'Python'},self_pid=1,
                                         activate=lambda pid:calls.append(pid) or True))
        self.assertEqual(calls,[68619])
        self.assertFalse(restore_frontmost(saved,current={'pid':26669,'name':'Python'},self_pid=1,
                                          activate=lambda pid:calls.append(pid) or True))
        self.assertFalse(restore_frontmost({'pid':1,'bundle':'org.python.python'},
                                          current={'pid':1,'name':'Python'},self_pid=1))
        lock={'pid':403,'name':'loginwindow','bundle':'com.apple.loginwindow'}
        self.assertTrue(is_locked_session(lock))
        lock_calls=[]
        self.assertFalse(restore_frontmost(lock,current={'pid':80,'name':'wine64-preloader'},self_pid=1,
                                           activate=lambda pid:lock_calls.append(pid) or True,
                                           stolen_by=is_self_or_wine))
        self.assertEqual(lock_calls,[])
        qq={'pid':68619,'name':'QQ','bundle':'com.tencent.qq'}
        safari={'pid':900,'name':'Safari','bundle':'com.apple.Safari'}
        wine={'pid':80,'name':'wine64-preloader'}
        self.assertFalse(usable_resume(lock,1))
        self.assertFalse(usable_resume(wine,1))
        self.assertTrue(usable_resume(qq,1))
        helper={'pid':902,'name':'通用控制','bundle':'com.apple.universalcontrol'}
        self.assertTrue(is_helper_front(helper))
        self.assertFalse(usable_resume(helper,1))
        self.assertIsNone(adopt_resume(helper,current=wine,self_pid=1))
        self.assertEqual(adopt_resume(helper,current=qq,self_pid=1)['pid'],68619)
        helper_calls=[]
        self.assertFalse(restore_frontmost(helper,current={'pid':80,'name':'wine64-preloader'},self_pid=1,
                                           activate=lambda pid:helper_calls.append(pid) or True,
                                           stolen_by=is_self_or_wine))
        self.assertEqual(helper_calls,[])
        self.assertEqual(adopt_resume(lock,current=qq,self_pid=1)['pid'],68619)
        self.assertEqual(adopt_resume(qq,current=wine,self_pid=1)['pid'],68619)
        self.assertEqual(adopt_resume(qq,current=safari,self_pid=1)['pid'],900)
        self.assertEqual(adopt_resume(lock,current=lock,self_pid=1)['name'],'loginwindow')
        self.assertEqual(adopt_resume(lock,current=wine,self_pid=1)['name'],'loginwindow')
        self.assertEqual(adopt_resume(None,current=qq,self_pid=1)['bundle'],'com.tencent.qq')
        self.assertEqual(adopt_resume(lock,current=None,self_pid=1,capture=lambda:qq)['pid'],68619)
        self.assertTrue(should_log_snapshot('fresh','ok'))
        self.assertTrue(should_log_snapshot('waiting_lobby','wait'))
        self.assertFalse(should_log_snapshot('waiting_lobby','wait','waiting_lobby','wait',3))
        self.assertTrue(should_log_snapshot('waiting_lobby','wait','waiting_lobby','wait',60))
        from room_watch_focus import apply_win32_noactivate, WS_EX_NOACTIVATE, GWL_EXSTYLE
        written=[]
        self.assertTrue(apply_win32_noactivate(42, lambda hwnd, idx: 0x100,
                                               lambda hwnd, idx, value: written.append((hwnd, idx, value))))
        self.assertEqual(written, [(42, GWL_EXSTYLE, 0x100 | WS_EX_NOACTIVATE)])
        source=(Path(__file__).resolve().parents[1]/'app/room_watch_focus.py').read_text(encoding='utf-8')
        self.assertNotIn('SetForegroundWindow',source)
        self.assertIn('WS_EX_NOACTIVATE',source)
        self.assertIn('apply_win32_noactivate',source)
        watch=(Path(__file__).resolve().parents[1]/'app/room_watch.py').read_text(encoding='utf-8')
        self.assertIn('restore_frontmost(resume)',watch)
        self.assertIn("sys.platform!='darwin'",watch)
        self.assertLess(watch.find('acquire_lock()'),watch.find('tk.Tk()'))
        from room_watch import acquire_lock
        with tempfile.TemporaryDirectory() as directory:
            lock_path=Path(directory)/'room-watch.lock'
            held=acquire_lock(lock_path)
            try:
                with self.assertRaises(OSError):
                    acquire_lock(lock_path)
            finally:
                held.close()
            again=acquire_lock(lock_path)
            again.close()
        self.assertNotIn("messagebox.showinfo('房间观察'",watch)
        self.assertIn('notify_already_running()',watch)
        self.assertIn('apply_nonactivating_window',watch)
        self.assertIn('root.withdraw()',watch)
        self.assertIn('resume_from_env()',watch)
        self.assertIn('adopt_resume(state.get(\'resume\'))',watch)
        self.assertIn("'resume':resume",watch)
        self.assertLess(watch.find('except queue.Empty'),watch.find("state['resume']=adopt_resume"))
        self.assertLess(watch.find('root.withdraw()'),watch.find('root.deiconify()'))
        encoded=resume_env_value({'pid':68619,'name':'QQ','bundle':'com.tencent.qq'})
        saved=resume_from_env({'SGI_ROOM_WATCH_RESUME':encoded})
        self.assertEqual(saved['pid'],68619)
        self.assertEqual(saved['bundle'],'com.tencent.qq')
        self.assertIsNone(resume_from_env({}))
        self.assertIsNone(resume_from_env({'SGI_ROOM_WATCH_RESUME':'{}'}))
        focus=(Path(__file__).resolve().parents[1]/'app/room_watch_focus.py').read_text(encoding='utf-8')
        self.assertIn('MacWindowStyle',focus)
        self.assertIn('noActivates',focus)
        self.assertIn('SGI_ROOM_WATCH_RESUME',focus)

if __name__=='__main__':unittest.main()
