import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'bridge')]

from panorama_model import vision_cells
from unit_move import (
    bank_sand_sample, cheap_steps, city_hp_text, city_marker_text, city_morale_text, classify_mbm, enter_cost, hill_sample, lighten_rgb,
    move_brief, move_class, move_overlay_cells, move_points, plains_steps,
    reachable_cells, terrain_kind, tile_neighbors, unit_has_navy, website_skill_names,
)


class UnitMoveTests(unittest.TestCase):
    def test_city_hp_and_lighten(self):
        self.assertEqual(city_hp_text({'defense': [320, 800]}), '生命值 320/800')
        self.assertEqual(city_hp_text({'defense': 12}), '生命值 12')
        self.assertEqual(city_hp_text({}), '生命值 未解析')
        self.assertEqual(city_morale_text({'type': 'city', 'morale': 80}), '士气 80')
        self.assertEqual(city_morale_text({'type': 'city', 'morale': 0}), '士气 0')
        self.assertEqual(city_morale_text({'type': 'city', 'morale': 101}), '士气 未解析')
        self.assertIsNone(city_morale_text({'type': 'barrier', 'morale': 80}))
        self.assertEqual(city_marker_text({'type': 'city', 'defense': [100, 500], 'morale': 80}), '生命值 100/500 · 士气 80')
        self.assertEqual(city_marker_text({'type': 'barrier', 'defense': [100, 500]}), '生命值 100/500')
        pale = lighten_rgb((40, 80, 200), 0.5)
        self.assertGreater(pale[0], 40)
        self.assertGreater(pale[2], 200)
        self.assertLess(pale[2], 255)

    def test_website_move_points(self):
        land = {'unit_kind': '重装步兵', 'size_index': 0}
        mid = {'unit_kind': '强弓兵', 'soldiers_candidate': 25000}
        cav = {'unit_kind': '铁骑兵', 'size_index': 2, 'general_ids': []}
        navy = {'unit_kind': '水军', 'size_index': 1}
        wagon = {'unit_kind': '粮车', 'size_index': 0}
        state = {'entities': {'generals': []}}
        self.assertEqual(move_class(state, land), 'land')
        self.assertEqual(move_points(state, land), 12)
        self.assertEqual(move_points(state, mid), 10)
        self.assertEqual(move_points(state, cav), 10)
        self.assertEqual(move_points(state, navy), 10)
        self.assertEqual(move_points(state, wagon), 14)
        horse = {
            'entities': {'generals': [{
                'general_id_raw': 7, 'name': '赵云',
                'attributes': {'lead': 90, 'war': 90, 'intel': 80, 'pol': 70, 'cha': 80},
            }]}
        }
        with patch('unit_move.unit_has_horse', return_value=True):
            self.assertEqual(move_points(horse, {'unit_kind': '骑兵', 'size_index': 0}), 18)

    def test_small_infantry_plains_is_four_cells(self):
        self.assertEqual(plains_steps(12), 4)
        self.assertEqual(plains_steps(10), 3)
        self.assertEqual(plains_steps(8), 2)
        origin = (40, 80)
        unit = {'unit_kind': '重装步兵', 'size_index': 0, 'world_xy_raw': list(origin)}
        state = {'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': []}}
        with patch('unit_move.road_cells', return_value=set()):
            self.assertEqual(enter_cost(state, origin), 3)
            reach = reachable_cells(state, unit)
        self.assertEqual(move_points(state, unit), 12)
        self.assertEqual(set(reach), set(vision_cells(origin, 4)))
        ring5 = set(vision_cells(origin, 5)) - set(vision_cells(origin, 4))
        self.assertTrue(ring5)
        self.assertFalse(any(cell in reach for cell in ring5))
        self.assertIn('平地4格', move_brief(state, unit, reach))
        self.assertIn('道路6格', move_brief(state, unit, reach))
        self.assertIn('无水军水面不通行', move_brief(state, unit, reach))
        with patch('unit_move.road_cells', return_value=set()):
            self.assertEqual({item['cell'] for item in move_overlay_cells(state, unit)}, set(reach) - {origin})

    def _water_path(self, origin):
        water = [origin]
        cell = origin
        for _ in range(7):
            cell = max(tile_neighbors(*cell), key=lambda item: (item[0], item[1]))
            water.append(cell)
        raw = bytearray(101 * 202)
        for x, y in water[1:]:
            raw[x * 202 + y] = 4
        return water, raw

    def test_road_extends_without_navy_but_water_does_not(self):
        self.assertEqual(cheap_steps(12), 6)
        self.assertEqual(classify_mbm((80, 140, 200)), '河川')
        self.assertEqual(classify_mbm((230, 220, 170)), '道路')
        self.assertEqual(classify_mbm((176, 186, 140)), '平地')
        self.assertEqual(website_skill_names({'name': '中山王'}), {'骑马', '埋伏', '无双', '奇袭', '攻城'})
        self.assertNotIn('水军', website_skill_names({'name': '司马错'}))
        origin = (40, 80)
        water, raw = self._water_path(origin)
        unit = {'unit_kind': '重装步兵', 'size_index': 0, 'world_xy_raw': list(origin)}
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': []},
        }
        away = origin
        for _ in range(5):
            away = min(tile_neighbors(*away), key=lambda item: (item[0], item[1]))
        with patch('unit_move.road_cells', return_value=set()):
            self.assertIsNone(enter_cost(state, water[1], unit=unit))
            self.assertEqual(enter_cost(state, (38, 78), unit=unit), 3)
            self.assertEqual(enter_cost(state, away, unit=unit), 3)
            reach = reachable_cells(state, unit)
        self.assertNotIn(water[1], reach)
        self.assertNotIn(away, reach)

    def test_navy_or_wuyue_uses_river_cost_two(self):
        origin = (40, 80)
        water, raw = self._water_path(origin)
        land = {'unit_kind': '重装步兵', 'size_index': 0, 'world_xy_raw': list(origin)}
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [land], 'lords': [], 'cities_and_barriers': []},
        }
        with patch('unit_move.road_cells', return_value=set()), patch('unit_move.unit_has_navy', return_value=True):
            self.assertEqual(enter_cost(state, water[1], unit=land), 2)
            reach = reachable_cells(state, land)
        self.assertIn(water[6], reach)
        self.assertNotIn(water[7], reach)
        navy = {'unit_kind': '水军', 'size_index': 0, 'world_xy_raw': list(origin)}
        self.assertTrue(unit_has_navy({'entities': {'lords': []}}, navy))
        wuyue = {'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 3, 'world_xy_raw': list(origin)}
        cards = {
            'entities': {
                'lords': [{'force_id': 3, 'hand_cards': {'slots': [{'card_id': 25, 'name': '吴越春秋'}]}}],
            }
        }
        self.assertTrue(unit_has_navy(cards, wuyue))

    def test_units_and_enemy_cities_block_path(self):
        origin = (40, 80)
        # Wall of enemy units across the northern neighbours.
        wall = [cell for cell in tile_neighbors(*origin)]
        unit = {'unit_id': 1, 'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 15,
                'world_xy_raw': list(origin)}
        enemies = [
            {'unit_id': 10 + i, 'unit_kind': '强化骑兵', 'size_index': 0, 'owner_raw': 5,
             'world_xy_raw': list(cell)} for i, cell in enumerate(wall)
        ]
        state = {'entities': {'field_units': [unit] + enemies, 'lords': [], 'cities_and_barriers': []}}
        with patch('unit_move.road_cells', return_value=set()):
            reach = reachable_cells(state, unit)
        self.assertEqual(set(reach), {origin})
        # Enemy city blocks; own city does not.
        enemy_city = {'city_id': 3, 'type': 'city', 'owner_raw': 5, 'world_xy_raw': [40, 82]}
        own_city = {'city_id': 4, 'type': 'city', 'owner_raw': 15, 'world_xy_raw': [40, 78]}
        state2 = {'entities': {'field_units': [unit], 'lords': [],
                               'cities_and_barriers': [enemy_city, own_city]}}
        with patch('unit_move.road_cells', return_value=set()):
            reach2 = reachable_cells(state2, unit)
        self.assertNotIn((40, 82), reach2)
        self.assertIn((40, 78), reach2)

    def test_hill_sample_and_own_city_passable(self):
        # 深橄榄绿丘陵样本（南皮西北无格带取样）算丘陵；平原亮草、水、路不算。
        self.assertTrue(hill_sample((106, 133, 78)))
        self.assertTrue(hill_sample((142, 172, 96)))
        self.assertFalse(hill_sample((159, 194, 114)))   # 平原草
        self.assertFalse(hill_sample((50, 112, 161)))    # 水
        self.assertFalse(hill_sample((253, 239, 181)))   # 路
        # 己方城可穿行、格上不画（平原城在范围正中、对岸仍有格）。
        origin = (40, 80)
        city_cell = tile_neighbors(*origin)[0]
        beyond = next(c for c in tile_neighbors(*city_cell) if c != origin)
        unit = {'unit_id': 1, 'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 15,
                'world_xy_raw': list(origin)}
        own_city = {'city_id': 4, 'type': 'city', 'owner_raw': 15, 'world_xy_raw': list(city_cell)}
        state = {'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': [own_city]}}
        with patch('unit_move.road_cells', return_value=set()):
            reach = reachable_cells(state, unit)
            painted = {item['cell'] for item in move_overlay_cells(state, unit)}
        self.assertIn(city_cell, reach)
        self.assertNotIn(city_cell, painted)
        self.assertEqual(reach[city_cell], 9)
        self.assertEqual(reach[beyond], 6)  # 穿城续走剩 6，不是绕路。
        self.assertIn(beyond, painted)

    def test_enemy_zoc_stops_movement_but_own_units_do_not(self):
        origin = (40, 80)
        # 敌军在正北两格；它的四邻是控制区，走进即停，敌后到不了。
        enemy_cell = (40, 78)
        unit = {'unit_id': 1, 'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 15,
                'world_xy_raw': list(origin)}
        enemy = {'unit_id': 2, 'unit_kind': '强化骑兵', 'size_index': 0, 'owner_raw': 5,
                 'world_xy_raw': list(enemy_cell)}
        state = {'entities': {'field_units': [unit, enemy], 'lords': [], 'cities_and_barriers': []}}
        with patch('unit_move.road_cells', return_value=set()):
            reach = reachable_cells(state, unit)
        self.assertNotIn(enemy_cell, reach)
        self.assertNotIn((40, 76), reach)  # 敌后正北
        zoc_ring = set(tile_neighbors(*enemy_cell))
        self.assertTrue(any(cell in reach for cell in zoc_ring))  # 贴脸格可达（停步）
        # 同一格换成自己人：只占格，不锁邻格，可以绕过去。
        friend = dict(enemy, owner_raw=15)
        state2 = {'entities': {'field_units': [unit, friend], 'lords': [], 'cities_and_barriers': []}}
        with patch('unit_move.road_cells', return_value=set()):
            reach2 = reachable_cells(state2, unit)
        self.assertNotIn(enemy_cell, reach2)
        self.assertIn((40, 76), reach2)

    def test_buildings_passable_but_not_painted_and_wet_cells_not_roads(self):
        # 练兵所/牧场等建筑：格上不画网格，但可以穿行（2026-09-17 三步兵场景标定）。
        origin = (40, 80)
        unit = {'unit_id': 1, 'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 15,
                'world_xy_raw': list(origin)}
        farm = {'type': 'horse_farm', 'owner_raw': 15, 'world_xy_raw': [40, 78]}
        state = {'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': [],
                              'production_buildings': [farm]}}
        with patch('unit_move.road_cells', return_value=set()):
            reach = reachable_cells(state, unit)
            painted = {item['cell'] for item in move_overlay_cells(state, unit)}
        self.assertIn((40, 78), reach)      # 可进可穿。
        self.assertIn((40, 76), reach)      # 建筑后方也能到（穿行）。
        self.assertNotIn((40, 78), painted)  # 但建筑格本身不画。
        self.assertIn((40, 76), painted)
        # 道路只看细长连通线；水色≥3% 的临水格否决（海岬沙滩不给借道）。
        class FakeTerrain:
            pass
        t = FakeTerrain()
        t._road_frac_cache = {(1, 1): (0.10, 0.04), (2, 2): (0.10, 0.00), (3, 3): (0.0, 0.0)}
        with patch('unit_move._mbm_samples', return_value=[]):
            self.assertEqual(terrain_kind(None, (2, 2), t), '道路')
            self.assertNotEqual(terrain_kind(None, (1, 1), t), '道路')
            self.assertEqual(terrain_kind(None, (3, 3), t), '平地')

    def test_ji_south_dry_grass_is_not_a_road_shortcut(self):
        # 蓟南干草沙斑与路色重叠，形状是团块（两次腐蚀仍存活>45%），
        # 暖色兜底会把 (67,32)/(66,33)/(67,34) 判成路，12 点步兵多走出
        # (66,35)(67,35) 贴到南皮练兵所。细长真路 (64,26) 仍应是路。
        try:
            from tactical_terrain import Terrain
            terrain = Terrain()
        except (FileNotFoundError, ValueError):
            self.skipTest('SanInet.mbm missing')
        origin = (66, 30)
        unit = {
            'unit_id': 31, 'unit_kind': '重装步兵', 'size_index': 0,
            'owner_raw': 15, 'world_xy_raw': list(origin),
        }
        state = {'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': []}}
        for cell in ((67, 32), (66, 33), (67, 34), (64, 31)):
            self.assertEqual(terrain_kind(state, cell, terrain), '平地', cell)
        self.assertEqual(terrain_kind(state, (64, 26), terrain), '道路')
        painted = {item['cell'] for item in move_overlay_cells(state, unit, terrain)}
        self.assertNotIn((66, 35), painted)
        self.assertNotIn((67, 35), painted)
        self.assertIn((64, 26), painted)

    def test_pingyuan_own_city_pass_reaches_coast(self):
        # 平原 (67,52) 在骑兵西侧；游戏在城东海岸仍有格。己方城可穿。
        # 水中格 (69,57) 水色 29% 不能上；沙滩 (70,56) 17% 可走。
        try:
            from tactical_terrain import Terrain
            terrain = Terrain()
        except (FileNotFoundError, ValueError):
            self.skipTest('SanInet.mbm missing')
        cav = {
            'unit_id': 0, 'unit_kind': '强化骑兵', 'size_index': 0, 'owner_raw': 15,
            'world_xy_raw': [66, 51], 'general_ids': [11],
        }
        inf = {'unit_id': 1, 'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 15,
               'world_xy_raw': [66, 53]}
        wag = {'unit_id': 2, 'unit_kind': '运输兵', 'size_index': 0, 'owner_raw': 15,
               'world_xy_raw': [67, 51]}
        city = {'city_id': 5, 'type': 'city', 'name': '平原', 'owner_raw': 15,
                'world_xy_raw': [67, 52]}
        state = {'entities': {
            'field_units': [cav, inf, wag], 'lords': [],
            'cities_and_barriers': [city],
            'generals': [{'general_id_raw': 11, 'name': '中山王'}],
        }}
        with patch('unit_move.unit_has_horse', return_value=True):
            painted = {item['cell'] for item in move_overlay_cells(state, cav, terrain)}
            reach = reachable_cells(state, cav, terrain)
        self.assertIn((67, 52), reach)
        self.assertNotIn((67, 52), painted)
        self.assertIn((70, 53), painted)   # 城东海岸路
        self.assertIn((69, 55), painted)
        self.assertNotIn((70, 55), painted)  # 河川
        self.assertNotIn((69, 57), painted)  # 水中格
        self.assertEqual(terrain_kind(state, (69, 57), terrain), '河川')
        self.assertEqual(terrain_kind(state, (70, 56), terrain), '平地')

    def test_jinyang_riverbank_sand_opens_east_road(self):
        # 晋王步兵 (50,46)：东岸黄沙混水色，不能当河川，否则只剩城西几格。
        self.assertTrue(bank_sand_sample((173, 164, 104)))
        self.assertTrue(bank_sand_sample((191, 197, 110)))
        self.assertFalse(bank_sand_sample((89, 159, 164)))
        try:
            from tactical_terrain import Terrain
            terrain = Terrain()
        except (FileNotFoundError, ValueError):
            self.skipTest('SanInet.mbm missing')
        unit = {
            'unit_id': 0, 'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 7,
            'world_xy_raw': [50, 46],
        }
        city = {'city_id': 7, 'type': 'city', 'name': '晋阳', 'owner_raw': 7,
                'world_xy_raw': [49, 47]}
        state = {'entities': {
            'field_units': [unit], 'lords': [],
            'cities_and_barriers': [city],
            'production_buildings': [
                {'type': 'parade_ground', 'owner_raw': 7, 'world_xy_raw': [48, 47]},
                {'type': 'horse_farm', 'owner_raw': 7, 'world_xy_raw': [48, 48]},
            ],
        }}
        self.assertNotEqual(terrain_kind(state, (50, 45), terrain), '河川')
        self.assertNotEqual(terrain_kind(state, (50, 48), terrain), '河川')
        self.assertEqual(terrain_kind(state, (50, 47), terrain), '河川')
        painted = {item['cell'] for item in move_overlay_cells(state, unit, terrain)}
        self.assertIn((50, 45), painted)
        self.assertIn((50, 48), painted)
        self.assertIn((50, 49), painted)
        self.assertIn((51, 51), painted)
        self.assertNotIn((50, 47), painted)

    def test_jiangling_coast_is_not_a_cheap_road(self):
        # 江陵南岸水色格不能当路；骑兵(51,123) 16 点不该沿水多画出 (49,129)。
        try:
            from tactical_terrain import Terrain
            terrain = Terrain()
        except (FileNotFoundError, ValueError):
            self.skipTest('SanInet.mbm missing')
        cav = {
            'unit_id': 0, 'unit_kind': '强化骑兵', 'size_index': 0, 'owner_raw': 4,
            'world_xy_raw': [51, 123],
        }
        inf = {'unit_id': 1, 'unit_kind': '强化步兵', 'size_index': 0, 'owner_raw': 4,
               'world_xy_raw': [52, 123]}
        wag = {'unit_id': 2, 'unit_kind': '运输兵', 'size_index': 0, 'owner_raw': 4,
               'world_xy_raw': [51, 125]}
        city = {'city_id': 4, 'type': 'city', 'name': '江陵', 'owner_raw': 4,
                'world_xy_raw': [52, 124]}
        state = {'entities': {
            'field_units': [cav, inf, wag], 'lords': [],
            'cities_and_barriers': [city],
            'production_buildings': [
                {'type': 'parade_ground', 'owner_raw': 4, 'world_xy_raw': [50, 123]},
                {'type': 'horse_farm', 'owner_raw': 4, 'world_xy_raw': [50, 125]},
                {'type': 'bow_studio', 'owner_raw': 4, 'world_xy_raw': [51, 121]},
            ],
        }}
        self.assertEqual(terrain_kind(state, (52, 125), terrain), '河川')
        self.assertEqual(terrain_kind(state, (49, 129), terrain), '河川')
        painted = {item['cell'] for item in move_overlay_cells(state, cav, terrain)}
        self.assertNotIn((49, 129), painted)
        self.assertNotIn((52, 125), painted)
        self.assertNotIn((51, 127), painted)

    def test_engine_water_opens_navy_path_mbm_would_call_plains(self):
        # 寿春：小地图把宽河面判成平地，引擎 4 才是河。水军走得动，步兵下不去。
        origin = (40, 80)
        water, raw = self._water_path(origin)
        cav = {'unit_id': 0, 'unit_kind': '强化骑兵', 'size_index': 0, 'owner_raw': 11,
               'world_xy_raw': list(origin)}
        inf = {'unit_id': 1, 'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 11,
               'world_xy_raw': list(origin)}
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [cav], 'lords': [], 'cities_and_barriers': []},
        }
        plains = (80, 160, 140)
        with patch('unit_move._mbm_samples', return_value=[plains] * 5), patch(
                'unit_move.road_fraction', return_value=(0.0, 0.04)), patch(
                'unit_move.road_cells', return_value=set()), patch(
                'unit_move.unit_has_navy', return_value=True), patch(
                'unit_move.unit_has_horse', return_value=True):
            self.assertEqual(terrain_kind(state, water[1], object()), '河川')
            self.assertEqual(enter_cost(state, water[1], object(), unit=cav), 2)
            reach = reachable_cells(state, cav)
            self.assertIn(water[6], reach)
        inf_state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [inf], 'lords': [], 'cities_and_barriers': []},
        }
        with patch('unit_move.road_cells', return_value=set()):
            self.assertIsNone(enter_cost(inf_state, water[1], unit=inf))
            self.assertNotIn(water[1], reachable_cells(inf_state, inf))

    def test_engine_land_suppresses_mbm_false_river(self):
        # 公孙瓒 (73,98)：MBM 2/5 水色会判河川，引擎非 4/6 则步兵可走。
        cell = (73, 98)
        raw = bytearray(101 * 202)
        raw[73 * 202 + 98] = 0
        origin = (73, 97)
        unit = {'unit_kind': '重装步兵', 'size_index': 0, 'world_xy_raw': list(origin)}
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': []},
        }
        water_rgb = (80, 140, 200)
        with patch('unit_move._mbm_samples', return_value=[water_rgb] * 5), patch(
                'unit_move.road_fraction', return_value=(0.0, 0.50)), patch(
                'unit_move.road_cells', return_value=set()):
            self.assertNotEqual(terrain_kind(state, cell, object()), '河川')
            self.assertEqual(enter_cost(state, cell, object(), unit=unit), 3)
            self.assertIn(cell, reachable_cells(state, unit, object()))

    def test_unread_engine_cell_still_uses_mbm_river(self):
        cell = (40, 81)
        raw = bytearray(101 * 202)
        raw[40 * 202 + 81] = 15
        unit = {'unit_kind': '重装步兵', 'size_index': 0, 'world_xy_raw': [40, 80]}
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': []},
        }
        water_rgb = (80, 140, 200)
        with patch('unit_move._mbm_samples', return_value=[water_rgb] * 5), patch(
                'unit_move.road_fraction', return_value=(0.0, 0.50)), patch(
                'unit_move.road_cells', return_value=set()):
            self.assertEqual(terrain_kind(state, cell, object()), '河川')
            self.assertIsNone(enter_cost(state, cell, object(), unit=unit))

    def test_engine_gate_tile_is_road_not_mbm_hill(self):
        # 函谷/虎牢 type 7：小地图丘陵，引擎是路。
        cell = (45, 81)
        raw = bytearray(101 * 202)
        raw[45 * 202 + 81] = 7
        unit = {'unit_kind': '强化骑兵', 'size_index': 0, 'world_xy_raw': [45, 80]}
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': []},
        }
        hill_rgb = (90, 140, 90)
        with patch('unit_move._mbm_samples', return_value=[hill_rgb] * 5), patch(
                'unit_move.road_fraction', return_value=(0.0, 0.0)), patch(
                'unit_move.hill_sample', return_value=True), patch(
                'unit_move.road_cells', return_value=set()):
            self.assertEqual(terrain_kind(state, cell, object()), '道路')
            self.assertEqual(enter_cost(state, cell, object(), unit=unit), 2)

    def test_engine_water_with_bank_sand_stays_walkable(self):
        # 平原沙滩 (70,56)：引擎 4 但黄沙，无水军可走。
        cell = (70, 56)
        raw = bytearray(101 * 202)
        raw[70 * 202 + 56] = 4
        unit = {'unit_kind': '强化骑兵', 'size_index': 0, 'world_xy_raw': [70, 55]}
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': []},
        }
        sand = (173, 164, 104)
        with patch('unit_move._mbm_samples', return_value=[sand] * 5), patch(
                'unit_move.road_fraction', return_value=(0.0, 0.29)), patch(
                'unit_move.road_cells', return_value=set()):
            self.assertNotEqual(terrain_kind(state, cell, object()), '河川')
            self.assertEqual(enter_cost(state, cell, object(), unit=unit), 3)

    def test_engine_mountain_is_impassable(self):
        # 洛阳南灰岩 type 3：小地图会判平地/路，游戏过不去。
        cell = (51, 85)
        raw = bytearray(101 * 202)
        raw[51 * 202 + 85] = 3
        unit = {'unit_kind': '重装步兵', 'size_index': 0, 'world_xy_raw': [51, 84]}
        cav = {'unit_kind': '强化骑兵', 'size_index': 0, 'world_xy_raw': [51, 84]}
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {'field_units': [unit], 'lords': [], 'cities_and_barriers': []},
        }
        road_rgb = (230, 220, 170)
        with patch('unit_move._mbm_samples', return_value=[road_rgb] * 5), patch(
                'unit_move.road_fraction', return_value=(0.20, 0.0)), patch(
                'unit_move.road_cells', return_value=set()):
            self.assertEqual(terrain_kind(state, cell, object()), '山岳')
            self.assertIsNone(enter_cost(state, cell, object(), unit=unit))
            self.assertIsNone(enter_cost(state, cell, object(), unit=cav))
            self.assertNotIn(cell, reachable_cells(state, unit, object()))

    def test_hulao_south_slope_lets_cavalry_exit(self):
        # 虎牢南坡 (54,83) 与洛阳南同是 type 3。南坡贴关、像素是草坡，游戏可出关；
        # 关西 (53,81) 灰岩邻关但 hill≥3，仍不能走。孟获占 (54,81)，只能经南坡到 (55,82)。
        slope, east, ridge, rock = (54, 83), (55, 82), (53, 81), (51, 85)
        raw = bytearray(101 * 202)
        raw[54 * 202 + 82] = 7
        raw[54 * 202 + 83] = 3
        raw[55 * 202 + 82] = 8
        raw[53 * 202 + 81] = 3
        raw[51 * 202 + 85] = 3
        unit = {
            'unit_kind': '强化骑兵', 'size_index': 0, 'owner_raw': 10,
            'world_xy_raw': [54, 82],
        }
        blocker = {
            'unit_kind': '强化骑兵', 'size_index': 0, 'owner_raw': 10,
            'world_xy_raw': [54, 81],
        }
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {
                'field_units': [unit, blocker],
                'lords': [],
                'cities_and_barriers': [
                    {'name': '虎牢关', 'type': 'barrier', 'owner_raw': 10,
                     'world_xy_raw': [54, 82]},
                    {'name': '洛阳', 'type': 'city', 'owner_raw': 10,
                     'world_xy_raw': [51, 81]},
                ],
            },
        }
        samples = {
            slope: [(208, 195, 128), (103, 79, 48), (252, 229, 153),
                    (156, 185, 106), (156, 182, 99)],
            ridge: [(126, 142, 78), (104, 96, 59), (97, 81, 50),
                    (255, 255, 255), (156, 190, 110)],
            rock: [(254, 237, 171), (167, 199, 119), (147, 171, 93),
                   (104, 96, 59), (103, 79, 48)],
        }
        grass = [(159, 194, 114)] * 5

        def fake_samples(_terrain, cell):
            return samples.get(cell, grass)

        with patch('unit_move._mbm_samples', side_effect=fake_samples), patch(
                'unit_move.road_fraction', return_value=(0.0, 0.0)), patch(
                'unit_move.road_cells', return_value=set()), patch(
                'unit_move.unit_has_horse', return_value=True):
            self.assertEqual(terrain_kind(state, slope, object()), '平地')
            self.assertEqual(enter_cost(state, slope, object(), unit=unit), 3)
            self.assertEqual(terrain_kind(state, ridge, object()), '山岳')
            self.assertIsNone(enter_cost(state, ridge, object(), unit=unit))
            self.assertEqual(terrain_kind(state, rock, object()), '山岳')
            reach = reachable_cells(state, unit, object())
            self.assertIn(slope, reach)
            self.assertIn(east, reach)
            self.assertNotIn(ridge, reach)
            self.assertNotIn(rock, reach)

    def test_city_without_engine_road_does_not_cheapen_hill_climb(self):
        # 襄阳 (48,110) type 0：屋顶/穿城路像素会判路。进城按平地 3，
        # 12 点步兵到南坡 (47,111) 剩 4，再进 (48,112) 丘陵 5 不够。
        # 弓兵从邻格 (48,111) 上坡仍可走。虎牢 type 7 仍是路。
        city, slope, second, origin, bow_cell = (
            (48, 110), (47, 111), (48, 112), (47, 109), (48, 111),
        )
        raw = bytearray(101 * 202)
        raw[47 * 202 + 109] = 8
        raw[48 * 202 + 110] = 0
        raw[47 * 202 + 111] = 2
        raw[48 * 202 + 112] = 2
        raw[48 * 202 + 111] = 8
        inf = {
            'unit_kind': '重装步兵', 'size_index': 0, 'owner_raw': 2,
            'world_xy_raw': list(origin),
        }
        bow = {
            'unit_kind': '强弓兵', 'size_index': 0, 'owner_raw': 2,
            'world_xy_raw': list(bow_cell),
        }
        state = {
            'terrain_grid': {'width': 101, 'height': 202, 'types': raw.hex()},
            'entities': {
                'field_units': [inf, bow],
                'lords': [],
                'cities_and_barriers': [{
                    'name': '襄阳', 'type': 'city', 'owner_raw': 2,
                    'world_xy_raw': list(city),
                }],
            },
        }
        samples = {
            city: [(253, 239, 181), (162, 198, 118), (162, 198, 118),
                   (154, 190, 113), (164, 202, 122)],
            slope: [(147, 171, 93), (166, 191, 103), (114, 125, 69),
                    (99, 104, 58), (183, 208, 117)],
            second: [(126, 142, 78), (183, 208, 117), (105, 113, 63),
                     (131, 148, 81), (134, 156, 86)],
        }
        grass = [(159, 194, 114)] * 5

        def fake_samples(_terrain, cell):
            return samples.get(cell, grass)

        def fake_road(_terrain, cell):
            if cell == city:
                return (0.13, 0.0)
            return (0.0, 0.0)

        with patch('unit_move._mbm_samples', side_effect=fake_samples), patch(
                'unit_move.road_fraction', side_effect=fake_road), patch(
                'unit_move.road_cells', return_value=set()):
            self.assertEqual(terrain_kind(state, city, object()), '平地')
            self.assertEqual(enter_cost(state, city, object(), unit=inf), 3)
            self.assertEqual(terrain_kind(state, slope, object()), '丘陵森林')
            inf_reach = reachable_cells(state, inf, object())
            self.assertEqual(inf_reach.get(city), 9)
            self.assertEqual(inf_reach.get(slope), 4)
            self.assertNotIn(second, inf_reach)
            bow_reach = reachable_cells(state, bow, object())
            self.assertIn(second, bow_reach)

    def test_same_force_move_overlay_is_marked(self):
        unit = {'unit_id': 3, 'unit_kind': '步兵', 'size_index': 0, 'owner_raw': 2,
                'world_xy_raw': [40, 80]}
        state = {
            'entities': {
                'lords': [{'force_id': 2, 'capital_city_id': 8}],
                'cities_and_barriers': [{
                    'city_id': 8, 'type': 'city', 'owner_raw': 2, 'world_xy_raw': [40, 80],
                }],
                'field_units': [unit],
            }
        }
        with patch('unit_move.road_cells', return_value=set()):
            items = {item['cell']: item for item in move_overlay_cells(state, unit)}
        self.assertNotIn((40, 80), items)  # 原点兼己方城，不画。
        neighbor = next(iter(items))
        self.assertTrue(items[neighbor]['same_as_city'] or not items[neighbor]['center'])
        self.assertIn('前进', move_brief(state, unit, { (40, 80): 12 }))


if __name__ == '__main__':
    unittest.main()
