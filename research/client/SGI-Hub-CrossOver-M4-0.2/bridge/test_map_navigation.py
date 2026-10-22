import sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from map_navigation import _MOVE_KEYS, _ZOOM_KEYS, bind_pointer_wheel, bind_zoom_keys, move_center, precise_scroll_deltas, wheel_direction
from panorama_model import BARRIER_VISION, CAPITAL_VISION, CITY_VISION, cell_diamond, sprite_size, vision_cells
from city_tactical import CityTactical,city_alert,nearby
from native_city_map import CityLocator

class NavigationTests(unittest.TestCase):
 def test_bounds_and_directions(self):
  self.assertEqual(move_center((0,201),-1,1),(0,201))
  self.assertEqual(move_center((50,100),1,-1,2),(52,98))
 def test_mac_wheel_direction(self):
  self.assertEqual(wheel_direction(120),1)
  self.assertEqual(wheel_direction(-1),-1)
  self.assertEqual(wheel_direction(0),0)
  self.assertEqual(wheel_direction(None),0)
 def test_tactical_pan_keeps_anchor_and_moves_visible_entities(self):
  anchor={'world_xy_raw':[20,20]}
  view=SimpleNamespace(city=anchor,view_center=None,render=lambda:None)
  CityTactical.pan(view,0,-1);self.assertEqual(view.view_center,(20,18))
  CityTactical.pan(view,1,0);self.assertEqual(view.view_center,(21,18))
  self.assertEqual(anchor['world_xy_raw'],[20,20])
  CityTactical.return_target(view);self.assertIsNone(view.view_center)
 def test_selected_unit_recenters(self):
  view=SimpleNamespace(selected='u',items={'u':('部队',{'world_xy_raw':[45,60]},'u')},render=lambda:None)
  CityTactical.recenter_selected(view);self.assertEqual(view.view_center,(45,60))
 def test_fullmap_click_unit(self):
  record={'type':'field_unit','unit_id':8,'world_xy_raw':[20,20]}
  calls=[]
  view=SimpleNamespace(state={'entities':{'cities_and_barriers':[],'field_units':[record]}},
       show_units=SimpleNamespace(get=lambda:True),project=lambda x,y:(x,y),entity_target=None,
       entity_key=CityLocator.entity_key,focus_entity=lambda k,r:calls.append((k,r)))
  CityLocator.click_city(view,SimpleNamespace(x=20,y=20))
  self.assertEqual(calls,[('field_units',record)])
 def test_city_alert_empty_is_none(self):
  city={'world_xy_raw':[10,10]}
  self.assertEqual(city_alert({'entities':{}},city),('陷阱未采集',False))
  empty={'entities':{'traps':[]}}
  self.assertEqual(city_alert(empty,city),('无',False))
  far={'entities':{'traps':[{'trap_kind':'火计','world_xy_raw':[50,50]}]}}
  self.assertEqual(city_alert(far,city),('无',False))
  near={'entities':{'traps':[{'trap_kind':'火计','world_xy_raw':[11,10]}]}}
  self.assertEqual(city_alert(near,city),('有 1 处 · 火计1',True))
 def test_wasd_matches_arrows(self):
  self.assertEqual(_MOVE_KEYS['w'], _MOVE_KEYS['Up'])
  self.assertEqual(_MOVE_KEYS['s'], _MOVE_KEYS['Down'])
  self.assertEqual(_MOVE_KEYS['a'], _MOVE_KEYS['Left'])
  self.assertEqual(_MOVE_KEYS['d'], _MOVE_KEYS['Right'])
  nav=(Path(__file__).resolve().parent.parent/'app'/'map_navigation.py').read_text(encoding='utf-8')
  self.assertNotIn('unbind_all', nav)
  self.assertIn('_wheel_dispatch', nav)
  self.assertIn('winfo_containing', nav)
  self.assertIn('winfo_pointerxy', nav)
  self.assertIn('bind_class', nav)
  self.assertIn('TNotebook', nav)
  self.assertIn('TouchpadScroll', nav)
  self.assertIn("<' + key + '>'", nav)
  self.assertEqual(_ZOOM_KEYS['minus'], -1)
  self.assertEqual(_ZOOM_KEYS['equal'], 1)
  self.assertEqual(_ZOOM_KEYS['-'], -1)
  self.assertEqual(_ZOOM_KEYS['='], 1)
  self.assertIn('bind_zoom_keys', nav)
  self.assertIn("'minus'", nav)
  self.assertIn("'equal'", nav)
  self.assertIn("for key in ('minus', 'equal'):", nav)
  self.assertIn('except Exception', nav)
  self.assertIn('<KeyPress>', nav)
 def test_zoom_keys_tolerate_invalid_sequence(self):
  class Fake:
   def bind(self, seq, fn, add=None):
    raise RuntimeError('no event type or button # or keysym')
  seen=[]
  bind_zoom_keys(Fake(), seen.append)
  self.assertEqual(seen, [])
 def test_zoom_keys_bind_without_tcl_error(self):
  import tkinter as tk
  try:
   root=tk.Tk();root.withdraw()
  except tk.TclError:
   self.skipTest('no display')
  seen=[]
  bind_zoom_keys(root,seen.append)
  root.destroy()
  self.assertEqual(seen,[])
 def test_touchpad_scroll_unpacks_tk9_deltas(self):
  self.assertEqual(precise_scroll_deltas(5), (0, 5))
  self.assertEqual(precise_scroll_deltas(0xfffd), (0, -3))
  self.assertEqual(precise_scroll_deltas(2 << 16), (2, 0))
  self.assertEqual(precise_scroll_deltas(((-1) & 0xffff) << 16 | 8), (-1, 8))
 def test_city_vision_is_three_cell_diamond(self):
  self.assertEqual(CITY_VISION, 3)
  self.assertEqual(CAPITAL_VISION, 5)
  self.assertEqual(BARRIER_VISION, 1)
  cells=vision_cells((20, 40))
  self.assertIn((20, 40), cells)
  self.assertIn((21, 40), cells)
  self.assertIn((20, 43), cells)
  self.assertNotIn((22, 42), cells)
  self.assertNotIn((23, 43), cells)
  self.assertEqual(len(cells), 25)
  self.assertEqual(len(vision_cells((20, 40), 1)), 5)
  self.assertEqual(len(vision_cells((20, 40), 5)), 61)
  self.assertEqual(set(vision_cells((20, 40), 1)), {
   (19,39),(20,39),(20,40),(19,41),(20,41),
  })
  from tactical_terrain import world_pixel
  for center in ((20,40),(20,41)):
   px,py=world_pixel(*center)
   offsets={(world_pixel(x,y)[0]-px,world_pixel(x,y)[1]-py)
            for x,y in vision_cells(center,1)}
   self.assertEqual(offsets,{(-48,-24),(-48,24),(0,0),(48,-24),(48,24)})
  for center in ((0,0),(100,201)):
   clipped=vision_cells(center,5)
   self.assertIn(center,clipped)
   self.assertTrue(all(0<=x<101 and 0<=y<202 for x,y in clipped))
  self.assertEqual(vision_cells((20,40),0),[(20,40)])
  diamond=cell_diamond(10, 11)
  self.assertEqual(len(diamond), 4)
  self.assertGreater(sprite_size('城关', 6, 1.25), 70)
  self.assertLess(sprite_size('城关', 1), 30)
 def test_fullmap_pan_and_reset(self):
  view=SimpleNamespace(center=(50.5,100.5),zoom=2,world=(101,202),draw=lambda:None,
       target_record={'world_xy_raw':[40,60]})
  CityLocator.pan(view,-1,0);self.assertEqual(view.center,(44.5,100.5))
  CityLocator.return_target(view);self.assertEqual(view.center,(40.5,60.5))
