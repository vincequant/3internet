"""Actual Tk interactions: selectable draw count and stable forecast selection."""
import json,sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
class ForecastUITests(unittest.TestCase):
 def test_user_can_choose_four_and_five_and_missing_pool_clears(self):
  import tkinter as tk
  from tkinter import ttk
  from diplomacy_forecasts import CardProbabilityBoard,DefectionBoard
  from diplomacy_matchup import WarRejectBoard
  from test_diplomacy_forecasts import fixture
  try:root=tk.Tk()
  except tk.TclError:self.skipTest('no display')
  root.geometry('1180x760+40+50');root.title('SGI Hub 1.1.330 · 概率验收')
  def tree(p,cols):
   t=ttk.Treeview(p,columns=tuple(c[0] for c in cols),show='headings',height=7)
   for key,title,width in cols:t.heading(key,text=title);t.column(key,width=width,minwidth=50)
   t.pack(fill='both',expand=True);return t
  app=SimpleNamespace(face='Arial',tree=tree)
  try:
   book=ttk.Notebook(root);book.pack(fill='both',expand=True)
   draw=CardProbabilityBoard(book,app);defection=DefectionBoard(book,app);war=WarRejectBoard(book,app)
   for w,n in ((draw,'抽牌概率'),(defection,'策反'),(war,'宣战拒绝')):book.add(w,text=n)
   s=fixture();s['card_pool']={'status':'verified','counts':{str(i):0 for i in range(1,29)}};s['card_pool']['counts'].update({'1':2,'2':1,'17':1,'26':6})
   draw.refresh(s);root.update();self.assertTrue(draw.hide_zero.get());self.assertEqual(tuple(draw.tree.item('0')['values']),('白卡（全部）','50.00%'));self.assertFalse(any(draw.tree.item(i)['values'][1]=='0.00%' for i in draw.tree.get_children()));draw.hide_zero.set(False);draw.calculate();root.update();self.assertTrue(any(draw.tree.item(i)['values'][1]=='0.00%' for i in draw.tree.get_children()));draw.hide_zero.set(True);draw.calculate();draw.draws.set('4');root.update();self.assertEqual(tuple(draw.tree.item('0')['values']),('白卡（全部）','40.00%'));self.assertNotIn('0张',draw.detail.cget('text'));self.assertEqual(draw.tree['columns'],('name','one'))
   draw.draws.set('5');root.update();self.assertIn('50.00%',draw.tree.item('0')['values'])
   defection.refresh(s,1);book.select(defection);root.update();self.assertIn('97.75%',defection.tree.item('0')['values']);self.assertIn('必入选',str(defection.tree.item('0')['values']));self.assertIn('将11',defection.detail.get('1.0','end'))
   defection.tree.selection_set('0');defection.refresh(s,1);self.assertEqual(defection.tree.selection(),('0',))
   war.refresh(s,1);book.select(war);root.update();self.assertEqual(list(war.tree.get_children()),[])
   draw.refresh({});self.assertFalse(draw.tree.get_children());self.assertIn('没有完整',draw.summary.cget('text'))
   if __import__('os').environ.get('SGI_FORECAST_PREVIEW'):
    draw.refresh(s);book.select(draw);root.update();root.after(15000,root.quit);root.mainloop()
  finally:root.destroy()
if __name__=='__main__':unittest.main()
