"""Actual Tk calculator interactions and the final two-tab workspace."""
import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))


class CalculatorUiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:self.root=tk.Tk()
        except tk.TclError:self.skipTest('no display')
        self.root.withdraw()

    def tearDown(self):self.root.destroy()

    def test_inputs_clear_errors_import_and_refresh_preserve_manual_values(self):
        from attack_calculator import AttackCalculator
        ui=AttackCalculator(self.root,SimpleNamespace(face='Arial'));ui.pack();self.root.update()
        self.assertIn('[388/520]',ui.answer.cget('text'))
        ui.horse.set(False);ui.changed();self.assertIn('[193/258]',ui.answer.cget('text'))
        ui.variables['terrain'].set('水上');self.assertIn('[118/258]',ui.answer.cget('text'))
        ui.variables['training'].set('');self.assertIsNone(ui.result);self.assertNotIn('118',ui.answer.cget('text'))
        ui.variables['training'].set('60');self.assertIsNotNone(ui.result)
        state=json.loads((Path(__file__).parent/'native-map-321-fixture.json').read_text())['state']
        unit=state['entities']['field_units'][0];ui.refresh(state,unit['owner_raw']);ui.load_unit()
        self.assertEqual(ui.result['current'],867);self.assertIn('已载入',ui.source_note.cget('text'))
        ui.variables['morale'].set('25');ui.refresh(None,None)
        self.assertEqual(ui.variables['morale'].get(),'25');self.assertEqual(str(ui.load_button['state']),'disabled')
        ui.refresh(state,unit['owner_raw']);bad=copy.deepcopy(state);bad['build_sha256']='unknown'
        ui.refresh(bad,unit['owner_raw']);before=ui.result;ui.load_unit()
        self.assertEqual(ui.result,before);self.assertIn('不能载入',ui.source_note.cget('text'))
        ui.variables['kind'].set('强弓兵');self.assertIn('远射指数',ui.answer.cget('text'))

    def test_only_manual_and_calculator_remain_diplomacy_still_separate(self):
        from tkinter import ttk
        from rules_panel import RulesPanel
        workspace=ttk.Notebook(self.root);workspace.pack()
        app=SimpleNamespace(face='Arial',workspace=workspace,force_page=ttk.Frame(workspace),doc=None,sel=None)
        def tree(parent,columns):
            t=ttk.Treeview(parent,columns=[c[0] for c in columns]);t.pack();return t
        app.tree=tree
        panel=RulesPanel(workspace,app);workspace.add(panel,text='攻略预判');panel.refresh();self.root.update()
        self.assertEqual([panel.tabs.tab(t,'text') for t in panel.tabs.tabs()],['算法手册','攻击系数计算器'])
        self.assertIn('外交对比 · 手牌计算',[workspace.tab(t,'text') for t in workspace.tabs()])
        self.assertIn('宣战拒绝',[workspace.tab(t,'text') for t in workspace.tabs()])
        panel.tabs.select(panel.attack_calculator);self.root.update();self.assertIn('[388/520]',panel.attack_calculator.answer.cget('text'))

if __name__=='__main__':unittest.main()
