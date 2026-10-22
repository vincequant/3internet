import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'bridge')]

from panorama_model import capital_marks, vision_cells, world_xy
from stealth_raid import (
    SOURCE, SPRITE_KIND, UNIT_VISION, choose_origin_city, default_cavalry_spec, default_wagon_spec,
    enemy_vision_sets, field_unit_at, format_raid_brief, hostile_force_ids, kind_spec, origin_watched,
    city_ring_cell, city_ring_cells, plan_stealth_raid, raid_board, raid_move_overlay,
    raid_plans_payload, raid_reach_cells, raid_targets, resolve_raid_endpoints, sim_unit, split_turns,
    unit_move_overlay, unit_reach_cells, unit_vision_radius,
)
from unit_move import tile_neighbors


def plains_hex():
    return bytes(101 * 202).hex()


def walk(start, n, key=lambda cell: (cell[1], cell[0])):
    cell = start
    path = [cell]
    for _ in range(n):
        cell = max(tile_neighbors(*cell), key=key)
        path.append(cell)
    return path


def confirmed(entities, player=1):
    rels = [0] * 22
    for lord in entities.get('lords') or []:
        fid = lord.get('force_id')
        if fid != player:
            rels[fid] = 1
    for lord in entities.get('lords') or []:
        if lord.get('force_id') == player:
            lord['diplomacy_relations'] = rels
    return {
        'player_force_id': player,
        'player_identity': {'status': 'confirmed', 'force_id': player},
        'terrain_grid': {'width': 101, 'height': 202, 'types': plains_hex()},
        'entities': entities,
    }


