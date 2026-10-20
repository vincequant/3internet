"""Mapped reuse of the actual original force widgets, without any live reader."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'app'), str(ROOT/'bridge')]
from card_state import decode_hand
from fengye_force_views import mount_force_views, update_force_views
from omni_window import OmniWindow


def payload(key='game-one', gold=12345):
    force = {'force_id': 3, 'name': '齊', 'prestige': 64, 'gold': gold, 'rice': 95000,
             'color_index_raw': 3, 'ruler_general_id': 65535, 'capital_city_id': 65535,
             'armament_raw': dict.fromkeys(('infantry','cavalry','bow'), 0),
             'troop_stock': dict.fromkeys(('infantry','cavalry','bow'), 1000),
             'training_progress': dict.fromkeys(('infantry','cavalry','bow'), 0),
             'hand_cards': decode_hand(bytes([1,2,0,15,0]))}
    return {'ok': True, 'source_prefix': 'prefix-fengye-shadow', 'game_key': key,
            'state': {'readonly': True, 'snapshot_id': 'frame-'+str(gold),
                      'capture_end': datetime.now(timezone.utc).isoformat(),
                      'clock_candidates': {'year_u16':200,'season_u16':0},
                      'entities': {'lords':[force], 'generals':[], 'field_units':[],
                                   'cities_and_barriers':[], 'production_buildings':[], 'traps':[]}}}


class ReadOnlyOmni(OmniWindow):
    def fetch(self):
        raise AssertionError('Player fetch must never start')

    def tick(self):
        pass


class ForceViewsMappedTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Mapped display unavailable: %s' % exc)
        self.root.geometry('1450x950+3200+2000')
        self.errors=[]
        self.root.report_callback_exception=lambda *error:self.errors.append(error)
        self.addCleanup(self.root.destroy)
        # OmniWindow normally starts its fetch worker. Stop all worker starts
        # during construction so this test cannot open a player source.
        with mock.patch('threading.Thread.start') as starts:
            self.app=ReadOnlyOmni(self.root)
        self.app.original_tabs=list(self.app.workspace.tabs())
        self.console=tk.Frame(self.app.workspace)
        self.app.workspace.add(self.console,text='風夜')
        self.app.control_book=ttk.Notebook(self.console)
        self.app.control_book.pack(fill='both',expand=True)
        self.other=ttk.Frame(self.app.control_book)
        self.app.control_book.add(self.other,text='其他')
        for tab in self.app.original_tabs:self.app.workspace.hide(tab)
        self.app.workspace.select(self.console)
        self.original_info=self.app.force_page
        self.original_compare=self.app.force_compare
        self.original_military=self.app.military
        self.original_quarter=self.app.quarter_ops
        self.hosts=mount_force_views(self.app)
        self.root.update()

    def test_exact_original_widgets_mount_and_both_tabs_are_mapped(self):
        self.assertIs(self.app.force_page,self.original_info)
        self.assertIs(self.app.force_compare,self.original_compare)
        self.assertIs(self.app.military,self.original_military)
        self.assertIs(self.app.quarter_ops,self.original_quarter)
        self.assertEqual([self.app.control_book.tab(h,'text') for h in self.hosts.values()],
                         ['勢力情報','勢力對比'])
        for key,page in (('info',self.original_info),('compare',self.original_compare)):
            self.app.control_book.select(self.hosts[key]);self.root.update()
            self.assertTrue(page.winfo_ismapped())
            self.assertEqual(str(page.pack_info()['in']),str(self.hosts[key]))
        self.assertIs(mount_force_views(self.app),self.hosts)
        self.assertNotIn(str(self.original_info),self.app.original_tabs)
        self.assertEqual(self.errors,[])

    def test_original_pages_are_topmost_not_hidden_by_console_sibling(self):
        self.assertTrue(update_force_views(self.app,payload()))
        for key, tree in (('info',self.app.force_tree),('compare',self.app.force_compare.tree)):
            self.app.control_book.select(self.hosts[key]);self.root.update()
            self.assertTrue(tree.winfo_ismapped())
            x=tree.winfo_rootx()+min(30,tree.winfo_width()-1)
            y=tree.winfo_rooty()+min(40,tree.winfo_height()-1)
            hit=self.root.winfo_containing(x,y)
            self.assertIsNotNone(hit)
            self.assertTrue(str(hit)==str(tree) or str(hit).startswith(str(tree)+'.'),
                            'Original tree is covered by %s' % hit)
        note=next(w for w in self.hosts['info'].winfo_children() if isinstance(w,tk.Label))
        self.assertEqual(note.cget('text'),'內政區僅顯示已捕獲的記錄；空白不代表沒有下令。')
        self.app.control_book.select(self.other);self.root.update()
        hit=self.root.winfo_containing(self.other.winfo_rootx()+20,self.other.winfo_rooty()+20)
        self.assertTrue(str(hit)==str(self.other) or str(hit).startswith(str(self.other)+'.'))
        self.assertFalse(self.app.force_page.winfo_ismapped())
        self.assertFalse(self.app.force_compare.winfo_ismapped())
        self.assertEqual(self.errors,[])

    def test_lazy_latest_snapshot_uses_original_render_stock_cards_and_quarter_unknown(self):
        first=payload();before=copy.deepcopy(first)
        with mock.patch.object(self.app,'render',wraps=self.app.render) as render:
            self.assertTrue(update_force_views(self.app,first))
            render.assert_not_called()
            self.assertIsNot(self.app.doc,first['state'])
            self.app.control_book.select(self.hosts['info']);self.root.update()
            self.assertIsNone(self.app.force_views_error)
            self.assertGreaterEqual(render.call_count,1)
        self.assertIn('12,345',self.app.resources.cget('text'))
        self.assertTrue(self.app.force_tree.item('3','image'))
        # The actual original stock/training widget, not replacement strings.
        self.assertEqual(self.app.military.tiles['infantry'][1].cget('text'),'1,000')
        self.assertIn('暂无记录',self.app.quarter_ops.input_log.get('1.0','end'))
        self.assertEqual(first,before)
        self.assertNotIn('player_identity',self.app.doc)
        self.assertNotIn('native_command_evidence',self.app.doc)
        self.assertEqual(self.errors,[])

    def test_compare_only_refresh_and_same_game_selection_camera_are_preserved(self):
        self.assertTrue(update_force_views(self.app,payload()))
        self.app.sel=3
        self.app.panorama.center=(40,90);self.app.panorama.zoom=3
        self.app.control_book.select(self.hosts['compare']);self.root.update()
        with mock.patch.object(self.app,'render',wraps=self.app.render) as render:
            self.assertTrue(update_force_views(self.app,payload(gold=23456)))
            render.assert_not_called()
        self.assertEqual(self.app.sel,3)
        self.assertEqual((self.app.panorama.center,self.app.panorama.zoom),((40,90),3))
        self.assertEqual(self.app.force_compare.tree.get_children(),('3',))
        self.assertEqual(self.app.doc['entities']['lords'][0]['gold'],23456)
        self.assertEqual(self.errors,[])

    def test_game_change_clears_prior_view_history_and_foreign_payload_is_rejected(self):
        self.assertTrue(update_force_views(self.app,payload()))
        self.app.sel=3
        self.app.training_record.series=[{'old_game':True}]
        self.app.training_record.samples=[{'old_game':True}]
        self.app.quarter_ops._expanded_additions.add('old')
        self.app.retained_command_view={'old':True}
        self.assertTrue(update_force_views(self.app,payload(key='game-two')))
        self.assertIsNone(self.app.sel)
        self.assertEqual(self.app.training_record.series,[])
        self.assertEqual(self.app.quarter_ops._expanded_additions,set())
        self.assertIsNone(self.app.retained_command_view)
        current=self.app.doc
        foreign=payload();foreign['source_prefix']='prefix-dingman-local'
        self.assertFalse(update_force_views(self.app,foreign))
        self.assertIs(self.app.doc,current)
        self.assertIn('風夜資料來源',self.app.force_views_error)
        self.assertEqual(self.errors,[])


if __name__=='__main__':unittest.main()
