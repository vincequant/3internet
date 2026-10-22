import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from city_roads import load_road_edges, path_for_layer, rdp, stride
from unit_memory import memory_line
from panorama_map import apply_view, parse_view, tk_pixels
from wine_nav import panorama_command
from panorama_model import (
    DETAIL_ZOOM, MIN_ZOOM, SWITCH_ZOOM, capital_marks, catalog_cities, clamp_zoom,
    is_capital, layer_for_zoom, live_objects, mbm_view, named_city_places, nearest_city,
    object_key, opponent_brief, overlay_force_diamonds, paint_mbm_vision, parse_map_point,
    search_city_places, show_kind_at_zoom, show_overlay, supply_lines, units_in_view,
    view_unit_line, vision_cells, vision_overlay_cells, world_xy,
)


class PanoramaResearchTests(unittest.TestCase):
    def test_zoom_stays_on_mbm_across_hub_range(self):
        self.assertLess(SWITCH_ZOOM, MIN_ZOOM)
        self.assertEqual(layer_for_zoom(MIN_ZOOM), 'mbm')
        self.assertEqual(layer_for_zoom(1), 'mbm')
        self.assertEqual(layer_for_zoom(6), 'mbm')
        self.assertEqual(layer_for_zoom(SWITCH_ZOOM - 0.1), 'lbm')

    def test_zoom_stays_in_range(self):
        self.assertEqual(clamp_zoom(0), MIN_ZOOM)
        from panorama_model import clamp_mbm_view
        zoom, center = clamp_mbm_view((50.5, 101), 0.05, 1200, 700)
        self.assertGreater(zoom, 0.28)
        box, _scale = __import__('panorama_model', fromlist=['mbm_view']).mbm_view(center, zoom, 1200, 700)
        self.assertGreaterEqual(box[0], -2)
        self.assertGreaterEqual(box[1], -2)
        self.assertLessEqual(box[2], 9746)
        self.assertLessEqual(box[3], 4874)
        self.assertEqual(clamp_zoom(99), 12.0)

    def test_mbm_box_follows_jiangling(self):
        box, scale = mbm_view((52.5, 124.5), 6, 800, 480)
        self.assertGreater(scale, 0)
        self.assertLess(box[0], box[2])
        self.assertLess(box[1], box[3])
        self.assertLess(box[2] - box[0], 4000)

    def test_historical_cities_include_jiangling(self):
        cities = catalog_cities()
        match = [row for row in cities if row['name'] == '江陵']
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]['world_xy'], (52, 124))
        self.assertEqual(nearest_city((52.4, 124.2), cities)['name'], '江陵')

    def test_search_city_name_and_coordinates(self):
        hits = search_city_places('江陵')
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['world_xy'], (52, 124))
        self.assertEqual(search_city_places('成都')[0]['name'], '成都')
        self.assertEqual(parse_map_point('52,124'), (52.0, 124.0))
        self.assertEqual(parse_map_point('52.5，124.5'), (52.5, 124.5))
        self.assertIsNone(parse_map_point('江陵'))
        live = {'entities': {'cities_and_barriers': [
            {'city_id': 9, 'name': '江陵', 'world_xy_raw': [10, 20]},
        ]}}
        moved = search_city_places('江陵', live)
        self.assertEqual(moved[0]['world_xy'], (10, 20))
        self.assertEqual(moved[0]['source'], 'live')
        names = {row['name'] for row in named_city_places()}
        self.assertIn('洛阳', names)
        src = (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8')
        self.assertIn('def go_city', src)
        self.assertIn("text='定位'", src)
        talent = (ROOT / 'app/omni_window.py').read_text(encoding='utf-8')
        self.assertIn('show_city_wild', talent)
        self.assertIn('nation_view', talent)
        self.assertIn('def locate_listed_officer', talent)
        self.assertIn('本城在野', talent)
        self.assertIn('def locate_wild', talent)
        self.assertIn('city_for_officer', talent)
        self.assertIn('officer=officer', talent)
        self.assertIn('if nation_view:self.object_locator.fit()', talent)
        self.assertLess(talent.index("if show_city_wild and key=='cities'"), talent.index('if prefer_world:self.location_book.select(self.object_locator)'))
        self.assertIn('nation_view=True', (ROOT / 'app/city_talent.py').read_text(encoding='utf-8'))

    def test_wine_nav_and_hub_tab(self):
        hub = (ROOT / 'app/omni_window.py').read_text(encoding='utf-8')
        nav = (ROOT / 'app/wine_nav.py').read_text(encoding='utf-8')
        swift = ROOT.parents[2] / 'scripts/wine-launcher/main.swift'
        self.assertIn("text='全景地图'", hub)
        self.assertIn('PanoramaMap', hub)
        pan = (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8')
        self.assertIn("tk.PanedWindow(self, orient='horizontal'", pan)
        self.assertIn("minsize=400", pan)
        self.assertIn("tk.Frame(self, bg='#22241d'", pan)
        self.assertIn('def _place_side_sash', pan)
        self.assertIn('sash_place', pan)
        self.assertIn('self._body = None', pan)
        self.assertIn('展开对手状态', pan)
        self.assertIn('def toggle_side', pan)
        self.assertIn('self._side_open = False', pan)
        self.assertIn("bind('<Double-1>'", pan)
        self.assertIn('def _double', pan)
        self.assertIn('def _side_wrap', pan)
        self.assertNotIn("side.pack(side='right', fill='y')", pan)
        self.assertIn("text='全景地图'", nav)
        self.assertIn('房间观察', nav)
        self.assertIn('打开历史回放', nav)
        self.assertIn('panorama_replay.py', nav)
        self.assertNotIn('attach_collector', (ROOT / 'app/panorama_replay.py').read_text(encoding='utf-8'))
        if swift.is_file():
            swift_text = swift.read_text(encoding='utf-8')
            self.assertIn('全景地图', swift_text)
            self.assertIn('打开历史回放', swift_text)
            self.assertIn('launchHub("--launch", "replay")', swift_text)
            self.assertIn('launchHub("--launch", "hub")', swift_text)
            self.assertNotIn('launch("hub")', swift_text)
        self.assertIn('panorama_map.py', nav)
        cmd = panorama_command((74.5, 63.5), 6)
        self.assertEqual(cmd[-4:], ['--center', '74.5,63.5', '--zoom', '6.0'])
        center, zoom = parse_view(['--center', '74.5,63.5', '--zoom', '6'])
        self.assertEqual(center, (74.5, 63.5))
        self.assertEqual(zoom, 6.0)
        page = type('P', (), {'center': (1, 1), 'zoom': 1.0})()
        apply_view(page, (74.5, 63.5), 6)
        self.assertEqual(page.center, (74.5, 63.5))
        self.assertEqual(page.zoom, 6.0)
        locator = (ROOT / 'app/native_city_map.py').read_text(encoding='utf-8')
        self.assertIn('打开全景视窗', locator)
        self.assertIn('self.zoom=6.', locator)
        self.assertIn('bind_pointer_wheel', locator)
        self.assertIn('bind_pointer_wheel', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertIn("text='指令'", (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertIn('set_force_commands', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertIn('set_force_commands', (ROOT / 'app/panorama_replay.py').read_text(encoding='utf-8'))
        self.assertIn('bind_all', (ROOT / 'app/map_navigation.py').read_text(encoding='utf-8'))
        self.assertNotIn('unbind_all', (ROOT / 'app/map_navigation.py').read_text(encoding='utf-8'))
        self.assertIn("<' + key + '>'", (ROOT / 'app/map_navigation.py').read_text(encoding='utf-8'))
        self.assertIn('vision_overlay_cells', (ROOT / 'app/native_city_map.py').read_text(encoding='utf-8'))
        self.assertIn('paint_mbm_vision', locator)
        self.assertIn('overlay_force_diamonds', locator)
        self.assertIn('capital_marks', locator)
        self.assertIn('paint_mbm_vision', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertIn('_city_vision_diamonds', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertIn('winfo_containing', (ROOT / 'app/map_navigation.py').read_text(encoding='utf-8'))
        self.assertIn('滚轮或 -/= 缩放', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertIn('bind_zoom_keys', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertNotIn('def _star', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertNotIn('#f6d36a', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertNotIn('def _star', (ROOT / 'app/native_city_map.py').read_text(encoding='utf-8'))
        self.assertNotIn('#f6d36a', (ROOT / 'app/native_city_map.py').read_text(encoding='utf-8'))
        self.assertIn('本视野部队', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertIn('units_in_view', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        src = (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8')
        self.assertIn("text='指令'", src)
        self.assertIn("text='该势力部队'", src)
        self.assertIn("text='本视野部队'", src)
        self.assertIn("text='交战部队'", src)
        self.assertIn('_draw_raid_route', src)
        self.assertIn("mode == 'raid'", src)
        self.assertNotIn("layer = 'lbm' if self.slim", src)
        self.assertIn("mode='raid'", (ROOT / 'app/stealth_raid_page.py').read_text(encoding='utf-8'))
        self.assertIn('shared_terrain(warmup=True)', src)
        self.assertIn("self.canvas.bind('<Configure>', lambda _=None: self.request_draw())", src)
        self.assertIn('def shared_lbm', src)
        omni = (ROOT / 'app/omni_window.py').read_text(encoding='utf-8')
        self.assertIn("text='偷袭主城'", omni)
        self.assertNotIn('陷阱（只读）', omni)
        self.assertLess(src.find("text='指令'"), src.find("text='该势力部队'"))
        self.assertLess(src.find("text='该势力部队'"), src.find("text='本视野部队'"))
        self.assertLess(src.find("text='本视野部队'"), src.find("text='交战部队'"))
        self.assertIn('focus_force_id', src)
        self.assertIn('force_attack_rows', src)
        self.assertIn('总战力', src)
        self.assertIn('Notebook', src)
        self.assertNotIn('view_panel.place', src)
        self.assertIn('paint_mbm_vision', src)
        self.assertIn('show_kind_at_zoom', src)

    def test_live_overlays_and_opponent_filter(self):
        relations = [0] * 22
        relations[2] = 1
        state = {
            'player_force_id': 1,
            'player_identity': {'status': 'confirmed', 'force_id': 1},
            'entities': {
                'lords': [
                    {'force_id': 1, 'name': '我军', 'diplomacy_relations': relations},
                    {'force_id': 2, 'name': '敌军'},
                ],
                'cities_and_barriers': [
                    {'city_id': 31, 'name': '江陵', 'type': 'city', 'owner_raw': 2, 'world_xy_raw': [52, 124]},
                ],
                'production_buildings': [
                    {'object_id_candidate': 8, 'type': 'parade_ground', 'owner_raw': 2, 'world_xy_raw': [53, 124]},
                ],
                'traps': [
                    {'trap_id': 4, 'type': 'trap', 'trap_kind': '落石', 'owner_raw': 2, 'world_xy_raw': [54, 124]},
                ],
                'field_units': [
                    {'unit_id': 9, 'unit_kind': '骑兵', 'owner_raw': 2, 'world_xy_raw': [52, 125]},
                    {'unit_id': 10, 'unit_kind': '步兵', 'owner_raw': 3, 'world_xy_raw': [10, 10]},
                ],
            },
        }
        kinds = [kind for kind, _ in live_objects(state)]
        self.assertEqual(kinds, ['城关', '建筑', '陷阱', '部队', '部队'])
        self.assertEqual(world_xy(state['entities']['cities_and_barriers'][0]), (52, 124))
        self.assertTrue(show_overlay(state, '部队', state['entities']['field_units'][0], True))
        self.assertFalse(show_overlay(state, '部队', state['entities']['field_units'][1], True))
        self.assertIn('敌军', opponent_brief(state))
        self.assertIn('部队 1', opponent_brief(state))
        self.assertEqual(object_key('城关', state['entities']['cities_and_barriers'][0]), ('城关', 'city', 31))
        near = units_in_view(state, (51, 123, 55, 127))
        self.assertEqual([row['unit_id'] for row in near], [9])
        far = units_in_view(state, (0, 0, 15, 15))
        self.assertEqual([row['unit_id'] for row in far], [10])
        self.assertEqual([row['unit_id'] for row in units_in_view(state, (0, 0, 100, 200), True)], [9])
        self.assertIn('敌军', view_unit_line(state, state['entities']['field_units'][0]))
        self.assertIn('骑兵', view_unit_line(state, state['entities']['field_units'][0]))
        state['entities']['cities_and_barriers'].append(
            {'city_id': 99, 'name': '关', 'type': 'barrier', 'owner_raw': 2, 'world_xy_raw': [10, 10]}
        )
        overlay = vision_overlay_cells(state)
        cells = {item['cell'] for item in overlay}
        self.assertIn((52, 124), cells)
        self.assertIn((53, 124), cells)
        self.assertIn((10, 10), cells)
        self.assertTrue(all(item['owner_raw'] == 2 for item in overlay))
        state['entities']['lords'][1]['capital_city_id'] = 31
        capital_cells = {item['cell'] for item in vision_overlay_cells(state) if item['owner_raw'] == 2}
        city_only = {
            'entities': {
                'lords': [{'force_id': 2, 'capital_city_id': 0}],
                'cities_and_barriers': [
                    {'city_id': 8, 'name': '城', 'type': 'city', 'owner_raw': 2, 'world_xy_raw': [80, 40]},
                ],
            }
        }
        self.assertGreater(len(vision_cells((52, 124), 5)), len(vision_cells((80, 40), 3)))
        self.assertGreater(len(capital_cells), len(vision_overlay_cells(city_only)))

    def test_supply_lines_and_capitals(self):
        cities = [
            {'city_id': 1, 'name': '甲', 'type': 'city', 'owner_raw': 4, 'world_xy_raw': [10, 10]},
            {'city_id': 2, 'name': '乙', 'type': 'city', 'owner_raw': 4, 'world_xy_raw': [20, 10]},
            {'city_id': 3, 'name': '丙', 'type': 'city', 'owner_raw': 5, 'world_xy_raw': [20, 20]},
            {'city_id': 4, 'name': '丁', 'type': 'city', 'owner_raw': 5, 'world_xy_raw': [10, 20]},
        ]
        state = {
            'entities': {
                'lords': [
                    {'force_id': 4, 'name': '楚', 'capital_city_id': 1},
                    {'force_id': 5, 'name': '吴', 'capital_city_id': 3},
                    {'force_id': 6, 'name': '空', 'capital_city_id': 99},
                ],
                'cities_and_barriers': cities,
            }
        }
        edges = [
            {'a': 1, 'b': 2, 'path': [[0, 0], [10, 4], [20, 0]]},
            {'a': 2, 'b': 3, 'path': [[20, 0], [20, 20]]},
            {'a': 3, 'b': 4, 'path': [[20, 20], [10, 20]]},
            {'a': 1, 'b': 4, 'path': [[0, 0], [10, 20]]},
        ]
        lines = supply_lines(state, edges)
        same = {(line['a_id'], line['b_id'], line['owner_raw']) for line in lines if line['same_owner']}
        split = {(line['a_id'], line['b_id']) for line in lines if not line['same_owner']}
        self.assertEqual(same, {(1, 2, 4), (3, 4, 5)})
        self.assertEqual(split, {(2, 3), (1, 4)})
        self.assertGreater(len(lines[0]['path']), 2)
        self.assertEqual(rdp([(0, 0), (5, 0), (10, 0)], 1), [(0, 0), (10, 0)])
        self.assertEqual(len(rdp([(0, 0), (5, 8), (10, 0)], 1)), 3)
        self.assertEqual(stride([(0, 0), (1, 1), (2, 2), (3, 3)], 2), [(0, 0), (2, 2), (3, 3)])
        gentle = [(0, 0), (20, 4), (40, 6), (80, 4), (120, 0)]
        self.assertEqual(path_for_layer(gentle, 'lbm'), [(0, 0), (120, 0)])
        self.assertEqual(path_for_layer(gentle, 'mbm'), gentle)
        self.assertLess(len(path_for_layer(gentle, 'mbm', 0.28)), len(gentle))
        corner = [(0, 0), (200, 0), (200, 200)]
        self.assertEqual(path_for_layer(corner, 'lbm'), [(0, 0), (200, 0), (200, 200)])
        marks = capital_marks(state)
        self.assertEqual([(m['force_name'], m['city_name'], m['world_xy']) for m in marks], [
            ('楚', '甲', (10, 10)),
            ('吴', '丙', (20, 20)),
        ])
        self.assertTrue(is_capital(state, cities[0]))
        self.assertFalse(is_capital(state, cities[1]))
        nav = (ROOT / 'app/wine_nav.py').read_text(encoding='utf-8')
        self.assertIn('沿路补给线', nav)
        self.assertIn('首都位置', nav)
        baked = [edge for edge in load_road_edges() if {edge.get('a_name'), edge.get('b_name')} & {'汉昌', '江陵'}]
        self.assertTrue(baked)
        self.assertTrue(all(len(edge['path']) > 4 for edge in baked))
        anding = next(edge for edge in load_road_edges() if {edge.get('a_name'), edge.get('b_name')} == {'安定', '北地'})
        ys = [point[1] for point in anding['path']]
        self.assertGreater(len(anding['path']), 20)
        self.assertGreater(max(ys) - min(ys), 40)

    def test_unit_memory_line_includes_rice(self):
        text = memory_line({
            'soldiers_candidate': 2969,
            'rice_candidate': 2969,
            'morale': 100,
            'basic_combat_power': 69,
            'target_attack_unit': 90,
        })
        self.assertIn('粮食 2,969（约6天）', text)
        self.assertIn('战力 69', text)
        self.assertIn('士气 100', text)
        self.assertNotIn('训练', text)
        nav = (ROOT / 'app/omni_window.py').read_text(encoding='utf-8')
        self.assertIn("('rice','粮食 / 约可吃',130)", nav)
        self.assertIn("('attack','攻击[当前/满士气]',130)", nav)
        self.assertNotIn('攻城攻击参考', nav)
        self.assertNotIn('编成将技能', nav)
        self.assertNotIn("('xy','坐标',70)", nav)
        self.assertNotIn('粮食天数按攻略', nav)
        self.assertNotIn("('training','本级武装值',95)", nav)
        locator = (ROOT / 'app/native_city_map.py').read_text(encoding='utf-8')
        self.assertIn('layer_for_zoom', locator)
        self.assertIn('supply_lines', locator)
        self.assertIn('mbm_view', locator)

    def test_tk9_canvas_width_with_centimeter_unit(self):
        class Fake:
            def winfo_fpixels(self, value):
                text = str(value)
                if text.endswith('c'):
                    return float(text[:-1]) * 37.8
                return float(text)
        self.assertEqual(tk_pixels(Fake(), '10c'), 378)
        self.assertEqual(tk_pixels(Fake(), '800'), 800)
        self.assertEqual(tk_pixels(Fake(), ''), 0)
        self.assertNotIn("int(c.cget('width')", (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))

    def test_capital_vision_overlay_uses_force_alpha(self):
        from PIL import Image
        base = Image.new('RGB', (40, 40), '#68724e')
        out = overlay_force_diamonds(base, [{
            'points': [(4, 20), (20, 4), (36, 20), (20, 36)],
            'rgb': (200, 40, 40),
            'center': True,
        }])
        self.assertEqual(out.mode, 'RGBA')
        pixel = out.getpixel((20, 20))
        self.assertGreater(pixel[0], pixel[1])
        self.assertGreater(pixel[3], 0)
        src = (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8')
        self.assertIn('capital_marks(self.state)', src)
        self.assertIn('_city_vision_diamonds', src)
        self.assertIn('paint_mbm_vision', src)
        locator = (ROOT / 'app/native_city_map.py').read_text(encoding='utf-8')
        self.assertIn('MIN_ZOOM', locator)
        self.assertIn('菱格视野 都5/城3/关1', locator)
        self.assertIn('逐格描边', locator)
        self.assertNotIn('主城中心半透明势力色', locator)
        self.assertNotIn('关隘不画', locator)
        self.assertNotIn('主城中心', locator)
        self.assertIn('self.zoom = MIN_ZOOM', (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8'))
        self.assertIn('city_marker_text', src)
        self.assertIn('点城看生命值与士气', src)
        self.assertIn('_move_overlay_items', src)
        self.assertIn('_range_overlay_items', src)
        self.assertIn("'★ ' if own else ''", src)
        self.assertIn("self._rgb(mark.get('force_id'))", src)
        self.assertIn('def _force_name_tag', src)
        self.assertIn('点部队看前进格', src)
        self.assertIn("text='独立大地图'", src)
        self.assertIn("fg='#302c22'", src)
        self.assertNotIn("outline='#c32620'", src)
        self.assertIn('_draw_produce_rings', src)
        self.assertIn('cities_over_produce', src)
        self.assertIn('可产圈', src)
        self.assertIn('总分(步1骑3弓1)', src)
        self.assertIn('cities_over_produce_score', src)
        self.assertIn('_show_city_card', src)
        self.assertIn("win.title('城池资料')", src)
        self.assertIn('city_card_text', src)
        self.assertIn('panorama-city-hp-unit-move', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        model = (ROOT / 'app/panorama_model.py').read_text(encoding='utf-8')
        overlay_fn = model[model.index('def overlay_force_diamonds'):model.index('def paint_mbm_vision')]
        self.assertNotIn('outline=', overlay_fn)
        tile = Image.new('RGB', (96, 48), '#68724e')
        diamond = overlay_force_diamonds(tile, [{
            'cell': (0, 0),
            'rgb': (200, 40, 40),
            'center': True,
        }], mbm_box=(0, 0, 96, 48))
        self.assertGreater(diamond.getpixel((48, 24))[0], diamond.getpixel((48, 24))[1])
        self.assertEqual(diamond.getpixel((1, 1))[:3], (0x68, 0x72, 0x4e))
        stretched = overlay_force_diamonds(
            Image.new('RGB', (192, 48), '#68724e'),
            [{'cell': (0, 0), 'rgb': (200, 40, 40)}],
            mbm_box=(0, 0, 96, 48),
        )
        self.assertEqual(stretched.getpixel((2, 1))[:3], (0x68, 0x72, 0x4e))
        self.assertGreater(stretched.getpixel((96, 24))[0], stretched.getpixel((96, 24))[1])

    def test_ranges_match_original_x86_engine_fixtures(self):
        import json
        fixture = json.loads((ROOT / 'bridge/vision_engine_cases.json').read_text())
        for case in fixture['cases']:
            with self.subTest(center=case['center'], radius=case['radius']):
                self.assertEqual([list(cell) for cell in vision_cells(case['center'], case['radius'])], case['cells'])

    def test_three_site_ranges_and_shared_grid_edge(self):
        from PIL import Image
        for kind, capital, expected in [('city', True, 61), ('city', False, 25), ('barrier', True, 5)]:
            state = {'entities': {
                'lords': [{'force_id': 2, 'capital_city_id': 8 if capital else 9}],
                'cities_and_barriers': [{'city_id': 8, 'type': kind,
                    'owner_raw': 2, 'world_xy_raw': [40, 80]}],
            }}
            self.assertEqual(len(vision_overlay_cells(state)), expected)
        items = [{'cell': cell, 'rgb': (120, 50, 170)}
                 for cell in vision_cells((2, 4), 1)]
        base = Image.new('RGB', (480, 240), (70, 80, 60))
        image = overlay_force_diamonds(base, items)
        # Shared diagonal edge midpoint vs nearby interior: clearly visible,
        # and drawing order does not erase it.
        self.assertNotEqual(image.getpixel((264, 108)), image.getpixel((264, 111)))
        self.assertEqual(image.tobytes(), overlay_force_diamonds(base, list(reversed(items))).tobytes())

    def test_far_zoom_hides_buildings_and_uses_mip(self):
        from tactical_terrain import mip_factor
        self.assertGreater(DETAIL_ZOOM, MIN_ZOOM)
        self.assertTrue(show_kind_at_zoom('城关', 0.5))
        self.assertTrue(show_kind_at_zoom('部队', 0.5))
        self.assertFalse(show_kind_at_zoom('建筑', 1.9))
        self.assertFalse(show_kind_at_zoom('陷阱', 1.9))
        self.assertTrue(show_kind_at_zoom('建筑', 2.0))
        self.assertTrue(show_kind_at_zoom('陷阱', 6.0))
        self.assertEqual(mip_factor(400, 1400), 1)
        self.assertEqual(mip_factor(9600, 1400), 8)
        locator = (ROOT / 'app/native_city_map.py').read_text(encoding='utf-8')
        self.assertIn('paint_mbm_vision', locator)
        self.assertIn('show_kind_at_zoom', locator)
        path = ROOT / 'app/assets/SanInet.mbm'
        if path.is_file():
            from tactical_terrain import Terrain
            terrain = Terrain(path)
            view = terrain.crop_to((0, 0, 9600, 4000), 200, 80)
            self.assertEqual(view.size, (200, 80))
            again = terrain.crop_to((0, 0, 9600, 4000), 200, 80)
            self.assertEqual(again.size, (200, 80))

    def test_far_zoom_keeps_vision_on_city_when_view_leaves_map(self):
        from PIL import Image
        from tactical_terrain import blit_mip_box, world_pixel

        factor = 8
        mip = Image.new('RGB', (10, 10), (10, 20, 30))
        mip.putpixel((0, 0), (255, 0, 0))
        placed = blit_mip_box(mip, factor, (0, -32, 80, 112), 80, 144)
        self.assertEqual(placed.getpixel((0, 0)), (0x68, 0x72, 0x4e))
        self.assertEqual(placed.getpixel((0, 32))[0], 255)

        class _Flat:
            def crop_to(self, box, dest_w, dest_h):
                return Image.new('RGB', (dest_w, dest_h), (0x68, 0x72, 0x4e))

        # Zoomed-out window: taller than the map, same shape as the south shift.
        box = (-400, -200, 9000, 6000)
        dest_w, dest_h = 620, 620
        cell = (59, 195)
        image = paint_mbm_vision(_Flat(), box, dest_w, dest_h, [{
            'cell': cell, 'rgb': (220, 40, 60), 'center': True,
        }])
        px, py = world_pixel(*cell)
        sx = int(round((px - box[0]) * dest_w / (box[2] - box[0])))
        sy = int(round((py - box[1]) * dest_h / (box[3] - box[1])))
        self.assertGreater(image.getpixel((sx, sy))[0], image.getpixel((sx, sy))[1])
        stretched = int(round(py * dest_h / 4872))
        self.assertGreater(abs(stretched - sy), 40)
        self.assertEqual(image.getpixel((sx, min(dest_h - 1, stretched)))[:3], (0x68, 0x72, 0x4e))


if __name__ == '__main__':
    unittest.main()
