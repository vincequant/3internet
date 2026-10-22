"""Exercise navigation/search in actual Tk; no game state, future frames or actions."""
import unittest,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
class AlgorithmGuideTests(unittest.TestCase):
 def test_search_categories_selection_and_optional_evidence(self):
  import tkinter as tk
  from algorithm_guide import AlgorithmGuide
  try:root=tk.Tk()
  except tk.TclError:self.skipTest('no display')
  root.withdraw()
  try:
   ui=AlgorithmGuide(root,SimpleNamespace(face='Arial'));ui.pack();root.update()
   self.assertEqual(ui.current,'composition')
   ui.category.set('军事');root.update()
   self.assertTrue(ui.rows);self.assertTrue(all(c['category']=='军事' for c in ui.rows.values()))
   ui.query.set('水战');root.update();self.assertIn('water-attack',ui.rows)
   ui.tree.selection_set('water-attack');root.update()
   body=ui.text.get('1.0','end');self.assertIn('[122/529]',body)
   self.assertNotIn('0x477dfb',body)
   ui.show_evidence.set(True);ui.render();self.assertIn('0x477dfb',ui.text.get('1.0','end'))
   ui.query.set('不存在的算法xyz');root.update();self.assertFalse(ui.rows);self.assertIn('没有匹配',ui.text.get('1.0','end'))
   ui.query.set('');ui.category.set('内政');root.update();self.assertIn('training',ui.rows);self.assertNotIn('water-attack',ui.rows)
   ui.tree.selection_set('recruit');root.update();self.assertIn('同城',ui.text.get('1.0','end'))
   ui.category.set('全部');root.update();self.assertEqual(ui.current,'recruit')
  finally:root.destroy()
if __name__=='__main__':unittest.main()