class StealthRaidTests(unittest.TestCase):
    def test_defaults_and_spy_radius(self):
        self.assertEqual(default_cavalry_spec()['points'], 18)
        self.assertEqual(default_wagon_spec()['points'], 14)
        self.assertEqual(kind_spec('骑兵')['points'], 18)
        self.assertEqual(kind_spec('粮草兵')['points'], 14)
        self.assertEqual(kind_spec('步兵')['points'], 12)
        self.assertEqual(kind_spec('弓兵')['points'], 12)
        self.assertEqual(unit_vision_radius({}, {'unit_kind': '骑兵'}), UNIT_VISION)
        self.assertEqual(unit_vision_radius({}, {'vision_radius': 4}), 4)
        self.assertIn('末回合才进目标主城视野', SOURCE)

    def test_split_turns_counts_full_mp_chunks(self):
        path = [(0, 0)]
        # fake linear costs of 3
        cells = [(i, 0) for i in range(7)]
        cost = {cell: 3 for cell in cells[1:]}
        chunks = split_turns(cells, 18, lambda cell: cost.get(cell, 3))
        self.assertEqual(len(chunks), 1)
        long = [(i, 0) for i in range(13)]
        chunks = split_turns(long, 18, lambda cell: 3)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0][-1], (6, 0))
        self.assertEqual(chunks[1][-1], (12, 0))

    def _raid_state(self, enemy_cell=None, spy=False, extra_units=None):
        path = walk((40, 40), 28)
        origin, dest = path[0], path[-1]
        units = extra_units or []
        if enemy_cell is None:
            enemy_cell = path[12]
        enemy = {
            'unit_id': 9, 'unit_kind': '步兵', 'owner_raw': 2, 'size_index': 0,
            'world_xy_raw': list(enemy_cell),
        }
        if spy:
            enemy['vision_radius'] = 4
        units = [enemy] + units
        state = confirmed({
            'lords': [
                {'force_id': 1, 'name': '鲁', 'capital_city_id': 1},
                {'force_id': 2, 'name': '汉', 'capital_city_id': 2},
            ],
            'cities_and_barriers': [
                {'city_id': 1, 'name': '曲阜', 'type': 'city', 'owner_raw': 1, 'world_xy_raw': list(origin)},
                {'city_id': 2, 'name': '洛阳', 'type': 'city', 'owner_raw': 2, 'world_xy_raw': list(dest)},
            ],
            'field_units': units,
            'generals': [],
        })
        return state, origin, dest, enemy_cell

    def test_path_detours_enemy_unit_vision_and_dashes_last_turn(self):
        state, origin, dest, enemy = self._raid_state()
        dest_row = state['entities']['cities_and_barriers'][1]
        with patch('unit_move.road_cells', return_value=set()):
            plan = plan_stealth_raid(state, origin, dest_row)
        self.assertTrue(plan['ok'], plan.get('error'))
        self.assertEqual(plan['dest_name'], '洛阳')
        self.assertGreaterEqual(plan['cavalry_turns'], 2)
        self.assertGreaterEqual(plan['wagon_turns'], plan['hidden_turns'])
        self.assertEqual(plan['arrive_calendar'], 1 + plan['cavalry_turns'])
        hostile = hostile_force_ids(state, 2)
        self.assertEqual(hostile, {2})
        vision = enemy_vision_sets(state, hostile, dest)
        hidden = set(plan['hidden_path'])
        self.assertTrue(hidden)
        self.assertFalse(hidden & vision['other'])
        self.assertNotIn(enemy, plan['full_path'])
        for cell in plan['hidden_path'][:-1]:
            self.assertNotIn(cell, vision['dest'])
        self.assertEqual(plan['dash_path'][0], plan['staging'])
        self.assertIn(plan['dash_path'][-1], set(tile_neighbors(*dest)) | {dest})
        self.assertIn('粮车', plan['brief'])
        self.assertIn('洛阳', plan['brief'])
        self.assertIn('移动力', format_raid_brief(plan))
        ox, _, dest_row = resolve_raid_endpoints(state, '城关', dest_row, 2)
        self.assertEqual(ox, origin)
        self.assertEqual(world_xy(dest_row), dest)

    def test_spy_vision_is_wider_than_normal(self):
        state, origin, dest, enemy = self._raid_state(spy=False)
        dest_row = state['entities']['cities_and_barriers'][1]
        spy_state, _, _, _ = self._raid_state(spy=True, enemy_cell=enemy)
        spy_row = spy_state['entities']['cities_and_barriers'][1]
        with patch('unit_move.road_cells', return_value=set()):
            normal = plan_stealth_raid(state, origin, dest_row)
            spy = plan_stealth_raid(spy_state, origin, spy_row)
        self.assertTrue(normal['ok'], normal.get('error'))
        self.assertTrue(spy['ok'], spy.get('error'))
        n_vis = enemy_vision_sets(state, {2}, dest)['other']
        s_vis = enemy_vision_sets(spy_state, {2}, dest)['other']
        self.assertGreater(len(s_vis), len(n_vis))
        self.assertGreaterEqual(len(spy['full_path']), len(normal['full_path']))
        self.assertTrue(set(spy['hidden_path']).isdisjoint(s_vis))

    def test_no_path_when_origin_is_inside_enemy_unit_vision(self):
        origin = (40, 80)
        dest = (40, 120)
        enemy = (40, 80)
        # actually put enemy adjacent covering origin
        nbs = tile_neighbors(*origin)
        enemy = nbs[0]
        state = confirmed({
            'lords': [
                {'force_id': 1, 'name': '鲁', 'capital_city_id': 1},
                {'force_id': 2, 'name': '汉', 'capital_city_id': 2},
            ],
            'cities_and_barriers': [
                {'city_id': 1, 'name': '曲阜', 'type': 'city', 'owner_raw': 1, 'world_xy_raw': list(origin)},
                {'city_id': 2, 'name': '洛阳', 'type': 'city', 'owner_raw': 2, 'world_xy_raw': list(dest)},
            ],
            'field_units': [{
                'unit_id': 3, 'unit_kind': '步兵', 'owner_raw': 2, 'size_index': 0,
                'world_xy_raw': list(enemy),
            }],
            'generals': [],
        })
        dest_row = state['entities']['cities_and_barriers'][1]
        self.assertIn(origin, vision_cells(enemy, 2))
        with patch('unit_move.road_cells', return_value=set()):
            plan = plan_stealth_raid(state, origin, dest_row)
        self.assertFalse(plan['ok'])
        self.assertIn('视野', plan['error'])

    def test_skips_watched_nearest_city(self):
        path = walk((36, 36), 30)
        dest = path[-1]
        near = path[12]
        far = path[0]
        enemy = tile_neighbors(*near)[0]
        state = confirmed({
            'lords': [
                {'force_id': 1, 'name': '鲁', 'capital_city_id': 1},
                {'force_id': 2, 'name': '汉', 'capital_city_id': 2},
            ],
            'cities_and_barriers': [
                {'city_id': 1, 'name': '曲阜', 'type': 'city', 'owner_raw': 1, 'world_xy_raw': list(far)},
                {'city_id': 3, 'name': '琅邪', 'type': 'city', 'owner_raw': 1, 'world_xy_raw': list(near)},
                {'city_id': 2, 'name': '洛阳', 'type': 'city', 'owner_raw': 2, 'world_xy_raw': list(dest)},
            ],
            'field_units': [{
                'unit_id': 9, 'unit_kind': '步兵', 'owner_raw': 2, 'size_index': 0,
                'world_xy_raw': list(enemy),
            }],
            'generals': [],
        })
        dest_row = state['entities']['cities_and_barriers'][2]
        self.assertTrue(origin_watched(state, near, {2}))
        self.assertFalse(origin_watched(state, far, {2}))
        with patch('unit_move.road_cells', return_value=set()):
            origin, plan = choose_origin_city(state, dest_row)
            board = raid_board(state)
            targets = raid_targets(state)
        self.assertEqual(origin, far, plan.get('origin_reason'))
        self.assertTrue(plan.get('ok'), plan.get('error'))
        self.assertIn('周边有敌', plan.get('origin_reason') or '')
        self.assertEqual(board[0]['force_name'], '汉')
        self.assertTrue(board[0]['ok'])
        self.assertEqual(board[0]['origin_name'], '曲阜')
        self.assertEqual(targets[0]['force_name'], '汉')
        self.assertIsNone(targets[0]['plan'])

    def test_raid_plans_payload_is_compact_and_ranked(self):
        state, origin, dest, _ = self._raid_state()
        with patch('unit_move.road_cells', return_value=set()):
            payload = raid_plans_payload(state, limit=3)
        self.assertTrue(payload['player_confirmed'])
        self.assertEqual(payload['player_force_id'], 1)
        self.assertTrue(payload['recommended']['ok'])
        self.assertEqual(payload['recommended']['origin_name'], '曲阜')
        self.assertEqual(payload['recommended']['dest_name'], '洛阳')
        self.assertEqual(payload['recommended']['origin_xy'], list(origin))
        self.assertEqual(payload['recommended']['dest_xy'], list(dest))
        self.assertNotIn('full_path', payload['recommended'])
        self.assertLessEqual(len(payload['plans']), 3)
        ctx = dict(state)
        ctx.pop('player_identity')
        ctx.pop('player_force_id')
        ctx['player_context'] = {'status': 'verified', 'force_id': 1}
        with patch('unit_move.road_cells', return_value=set()):
            again = raid_plans_payload(ctx, dest_force_id=2, limit=3)
        self.assertTrue(again['recommended']['ok'])
        self.assertEqual(again['recommended']['dest_force_id'], 2)

    def test_live_update_does_not_recompute_raid(self):
        pan = (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8')
        block = pan.split('def update_state', 1)[1].split('def _command_text', 1)[0]
        self.assertNotIn('_compute_raid', block)

    def test_city_ring_leaves_the_city_tile(self):
        state, origin, _, _ = self._raid_state()
        city = state['entities']['cities_and_barriers'][0]
        ring = city_ring_cell(state, city)
        self.assertIsNotNone(ring)
        self.assertNotEqual(ring, origin)
        self.assertIn(ring, tile_neighbors(*origin))
        cells = city_ring_cells(state, city)
        self.assertGreaterEqual(len(cells), 1)
        self.assertLessEqual(len(cells), 4)
        self.assertNotIn(origin, cells)

    def test_sim_unit_uses_game_move_tiles_and_sprite_kind(self):
        state, origin, _, _ = self._raid_state()
        city = state['entities']['cities_and_barriers'][0]
        ring = city_ring_cells(state, city)
        cell = ring[0]
        row = sim_unit(state, cell, '骑兵')
        self.assertEqual(row['unit_kind'], '重装骑兵')
        self.assertEqual(SPRITE_KIND['步兵'], '重装步兵')
        self.assertEqual(SPRITE_KIND['弓兵'], '重装弓兵')
        self.assertEqual(row['move_klass'], 'cavalry_horse')
        self.assertEqual(row['world_xy_raw'], [cell[0], cell[1]])
        wagon = sim_unit(state, cell, '粮草兵')
        self.assertEqual(wagon['unit_kind'], '运输兵')
        self.assertEqual(wagon['move_klass'], 'wagon')
        reach = raid_reach_cells(state, cell, '骑兵')
        overlay = raid_move_overlay(state, cell, '骑兵')
        self.assertGreater(len(reach), 4)
        self.assertTrue(overlay)
        self.assertNotIn(cell, [item['cell'] for item in overlay])

    def test_raid_targets_does_not_pathfind(self):
        state, _, _, _ = self._raid_state()
        with patch('stealth_raid.plan_stealth_raid') as planned:
            rows = raid_targets(state)
        planned.assert_not_called()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['ok'])

    def test_hub_has_raid_tab_not_panorama_button(self):
        pan = (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8')
        omni = (ROOT / 'app/omni_window.py').read_text(encoding='utf-8')
        page = (ROOT / 'app/stealth_raid_page.py').read_text(encoding='utf-8')
        self.assertIn("mode == 'raid'", pan)
        self.assertIn('def show_raid', pan)
        self.assertIn('if self.slim or getattr(self, \'view_units\', None) is None', pan)
        self.assertIn('展开对手状态', pan)
        self.assertIn('def _place_side_sash', pan)
        self.assertIn('if self.slim:\n            return', pan)
        self.assertIn('折叠状态栏', page)
        self.assertIn('展开状态栏', page)
        self.assertIn('def toggle_side', page)
        self.assertIn("tk.Frame(self, bg=WELL, width=300)", page)
        self.assertNotIn("text='对手状态'", page)
        self.assertIn("mode='raid'", page)
        self.assertNotIn("layer = 'lbm' if self.slim", pan)
        self.assertNotIn('结束回合', page)
        self.assertNotIn('目标君主', page)
        self.assertNotIn('tk.Listbox', page)
        self.assertNotIn('plan_stealth_raid', page)
        self.assertNotIn('threading', page)
        self.assertNotIn('算路中', page)
        self.assertIn('city_ring_cells', page)
        self.assertIn('raid_move_overlay', page)
        self.assertIn('raid_reach_cells', page)
        self.assertNotIn('walk_ring_cells', page)
        self.assertIn('_raid_overlay_items', pan)
        self.assertIn('sprites.image', pan)
        self.assertNotIn("text='本回'", pan)
        self.assertIn('_turn_count', page)
        self.assertIn('快捷模式', page)
        self.assertIn('每格一回', page)
        self.assertIn('KIND_CHOICES', page)
        self.assertIn("'粮草兵'", (ROOT / 'app/stealth_raid.py').read_text(encoding='utf-8'))
        self.assertNotIn("text='偷袭主城', command=self.toggle_raid", pan)
        self.assertIn("text='偷袭主城'", omni)
        self.assertIn('StealthRaidPage', omni)
        self.assertNotIn('陷阱（只读）', omni)
        self.assertNotIn('raid_board(', page)
        self.assertNotIn('raid_targets', page)
        self.assertNotIn('_pick_lord', page)
        self.assertIn('same_player', page)
        self.assertIn('已锁定', page)
        self.assertIn("'ring'", pan)
        self.assertIn('shared_terrain(warmup=True)', pan)
        self.assertIn("lambda _=None: self.request_draw()", pan)
        self.assertIn('MIN_ZOOM if self.slim else 6.0', pan)
        self.assertIn('raid.center = self.panorama.center', omni)
        self.assertIn("getattr(page, 'frozen', None)", omni)
        self.assertIn('raid.unfreeze()', omni)
        self.assertIn('on_pick_cell', pan)
        self.assertIn('on_pick_unit', pan)
        self.assertIn('def _from_map_unit', page)
        self.assertIn('_move_selected', page)
        self.assertIn('unit_reach_cells', page)
        self.assertIn('重装骑兵', (ROOT / 'app/stealth_raid.py').read_text(encoding='utf-8'))
        self.assertIn('stealth-raid-move-existing', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('stealth-raid-tier3-sprite', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('stealth-raid-quick-walk', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('locator-hide-when-idle', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('locator-stay-in-hub', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('def _raid_click', pan)
        self.assertIn('city_ring_cell', page)
        self.assertIn('_from_map_cell', page)
        self.assertIn('已锁本帧', page)
        self.assertIn('跟随实时', page)
        self.assertIn('copy.deepcopy', page)
        self.assertIn('def follow_live', page)
        self.assertIn('def unfreeze', page)
        self.assertIn('_CACHE', (ROOT / 'app/original_sprites.py').read_text(encoding='utf-8'))
        self.assertIn('if not self.slim:\n            self.after(80, self.draw)', pan)
        self.assertIn('def shared_terrain', (ROOT / 'app/tactical_terrain.py').read_text(encoding='utf-8'))
        self.assertIn('stealth-raid-open-fast', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('stealth-raid-freeze-live', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('stealth-raid-game-tiles', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('capital_marks', page)
        self.assertIn('_fill_capitals', page)
        self.assertIn('各势力主城', page)
        self.assertIn('stealth-raid-other-capitals', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('stealth-raid-capital-rings', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('panorama-side-sash-fix', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('raid-fold-status', (ROOT / 'RELEASE.json').read_text(encoding='utf-8'))
        self.assertIn('self._rgb(mark.get(\'force_id\'))', pan)
        self.assertIn('create_oval', pan.split('def _draw_capitals', 1)[1].split('def _draw_objects', 1)[0])
        self.assertNotIn('#c32620', (ROOT / 'app/stealth_raid.py').read_text(encoding='utf-8'))


class FakeRaidMap(tk.Frame):
    def __init__(self, parent, title='偷袭主城', mode='raid'):
        super().__init__(parent)
        self.state = None
        self.terrain = None
        self.center = (50, 50)
        self.zoom = 1
        self.on_pick_origin = None
        self.on_pick_cell = None
        self.on_pick_unit = None
        self.canvas = tk.Canvas(self)

    def update_state(self, state, lists=False, immediate=False, refresh_view=False):
        self.state = state

    def show_raid(self, plan, sim_cell=None, immediate=False):
        self.raid_plan = plan

    def draw(self):
        return None

    def request_draw(self):
        return None


class StealthRaidFreezeTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.SimpleNamespace = SimpleNamespace
        self.root = tk.Tk()
        self.root.withdraw()
        self._map_patch = patch('stealth_raid_page.PanoramaMap', FakeRaidMap)
        self._map_patch.start()

    def tearDown(self):
        self._map_patch.stop()
        self.root.destroy()

    def _state(self, snap, city2_owner=2):
        state, _, _, _ = StealthRaidTests()._raid_state()
        state['snapshot_id'] = snap
        state['capture_end'] = '2026-09-20T00:00:00+00:00'
        state['clock_candidates'] = {'year_u16': 189, 'season_u16': 1}
        state['phase_candidate'] = {'year_u16': 189, 'season_u16': 1}
        state['entities']['cities_and_barriers'][1]['owner_raw'] = city2_owner
        return state

    def _page(self, app=None, doc=None):
        from stealth_raid_page import StealthRaidPage
        if app is None:
            app = self.SimpleNamespace(review=None, doc=doc, face=None)
        return StealthRaidPage(self.root, app)

    def test_refresh_follows_new_snapshot_before_action(self):
        page = self._page()
        first = self._state('s1')
        second = self._state('s2', city2_owner=1)
        page.refresh(first)
        self.assertEqual(page.map.state['snapshot_id'], 's1')
        self.assertIsNone(page.frozen)
        page.refresh(second)
        self.assertEqual(page.map.state['snapshot_id'], 's2')
        self.assertEqual(page.map.state['entities']['cities_and_barriers'][1]['owner_raw'], 1)

    def test_city_click_freezes_and_ignores_later_snapshot(self):
        first = self._state('s1')
        later = self._state('s2', city2_owner=1)
        page = self._page(doc=first)
        page.refresh(first)
        page._from_map_city(first['entities']['cities_and_barriers'][0])
        self.assertIsNotNone(page.frozen)
        self.assertIn('已锁本帧', page.freeze_text.get())
        self.assertEqual(page.follow_btn.winfo_manager(), 'pack')
        page.refresh(later)
        self.assertEqual(page.map.state['snapshot_id'], 's1')
        self.assertEqual(page.map.state['entities']['cities_and_barriers'][1]['owner_raw'], 2)
        self.assertIs(page.map.state, page.frozen)

    def test_place_troop_also_freezes(self):
        first = self._state('s1')
        later = self._state('s2', city2_owner=1)
        page = self._page(doc=first)
        page.refresh(first)
        city = first['entities']['cities_and_barriers'][0]
        page.ring = city_ring_cells(first, city)
        landing = page.ring[0]
        page._from_map_cell(landing)
        self.assertIsNotNone(page.frozen)
        self.assertEqual(page.unit_cell, landing)
        self.assertGreater(len(page.ring), 4)
        page.refresh(later)
        self.assertEqual(page.map.state['snapshot_id'], 's1')
        self.assertEqual(page.map.state['entities']['cities_and_barriers'][1]['owner_raw'], 2)

    def test_live_unit_click_moves_sprite_cell(self):
        first = self._state('s1')
        own = {
            'unit_id': 21, 'unit_kind': '强化步兵', 'owner_raw': 1, 'size_index': 0,
            'world_xy_raw': [42, 42],
        }
        first['entities']['field_units'].append(own)
        page = self._page(doc=first)
        page.refresh(first)
        page._from_map_unit(own)
        self.assertIsNotNone(page.frozen)
        self.assertEqual(page.control, 'live')
        self.assertTrue(page.ring)
        dest = page.ring[0]
        page._from_map_cell(dest)
        moved = field_unit_at(page.map.state, own)
        self.assertEqual(tuple(moved['world_xy_raw']), dest)
        self.assertEqual(page.control, 'live')
        self.assertNotEqual(dest, (42, 42))
        overlay = unit_move_overlay(page.map.state, moved)
        self.assertTrue(overlay)
        first_dest = dest
        page.ring = unit_reach_cells(page.map.state, moved)
        second = next(cell for cell in page.ring if cell != first_dest)
        page._from_map_cell(second)
        self.assertEqual(page._turn_count(), 2)
        self.assertIn('已走 2 回', page.place_text.get())

    def test_reset_does_not_unfreeze(self):
        first = self._state('s1')
        later = self._state('s2', city2_owner=1)
        page = self._page(doc=first)
        page.refresh(first)
        page._from_map_city(first['entities']['cities_and_barriers'][0])
        page._from_map_cell(page.ring[0])
        self.assertIsNotNone(page.unit_cell)
        page._reset()
        self.assertIsNone(page.unit_cell)
        self.assertEqual(page.log, [])
        self.assertIsNotNone(page.frozen)
        page.refresh(later)
        self.assertEqual(page.map.state['snapshot_id'], 's1')

    def test_follow_live_then_tracks_new_snapshot(self):
        first = self._state('s1')
        second = self._state('s2', city2_owner=1)
        third = self._state('s3', city2_owner=0)
        app = self.SimpleNamespace(review=None, doc=first, face=None)
        page = self._page(app)
        page.refresh(first)
        page._from_map_city(first['entities']['cities_and_barriers'][0])
        app.doc = second
        page.follow_live()
        self.assertIsNone(page.frozen)
        self.assertEqual(page.map.state['snapshot_id'], 's2')
        self.assertEqual(page.follow_btn.winfo_manager(), '')
        page.refresh(third)
        self.assertEqual(page.map.state['snapshot_id'], 's3')
        self.assertEqual(page.map.state['entities']['cities_and_barriers'][1]['owner_raw'], 0)

    def test_archive_review_is_not_overwritten_by_live(self):
        archive = self._state('arch')
        live = self._state('live', city2_owner=1)
        app = self.SimpleNamespace(review={'state': archive}, doc=archive, face=None)
        page = self._page(app)
        page.refresh(archive)
        self.assertEqual(page.map.state['snapshot_id'], 'arch')
        page._from_map_city(archive['entities']['cities_and_barriers'][0])
        self.assertIsNone(page.frozen)
        self.assertEqual(page.follow_btn.winfo_manager(), '')
        self.assertEqual(page.freeze_text.get(), '')
        page.refresh(live)
        self.assertEqual(page.map.state['snapshot_id'], 'arch')
        self.assertEqual(page.map.state['entities']['cities_and_barriers'][1]['owner_raw'], 2)

    def test_other_capital_jump_does_not_freeze(self):
        first = self._state('s1')
        page = self._page(doc=first)
        page.refresh(first)
        enemy = next(mark for mark in capital_marks(first) if mark.get('city_id') == 2)
        jump = getattr(page, '_jump_capital', None) or getattr(page, '_pick_capital', None)
        self.assertIsNotNone(jump)
        jump(enemy)
        x, y = enemy['world_xy']
        self.assertAlmostEqual(page.map.center[0], x + 0.5)
        self.assertAlmostEqual(page.map.center[1], y + 0.5)
        self.assertIsNone(page.frozen)
        self.assertIsNone(page.unit_cell)


if __name__ == '__main__':
    unittest.main()
