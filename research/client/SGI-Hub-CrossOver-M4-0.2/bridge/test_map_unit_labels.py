"""Actual Canvas stacking and single-click behavior for overlapping labels."""
import sys
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from map_unit_labels import label_box,raise_label


class MapLabelTests(unittest.TestCase):
    def test_selected_label_background_and_text_raise_together(self):
        root=tk.Tk()
        try:
            canvas=tk.Canvas(root,width=500,height=200);canvas.pack();root.update()
            first=label_box(canvas,200,80,'first unit','#ff0000',tags='ov')
            second=label_box(canvas,200,80,'second unit','#0000ff',tags='ov')
            other=canvas.find_withtag(f'unit-label-{second}')
            raise_label(canvas,first)
            top=canvas.find_all()[-2:]
            self.assertEqual(set(top),set(canvas.find_withtag(f'unit-label-{first}')))
            self.assertEqual(canvas.type(top[0]),'rectangle');self.assertEqual(canvas.type(top[1]),'text')
            self.assertTrue(all(canvas.find_all().index(i)<canvas.find_all().index(top[0]) for i in other))
            canvas.delete('ov');self.assertEqual(canvas.find_all(),())
        finally:root.destroy()

    def test_single_unit_click_selects_and_draws_without_opening_window(self):
        from panorama_map import PanoramaMap
        page=object.__new__(PanoramaMap);page.drag=(100,100);page.slim=False
        page._hit=Mock(return_value=('部队',7));page._selected_row=Mock(return_value=('部队',{'unit_id':7}))
        page.detail=Mock();page._describe=Mock(return_value='unit7');page.draw=Mock();page._open_unit_tour=Mock()
        page._release(SimpleNamespace(x=100,y=100))
        self.assertEqual(page.selected,('部队',7));page.draw.assert_called_once()
        page._open_unit_tour.assert_not_called()
        page._double(SimpleNamespace(x=100,y=100));page._open_unit_tour.assert_called_once_with({'unit_id':7})


if __name__=='__main__':unittest.main()
