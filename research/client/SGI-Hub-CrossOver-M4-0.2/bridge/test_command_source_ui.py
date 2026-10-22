"""Compact phase timelines keep source information in evidence details."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
BRIDGE = ROOT / 'bridge'
for path in (str(APP), str(BRIDGE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import tkinter as tk

MARKER = '源语义测试城'
UNIT = '源语义测试出征部队'
GENERAL = '源语义测试将'


def observed_history():
    return {
        'quarters': [{
            'label': '200年春 · 内政',
            'phase': {'year_u16': 200, 'season_u16': 0},
            'closed': True,
            'forces': [{
                'owner': 7,
                'operations': [
                    {
                        'field': '新建练兵所',
                        'line': f'新建练兵所：{MARKER}',
                        'command': True,
                        'places': [MARKER],
                    },
                    {
                        'field': '出征',
                        'line': f'出征 {UNIT}',
                        'command': True,
                        'target': {'kind': 'field_units', 'unit_id': 9},
                    },
                    {
                        'field': '录用',
                        'line': f'录用 {GENERAL}：洛阳',
                        'command': True,
                        'after': GENERAL,
                        'hire_kind': '募将',
                        'target': {'general_id': 41},
                    },
                ],
            }],
        }],
    }


class CommandSourceUi(unittest.TestCase):
    def test_sortie_stats_diplomatic_reply_and_join_share_civil_without_extra_numbers(self):
        from quarter_ops_panel import QuarterOpsPanel
        from test_action_timeline import fixture
        row,item,history,entities=fixture()
        reply=dict(row,native_type=19,subtype=1,flags_raw=[30,0,0,0,0],other_raw=16,other2_raw=-1)
        join=dict(row,native_type=20,subtype=1,target_raw=554,action='接纳仕官')
        panel=QuarterOpsPanel(self.root)
        panel.update_force({'force_id':5},dict(history=history,entities=entities,
            native_command_evidence={'rows':[row,reply,join]}))
        civil=panel.input_log.get('1.0','end')
        self.assertIn('1. 出征 步兵#0（老子）',civil)
        self.assertIn('攻击54',civil);self.assertIn('训练50/100',civil)
        self.assertNotIn('封包',civil);self.assertNotIn('观察',civil)
        self.assertIn('封包＋观察',panel._input_details)
        self.assertIn('外交回应 接受 → 代',civil)
        self.assertIn('自动加入：老子',civil)
        self.assertNotIn('不占指令',civil)
        self.assertNotIn('2. ',civil)
        self.assertNotIn('出征',panel.military_log.get('1.0','end'))

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_peer_summer_remains_a_separate_verified_source_in_compact_view(self):
        from quarter_ops_panel import QuarterOpsPanel
        from native_command_evidence import decode
        from test_native_command_evidence import packet
        panel=QuarterOpsPanel(self.root)
        row=decode(packet(subtype=2,actor=7))
        row.update(observed_at='2026-10-10T09:02:00+00:00',
                   sampling_calendar={'year_u16':202,'season_u16':1,'basis':'sampling_time_correlation'})
        state={'native_command_evidence':{'binding':{'source_id':'PRIMARY'},'rows':[],
               'supplemental_sources':[{'binding':{'source_id':'COM'},'rows':[row]}]}}
        panel.update_force({'force_id':7},state)
        text=panel.input_log.get('1.0','end')
        self.assertIn('202年夏',text);self.assertIn('1. 施舍',text)
        self.assertNotIn('另端补充',text)
        self.assertIn('另端补充：COM',panel._input_details)
        self.assertIn('采集来源：COM',panel._input_details)
        self.assertEqual(state['native_command_evidence']['rows'],[])

    def test_two_phase_pages_merge_history_with_observation_sources_in_details(self):
        from quarter_ops_panel import QuarterOpsPanel
        panel = QuarterOpsPanel(self.root)
        panel.pack(); self.root.update_idletasks()
        self.assertEqual([panel.lane_book.tab(t, 'text') for t in panel.lane_book.tabs()],
                         ['内政阶段', '军事阶段'])
        self.assertEqual(panel.lane_book.select(), str(panel.civil_page))
        panel.update_force({'force_id': 7}, {'history': observed_history()})
        civil = panel.log.get('1.0', 'end')
        military = panel.military_log.get('1.0', 'end')
        self.assertTrue(civil.startswith('内政指令'))
        self.assertTrue(military.startswith('军事指令'))
        for value in (MARKER, UNIT, GENERAL, '200年春'):
            self.assertIn(value, civil)
        self.assertNotIn(UNIT, military)  # 出征 consumes a civil order.
        self.assertNotIn('封包', civil);self.assertNotIn('[观察]',civil)
        self.assertIn('观察：',panel._input_details)
        self.assertNotIn('暂无指令', civil + military)
        self.assertIn('不能当成原始指令', panel._input_details)

    def test_local_input_page_shows_only_selected_force_parameters_without_claiming_commit(self):
        from quarter_ops_panel import QuarterOpsPanel
        panel=QuarterOpsPanel(self.root)
        row=dict(scope={'force_id':7},observed_at='2026-10-10T08:29:37+00:00',action='infantry',
                 operand_before=80,operand_after=240,omitted_intermediate_operands=0)
        state={'history':observed_history(),'local_input_evidence':{'rows':[row]}}
        panel.update_force({'force_id':7},state)
        text=panel.input_log.get('1.0','end')
        self.assertIn('80→240',panel._input_details);self.assertIn('未确认',panel._input_details)
        self.assertNotIn('80→240',text)
        self.assertIn(MARKER,text);self.assertNotIn('[观察]',text)
        panel.update_force({'force_id':8},state)
        self.assertNotIn('80→240',panel._input_details)
        self.assertIn('暂无记录',panel.input_log.get('1.0','end'))
        panel.update_force({'force_id':7},{'history':observed_history()})
        self.assertNotIn('80→240',panel._input_details)

    def test_native_packets_are_force_filtered_and_independent_of_modifier_receipts(self):
        from quarter_ops_panel import QuarterOpsPanel
        from native_command_evidence import decode
        from test_native_command_evidence import packet
        row=dict(decode(packet('CSanInetDiplomacyCmd',4,actor=7)),observed_at='2026-10-10T09:02:00+00:00')
        commands=dict(rows=[row],capture_status={'phase':'waiting','error':'stale'})
        panel=QuarterOpsPanel(self.root)
        panel.update_force({'force_id':7},{'native_command_evidence':commands})
        text=panel.input_log.get('1.0','end')
        self.assertIn('外交卡排序',text);self.assertNotIn('26、12、24、13',text)
        self.assertIn('日期未确认',text);self.assertNotIn('实时采样中断',text);self.assertIn('实时采样中断',panel._input_details)
        self.assertIn('26、12、24、13',panel._input_details)
        self.assertNotIn('80→240',text)
        panel.update_force({'force_id':8},{'native_command_evidence':commands})
        self.assertNotIn('外交卡排序',panel.input_log.get('1.0','end'))

    def test_compact_date_lanes_and_details_remain_separate_on_refresh(self):
        from quarter_ops_panel import QuarterOpsPanel
        from native_command_evidence import decode
        from test_native_command_evidence import packet
        from test_command_display import window
        panel=QuarterOpsPanel(self.root)
        row=dict(decode(packet('CSanInetPersonnelCmd',5,actor=7)),
                 observed_at='2026-10-10T08:30:00+00:00',source_file='original.jsonl',raw_sha256='preserved')
        state=dict(native_command_evidence={'rows':[row]},
                   history={'quarters':[window(1,'08:00:00','09:00:00')]})
        panel.update_force({'force_id':7},state)
        text=panel.input_log.get('1.0','end')
        self.assertIn('内政指令\n200年夏\n1. ▶ 加增（1名武将）',text)
        self.assertIn('军事指令',panel.military_log.get('1.0','end'))
        self.assertNotIn('首次采样',text);self.assertNotIn('原始封包／结算未确认',text)
        panel._show_input_details()
        self.assertIn('首次采样',panel.details_log.get('1.0','end'))
        self.assertIn('original.jsonl',panel.details_log.get('1.0','end'))
        panel.update_force({'force_id':8},state)
        self.assertNotIn('武将#589',panel.details_log.get('1.0','end'))

    def test_additions_fold_to_named_generals_and_keep_expansion_on_refresh(self):
        from quarter_ops_panel import QuarterOpsPanel
        from native_command_evidence import decode
        from test_native_command_evidence import packet
        panel=QuarterOpsPanel(self.root)
        rows=[dict(decode(packet('CSanInetPersonnelCmd',5,actor=7,target=gid)),
                   observed_at='2026-10-10T08:30:00+00:00') for gid in (192,527,238)]
        state={'native_command_evidence':{'rows':rows},'entities':{'generals':[
            {'general_id_raw':192,'name':'司马懿'},{'general_id_raw':527,'name':'曹操'},
            {'general_id_raw':238,'name':'魏王'}]}}
        panel.update_force({'force_id':7},state)
        self.assertIn('1. ▶ 加增（3名武将）',panel.input_log.get('1.0','end'))
        self.assertNotIn('司马懿',panel.input_log.get('1.0','end'))
        tag=next(t for t in panel.input_log.tag_names() if str(t).startswith('command_'))
        callback=panel.input_log.tk.call(panel.input_log._w,'tag','bind',tag,'<Button-1>')
        import re
        command=re.search(r'\[([^\s]+)',callback).group(1)
        panel.input_log.tk.call(command)
        text=panel.input_log.get('1.0','end')
        self.assertIn('1. ▼ 加增（3名武将）',text)
        for name in ('司马懿','曹操','魏王'):self.assertIn('    '+name+'\n',text)
        self.assertNotIn('武将#',text)
        panel.update_force({'force_id':7},state)
        self.assertIn('司马懿',panel.input_log.get('1.0','end'))
        panel.update_force({'force_id':8},state)
        self.assertNotIn('司马懿',panel.input_log.get('1.0','end'))

    def test_numbered_values_red_badge_and_force_art_survive_refresh(self):
        from quarter_ops_panel import QuarterOpsPanel
        from test_command_effects import fixture
        from force_card_art import ForceCardArtwork
        from PIL import ImageTk
        row,history=fixture();row['extra_raw']=22
        panel=QuarterOpsPanel(self.root)
        state={'native_command_evidence':{'rows':[row]},'history':history}
        panel.update_force({'force_id':11},state)
        self.assertIn('1. 施舍 信望 140→146（+6）  [外挂]',panel.input_log.get('1.0','end'))
        self.assertEqual(panel.input_log.tag_cget('cheat','foreground'),'#b11a1a')
        self.assertTrue(panel.input_log.tag_ranges('cheat'))
        art=ForceCardArtwork(self.root);force={'force_id':11,'name':'宋'}
        plain=art.row(force,'#aa0000',False,11)
        marked=art.row(force,'#aa0000',False,11,modified=True)
        self.assertIsNot(plain,marked)
        image=ImageTk.getimage(marked)
        self.assertEqual(image.getpixel((4,41))[:3],(177,26,26))
        self.assertIs(marked,art.row(force,'#aa0000',False,11,modified=True))
        panel.update_force({'force_id':0},state)
        self.assertNotIn('[外挂]',panel.input_log.get('1.0','end'))

    def test_offline_command_pane_restores_dates_without_restoring_a_game_snapshot(self):
        from tkinter import ttk
        from omni_window import OmniWindow
        from quarter_ops_panel import QuarterOpsPanel
        from native_command_evidence import decode
        from test_native_command_evidence import packet

        class Host:
            show_retained_commands=OmniWindow.show_retained_commands
            render_retained_commands=OmniWindow.render_retained_commands
            tick=OmniWindow.tick

        host=Host();host.doc=None;host.sel=None;host.retained_command_view=None
        host.force_tree=ttk.Treeview(self.root,columns=('force','a','b','c','d','e'))
        host.workspace=ttk.Notebook(self.root);host.force_page=tk.Frame(host.workspace)
        host.workspace.add(host.force_page,text='势力情报')
        host.book=ttk.Notebook(host.force_page);page=tk.Frame(host.book);host.book.add(page,text='变化')
        host.quarter_ops=QuarterOpsPanel(page)
        from training_record_panel import TrainingRecordPanel
        host.training_record=TrainingRecordPanel(host.force_page)
        for name in ('identity_label','summary','heading'):
            setattr(host,name,tk.Label(self.root))
        host.confirm_btn=tk.Button(self.root);host.reidentify_btn=tk.Button(self.root)
        row=dict(decode(packet()),observed_at='2026-10-10T09:02:24+00:00',
                 sampling_calendar={'year_u16':201,'season_u16':0,'basis':'sampling_time_correlation'})
        import queue,threading
        host.root=self.root;host.review=None;host.inbox=queue.Queue();host.stop=threading.Event();host.stop.set()
        host.status=tk.Label(self.root)
        bundle=dict(force_names={'16':'代'},selected_force_id=16,native_command_evidence={'rows':[row]})
        host.inbox.put(dict(fresh=False,phase='waiting_for_player',state={'unconfirmed_lobby':True},
                            retained_command_view=bundle))
        host.tick()
        self.assertIsNone(host.doc)
        self.assertIn('201年春',host.quarter_ops.input_log.get('1.0','end'))
        self.assertEqual(host.force_tree.selection(),('16',))
        self.assertEqual(host.confirm_btn.cget('state'),'disabled')
        self.assertIn('保留',host.identity_label.cget('text'))
        self.assertIn('累计记录',host.training_record.activity.cget('text'))
        self.assertEqual(host.training_record.samples,[])

    def test_refresh_keeps_the_page_the_user_picked(self):
        from quarter_ops_panel import QuarterOpsPanel

        panel = QuarterOpsPanel(self.root)
        panel.pack()
        self.root.update_idletasks()
        panel.lane_book.select(panel.civil_page)
        self.root.update_idletasks()
        panel.update_force({'force_id': 7}, {'history': observed_history()})
        self.assertEqual(panel.lane_book.select(), str(panel.civil_page))
        panel.lane_book.select(panel.military_page)
        panel.update_force({'force_id': 8}, {'history': observed_history()})
        panel.update_force({'force_id': 8}, {'history': observed_history()})
        self.assertEqual(panel.lane_book.select(), str(panel.military_page))
        self.assertTrue(panel.input_log.get('1.0', 'end').startswith('内政指令'))

    def test_empty_observation_does_not_claim_there_was_no_order(self):
        from quarter_ops_panel import HIRES_BANNER, OBS_BANNER, OBS_EMPTY, QuarterOpsPanel

        panel = QuarterOpsPanel(self.root)
        panel.update_force({'force_id': 1}, {'history': {}})
        raw_empty = panel.raw_log.get('1.0', 'end')
        self.assertTrue(raw_empty.startswith('内政指令'))
        self.assertIn('暂无记录', raw_empty)
        self.assertNotIn('暂无指令', raw_empty)
        for widget,title in ((panel.log,'内政指令'), (panel.military_log,'军事指令')):
            text = widget.get('1.0', 'end')
            self.assertTrue(text.startswith(title))
            self.assertIn('暂无记录', text)
            self.assertNotIn('暂无指令', text)
        hires = QuarterOpsPanel(self.root, hires_only=True)
        self.assertIsNone(hires.lane_book)
        hires.update_force({'force_id': 7}, {'history': observed_history()})
        filled = hires.log.get('1.0', 'end')
        self.assertTrue(filled.startswith(HIRES_BANNER))
        self.assertIn(GENERAL, filled)
        self.assertNotIn('暂无招募', filled)
        blank = QuarterOpsPanel(self.root, hires_only=True)
        blank.update_force({'force_id': 1}, {'history': {'quarters': []}})
        empty = blank.log.get('1.0', 'end')
        self.assertTrue(empty.startswith(HIRES_BANNER))
        self.assertIn(OBS_EMPTY, empty)
        self.assertNotIn(GENERAL, empty)
        self.assertNotIn('暂无招募', empty)

    def test_replay_inference_never_renders_as_raw(self):
        from panorama_replay import (
            OBS_EMPTY, OPS_INFER_NOTE, OPS_INFER_TITLE, OPS_RAW_NOTE, OPS_RAW_TITLE,
            ReplayApp, ops_source_header,
        )

        frame = tk.Frame(self.root)
        raw_title, infer_note = ops_source_header(frame, 'PingFang SC')
        self.assertEqual(raw_title.cget('text'), '原始指令：未捕获')
        self.assertEqual(raw_title.cget('text'), OPS_RAW_TITLE)
        self.assertIn(OPS_INFER_TITLE, infer_note.cget('text'))
        self.assertEqual(infer_note.cget('text'), OPS_INFER_NOTE)
        self.assertNotIn(OBS_EMPTY, infer_note.cget('text'))
        ops = tk.Text(self.root)
        for tag in ('head', 'unknown', 'force', 'empty', 'quarter', 'lane', 'fact', 'inferred', 'observed_change'):
            ops.tag_configure(tag)

        class Host:
            _fill_lane = ReplayApp._fill_lane

            def __init__(self, widget):
                self.ops = widget

            def _goto_item(self, _item):
                return None

        host = Host(ops)
        ledger = [{
            'heading': '蜀',
            'quarters': [{
                'label': '200年春 · 内政',
                'phase': {'year_u16': 200, 'season_u16': 0},
                'civil': [{
                    'field': '新建练兵所',
                    'line': f'新建练兵所：{MARKER}',
                    'command': True,
                    'evidence': 'inferred',
                    'evidence_cn': '推断',
                    'seq': 12,
                }],
                'military': [{
                    'field': '出征',
                    'line': f'出征 {UNIT}',
                    'command': True,
                    'evidence': 'fact',
                    'evidence_cn': '事实',
                    'seq': 13,
                }],
            }],
        }]
        ReplayApp._fill_ops(host, {'gaps': []}, ledger)
        text = ops.get('1.0', 'end')
        raw, found, rest = text.partition(OPS_INFER_TITLE)
        self.assertTrue(found)
        self.assertIn(OPS_RAW_TITLE, raw)
        self.assertIn(OPS_RAW_NOTE, raw)
        self.assertNotIn(MARKER, raw)
        self.assertNotIn(UNIT, raw)
        self.assertNotIn('command', raw)
        self.assertNotIn('原始指令', rest)
        self.assertIn('内政观察', rest)
        self.assertIn('军事观察', rest)
        self.assertNotIn(OBS_EMPTY, text)
        self.assertIn(MARKER, rest)
        self.assertIn('[推断]', rest)
        self.assertIn(UNIT, rest)
        self.assertIn('[事实]', rest)
        self.assertNotIn('尚无建设/训练/录用/出征/移动', text)
        ReplayApp._fill_ops(host, {'gaps': []}, [{'heading': '吴', 'quarters': []}])
        empty = ops.get('1.0', 'end')
        raw_empty, _, infer_empty = empty.partition(OPS_INFER_TITLE)
        self.assertNotIn(MARKER, raw_empty)
        self.assertNotIn('出征', raw_empty)
        self.assertIn(OBS_EMPTY, infer_empty)
        self.assertNotIn('尚无建设/训练/录用/出征/移动', empty)


if __name__ == '__main__':
    unittest.main()
