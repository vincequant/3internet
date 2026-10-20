"""戰場／外部指令地圖相機的單元測試（純函式，不需要 Tk 視窗）。

2026-10-20：底圖換成「全知情報」的全景大地圖（app/assets/SanInet.mbm，
9744×4872、48×24 交錯菱格），並修好「放大縮小都會出問題」。
舊版的三個致命問題：
  1. zoom<=1 走 contain、zoom>1 走「切畫布比例」分支 → 1.0→1.2 倍率跳 2.15 倍
     （地圖被拉走）。
  2. 相機中心被夾在底圖中央（zoom<2.6 時）→ WASD 平移完全沒反應。
  3. 城池用 x/WORLD_X 線性投影，但地形是交錯菱格 → 方塊跟地形差一格。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'bridge'))
from native_window import (FengyeWindow, MAP_MAX_ZOOM, MAP_MIN_ZOOM, WORLD,
                           map_camera, map_fit_scale, map_project, map_size,
                           map_terrain, map_unproject, map_zoom, wheel_steps)

# 原作地面 app/assets/SanInet.mbm
IW, IH = 9744, 4872
W, H = 1164, 362            # 戰場頁 canvas（寬畫布，寬高比 3.2 ≠ 地圖 2.0）
WORLD_X, WORLD_Y = float(WORLD[0]), float(WORLD[1])


def world_pixel(x, y):
    """跟 app/tactical_terrain.world_pixel 一致（測試不依賴 PIL）。"""
    return 48 + 96 * x + 48 * (y % 2), 24 + 24 * y


class FakeCanvas:
    """不需要真的 Tk 視窗：只記錄畫了什麼。"""

    def __init__(self, width=W, height=H):
        self._width = width
        self._height = height
        self.items = []

    def winfo_width(self):
        return self._width

    def winfo_height(self):
        return self._height

    def delete(self, *_a):
        self.items = []

    def create_image(self, x, y, **kw):
        self.items.append(('image', x, y))
        return len(self.items)

    def create_text(self, x, y, **kw):
        self.items.append(('text', x, y, kw.get('text', '')))
        return len(self.items)

    def create_rectangle(self, *a, **kw):
        self.items.append(('rect',) + a)
        return len(self.items)

    def create_oval(self, *a, **kw):
        self.items.append(('oval',) + a)
        return len(self.items)

    def find_all(self):
        return list(range(len(self.items)))


class FakePhoto:
    def __init__(self, width, height):
        self._w = width
        self._h = height

    def width(self):
        return self._w

    def height(self):
        return self._h


class FakeFont:
    """量字用的假字型：固定字寬，讓重疊判斷可以預期。"""

    def __init__(self, size=9):
        self.size = size

    def measure(self, text):
        return 9 * len(text)

    def metrics(self, _what):
        return 12


def make_stub(width=W, height=H):
    """把戰場頁的地圖相關方法掛到一個假物件上（不開 Tk）。"""
    stub = type('Stub', (), {})()
    stub.battle_map = FakeCanvas(width, height)
    stub.battle_zoom = 1.0
    stub.battle_cx = None
    stub.battle_cy = None
    stub.battle_last = None
    stub._battle_photos = {}
    stub._battle_photo = None
    stub._battle_photo_key = None
    stub._canvas_sizes = {}
    stub._map_fonts = {k: FakeFont(k[0]) for k in ((9, True), (9, False))}
    stub.face = 'Helvetica'
    for name in ('_canvas_size', '_battle_geometry', '_battle_draw_map', '_battle_paint_map',
                 '_battle_set_zoom', '_battle_pan', '_battle_reset_view', '_battle_redraw',
                 '_battle_wheel', '_battle_drag_start', '_battle_drag_move',
                 '_battle_drag_end',
                 '_map_font', '_map_label_fits', '_map_label', '_map_hint'):
        setattr(stub, name, getattr(FengyeWindow, name).__get__(stub))

    def fake_view(w, h):
        """真的幾何、假的 PhotoImage（headless 沒有 Tk 圖形）。"""
        geo = FengyeWindow._battle_geometry(stub, w, h)
        if geo is None:
            return None
        key, pos, project, cam, crop = geo
        return FakePhoto(crop[4], crop[5]), pos, project, cam

    stub._battle_view = fake_view
    return stub


class MapCameraTests(unittest.TestCase):
    def test_zoom_one_shows_whole_map_uniformly_and_centered(self):
        cam = map_camera(IW, IH, W, H, 1.0)
        left, top, right, bottom = cam['box']
        self.assertAlmostEqual(right - left, IW, places=6)
        self.assertAlmostEqual(bottom - top, IH, places=6)
        # 等比：圖塊長寬比 == 底圖長寬比
        dw, dh = cam['draw'][2], cam['draw'][3]
        self.assertAlmostEqual(dw / dh, IW / IH, places=6)
        # 置中
        self.assertAlmostEqual(cam['draw'][0], (W - dw) / 2.0, places=6)
        self.assertAlmostEqual(cam['draw'][1], (H - dh) / 2.0, places=6)

    def test_zoom_steps_are_continuous_in_both_directions(self):
        """1.0 → 1.0002 不准跳版（舊版在 525×350 底圖上會跳 2.15 倍）。"""
        base = map_camera(IW, IH, W, H, 1.0)['scale']
        near = map_camera(IW, IH, W, H, 1.0002)['scale']
        self.assertLess(abs(near / base - 1.0), 0.001)
        zoom = 1.0
        prev = map_camera(IW, IH, W, H, zoom)['scale']
        for _ in range(8):
            zoom *= 1.2
            scale = map_camera(IW, IH, W, H, zoom)['scale']
            self.assertAlmostEqual(scale / prev, 1.2, places=6)
            prev = scale
        for _ in range(8):
            zoom /= 1.2
            scale = map_camera(IW, IH, W, H, zoom)['scale']
            self.assertAlmostEqual(scale / prev, 1 / 1.2, places=6)
            prev = scale

    def test_map_never_stretches_at_any_zoom(self):
        """圖塊像素密度 == scale，且圖塊長寬比 == 可見範圍長寬比。"""
        for zoom in (1.0, 1.2, 1.5, 2.0, 2.5, 5.0, 10.0):
            cam = map_camera(IW, IH, W, H, zoom)
            left, top, right, bottom = cam['box']
            vw, vh = right - left, bottom - top
            dw, dh = cam['draw'][2], cam['draw'][3]
            self.assertGreater(vw, 0.0)
            self.assertGreater(vh, 0.0)
            self.assertAlmostEqual(dw / dh, vw / vh, places=9)
            self.assertAlmostEqual(dw / vw, cam['scale'], places=9)
            self.assertAlmostEqual(dh / vh, cam['scale'], places=9)

    def test_visible_region_is_canvas_divided_by_scale(self):
        for zoom in (1.0, 2.0, 2.5, 5.0):
            cam = map_camera(IW, IH, W, H, zoom)
            self.assertAlmostEqual(cam['view'][0], W / cam['scale'], places=6)
            self.assertAlmostEqual(cam['view'][1], H / cam['scale'], places=6)

    def test_camera_is_clamped_inside_the_map(self):
        """平移到邊界外要被夾回來，可見範圍永遠不會超出底圖。"""
        for zoom in (1.0, 1.2, 2.0, 2.5, 5.0, 10.0):
            for want in ((-500, -500), (50000, 50000), (IW, IH), (0, 0)):
                cam = map_camera(IW, IH, W, H, zoom, want[0], want[1])
                left, top, right, bottom = cam['box']
                self.assertGreaterEqual(left, -1e-6)
                self.assertGreaterEqual(top, -1e-6)
                self.assertLessEqual(right, IW + 1e-6)
                self.assertLessEqual(bottom, IH + 1e-6)
                self.assertGreaterEqual(cam['cx'], 0.0)
                self.assertLessEqual(cam['cx'], IW)
                self.assertGreaterEqual(cam['cy'], 0.0)
                self.assertLessEqual(cam['cy'], IH)

    def test_pan_is_possible_once_the_map_is_cropped(self):
        """舊版 zoom<2.6 時相機被夾死在中央 → WASD 沒反應。"""
        moved = False
        for zoom in (2.0, 2.5, 3.0, 5.0):
            step_x = 0.10 * map_camera(IW, IH, W, H, zoom)['view'][0]
            cx = IW / 2.0
            for _ in range(3):
                cx = min(max(cx + step_x, 0.0), float(IW))
                cam = map_camera(IW, IH, W, H, zoom, cx, None)
                if abs(cam['cx'] - IW / 2.0) > 0.5:
                    moved = True
        self.assertTrue(moved, '放大後相機還是動不了')

    def test_zoom_round_trip_returns_to_the_same_view(self):
        """版面要能固定：1x → 2.5x → 1x → 2.5x 畫面必須一樣。"""
        def snap(zoom, cx=None, cy=None):
            cam = map_camera(IW, IH, W, H, zoom, cx, cy)
            return (round(cam['scale'], 6), round(cam['cx'], 4), round(cam['cy'], 4),
                    tuple(round(v, 4) for v in cam['box']),
                    tuple(round(v, 4) for v in cam['draw']))

        first = snap(1.0)
        zoomed = snap(2.5)
        self.assertEqual(snap(1.0), first)
        self.assertEqual(snap(2.5), zoomed)

    def test_projection_follows_the_drawn_map(self):
        """城池方塊與名稱必須跟著圖塊走（不能自己漂）。"""
        for zoom in (1.0, 1.2, 2.0, 2.5, 5.0):
            cam = map_camera(IW, IH, W, H, zoom)
            left, top, right, bottom = cam['box']
            for world in ((0, 0), (WORLD_X / 2, WORLD_Y / 2), (WORLD_X - 1, WORLD_Y - 1)):
                px, py = map_project(world, cam, W, H)
                sx, sy = world_pixel(world[0], world[1])
                expect_x = cam['draw'][0] + (sx - left) * cam['scale']
                expect_y = cam['draw'][1] + (sy - top) * cam['scale']
                self.assertAlmostEqual(px, expect_x, places=6)
                self.assertAlmostEqual(py, expect_y, places=6)

    def test_projection_uses_the_staggered_grid(self):
        """原作地面是 48×24 交錯菱格：奇數列要右移 48 px，線性投影會偏一格。"""
        cam = map_camera(IW, IH, W, H, 1.0)
        even = map_project((10, 4), cam, W, H)
        odd = map_project((10, 5), cam, W, H)
        self.assertAlmostEqual(odd[0] - even[0], 48 * cam['scale'], places=6)
        self.assertAlmostEqual(odd[1] - even[1], 24 * cam['scale'], places=6)
        # 舊版線性投影（x / WORLD_X * 底圖寬）給不出這個 48 px 的列位移
        linear = cam['draw'][0] + (10 / WORLD_X * IW - cam['box'][0]) * cam['scale']
        self.assertGreater(abs(even[0] - linear), 1.0)

    def test_projection_moves_with_the_camera(self):
        """平移後同一座城池的畫布座標要跟著移動（方向正確）。"""
        zoom = 3.0
        base = map_camera(IW, IH, W, H, zoom, IW / 2.0, IH / 2.0)
        moved = map_camera(IW, IH, W, H, zoom, IW / 2.0 + 40, IH / 2.0)
        city = (WORLD_X / 2, WORLD_Y / 2)
        x0, y0 = map_project(city, base, W, H)
        x1, y1 = map_project(city, moved, W, H)
        self.assertLess(x1, x0)          # 相機往右 → 城池在畫布上往左
        self.assertAlmostEqual(y0, y1, places=6)
        self.assertAlmostEqual(x0 - x1, 40 * base['scale'], places=6)

    def test_unproject_round_trips(self):
        """畫布座標 → 底圖像素 → 畫布座標（點擊選城池用）。"""
        cam = map_camera(IW, IH, W, H, 4.0, 3000, 2000)
        for point in ((10, 10), (W - 10, H - 10), (W / 2, H / 2)):
            mx, my = map_unproject(point[0], point[1], cam, W, H)
            bx = W / 2.0 + (mx - cam['cx']) * cam['scale']
            by = H / 2.0 + (my - cam['cy']) * cam['scale']
            self.assertAlmostEqual(bx, point[0], places=6)
            self.assertAlmostEqual(by, point[1], places=6)

    def test_fit_scale_is_contain(self):
        self.assertAlmostEqual(map_fit_scale(IW, IH, 1164, 362), 362 / 4872.0, places=9)
        self.assertAlmostEqual(map_fit_scale(IW, IH, 1000, 2000), 1000 / 9744.0, places=9)

    def test_camera_is_pure(self):
        """相機計算是純函式：不會偷偷改傳進去的狀態。"""
        cam = map_camera(IW, IH, W, H, 2.5, 100, 100)
        self.assertAlmostEqual(cam['want_cx'], 100.0)
        self.assertAlmostEqual(cam['want_cy'], 100.0)
        again = map_camera(IW, IH, W, H, 2.5, 100, 100)
        self.assertEqual(cam, again)

    def test_zoom_is_clamped_to_the_documented_range(self):
        self.assertEqual(map_zoom(0.2), MAP_MIN_ZOOM)
        self.assertEqual(map_zoom(99), MAP_MAX_ZOOM)
        self.assertEqual(map_zoom('x'), MAP_MIN_ZOOM)
        self.assertEqual(map_zoom(2.5), 2.5)


class WheelTests(unittest.TestCase):
    """滾輪：一個手勢不能連跳十幾格（舊版只看正負號）。"""

    def test_one_wheel_notch_is_one_step(self):
        self.assertEqual(wheel_steps(120), 1.0)
        self.assertEqual(wheel_steps(-120), -1.0)

    def test_large_delta_is_capped(self):
        self.assertEqual(wheel_steps(600), 3.0)
        self.assertEqual(wheel_steps(-600), -3.0)

    def test_small_trackpad_delta_is_fractional(self):
        self.assertAlmostEqual(wheel_steps(0.5), 0.5)
        self.assertAlmostEqual(wheel_steps(-0.25), -0.25)

    def test_zero_delta_does_nothing(self):
        self.assertEqual(wheel_steps(0), 0.0)
        self.assertEqual(wheel_steps(None), 0.0)

    def test_gesture_of_many_events_does_not_slam_to_max(self):
        """40 個小事件（觸控板一下）= 最多 40 步以內，而且每步都小。"""
        zoom = 1.0
        for _ in range(40):
            zoom = map_zoom(zoom * 1.2 ** wheel_steps(0.05))
        self.assertLess(zoom, 2.0)


class TerrainSourceTests(unittest.TestCase):
    def test_base_map_is_the_panorama_terrain(self):
        """底圖必須是全知情報的全景大地圖（9744×4872），不是 525×350 的示意圖。"""
        terrain = map_terrain()
        if terrain is None:
            self.skipTest('缺少 app/assets/SanInet.mbm')
        self.assertEqual(map_size(), (9744, 4872))
        self.assertEqual(terrain.size, map_size())


class BattleMapHandlerTests(unittest.TestCase):
    """戰場頁互動（滾輪縮放／WASD 平移／復原）——不需要 Tk 視窗。"""

    def setUp(self):
        if map_terrain() is None:
            self.skipTest('缺少 app/assets/SanInet.mbm')
        self.stub = make_stub()

    def test_zoom_keeps_the_camera_center_so_the_map_does_not_drift(self):
        stub = self.stub
        stub.battle_zoom = 2.0
        stub.battle_cx = 3000.0
        stub.battle_cy = 1500.0
        stub._battle_set_zoom(1.2)
        self.assertAlmostEqual(stub.battle_zoom, 2.4, places=6)
        self.assertAlmostEqual(stub.battle_cx, 3000.0, places=6)
        self.assertAlmostEqual(stub.battle_cy, 1500.0, places=6)

    def test_zoom_anchors_on_the_pointer(self):
        """游標底下那一點縮放後要留在原處（不然使用者看到「一滾就往下移」）。"""
        stub = self.stub
        stub.battle_zoom = 2.0
        stub.battle_cx = IW / 2.0
        stub.battle_cy = IH / 2.0
        ax, ay = 300.0, 80.0                       # 游標在畫布左上偏中
        before = map_camera(IW, IH, W, H, 2.0, stub.battle_cx, stub.battle_cy)
        world = map_unproject(ax, ay, before, W, H)
        stub._battle_set_zoom(1.2, anchor=(ax, ay))
        after = map_camera(IW, IH, W, H, stub.battle_zoom,
                           stub.battle_cx, stub.battle_cy)
        again = map_unproject(ax, ay, after, W, H)
        self.assertAlmostEqual(again[0], world[0], delta=1.0)
        self.assertAlmostEqual(again[1], world[1], delta=1.0)

    def test_zoom_anchor_is_clamped_at_the_map_edge(self):
        """在邊角縮放不能把相機推到地圖外。"""
        stub = self.stub
        stub.battle_zoom = 2.0
        stub.battle_cx = 60.0
        stub.battle_cy = 60.0
        stub._battle_set_zoom(1.2, anchor=(5.0, 5.0))
        self.assertGreaterEqual(stub.battle_cx, 0.0)
        self.assertGreaterEqual(stub.battle_cy, 0.0)
        self.assertLessEqual(stub.battle_cx, IW)
        self.assertLessEqual(stub.battle_cy, IH)

    def test_zoom_is_clamped_between_1_and_10(self):
        stub = self.stub
        stub._battle_set_zoom(1 / 1.2)
        self.assertEqual(stub.battle_zoom, MAP_MIN_ZOOM)
        stub.battle_zoom = 9.0
        stub._battle_set_zoom(1.2)
        self.assertEqual(stub.battle_zoom, MAP_MAX_ZOOM)
        stub._battle_set_zoom(0)
        self.assertEqual(stub.battle_zoom, MAP_MAX_ZOOM)

    def test_pan_moves_ten_percent_of_the_visible_range(self):
        stub = self.stub
        stub.battle_zoom = 3.0
        stub.battle_cx = IW / 2.0
        stub.battle_cy = IH / 2.0
        cam = map_camera(IW, IH, W, H, 3.0, stub.battle_cx, stub.battle_cy)
        stub._battle_pan(1, 0)
        self.assertAlmostEqual(stub.battle_cx, IW / 2.0 + 0.10 * cam['view'][0], places=6)
        stub._battle_pan(0, 1)
        self.assertAlmostEqual(stub.battle_cy, IH / 2.0 + 0.10 * cam['view'][1], places=6)

    def test_pan_never_leaves_the_map(self):
        stub = self.stub
        stub.battle_zoom = 3.0
        for _ in range(80):
            stub._battle_pan(1, 1)
        self.assertLessEqual(stub.battle_cx, IW)
        self.assertLessEqual(stub.battle_cy, IH)
        for _ in range(160):
            stub._battle_pan(-1, -1)
        self.assertGreaterEqual(stub.battle_cx, 0.0)
        self.assertGreaterEqual(stub.battle_cy, 0.0)

    def test_drawing_the_map_does_not_move_the_camera(self):
        """舊版 _battle_view 會把夾過的相機寫回去 → 畫一次版面就變一次。"""
        stub = self.stub
        stub.battle_zoom = 2.5
        stub.battle_cx = 2000.0
        stub.battle_cy = 1200.0
        stub._battle_draw_map([], [], {})
        self.assertAlmostEqual(stub.battle_cx, 2000.0, places=6)
        self.assertAlmostEqual(stub.battle_cy, 1200.0, places=6)

    def test_reset_view_returns_to_one_x_centered(self):
        stub = self.stub
        stub.battle_zoom = 4.0
        stub.battle_cx = 10.0
        stub.battle_cy = 10.0
        stub._battle_reset_view()
        self.assertEqual(stub.battle_zoom, MAP_MIN_ZOOM)
        self.assertAlmostEqual(stub.battle_cx, IW / 2.0, places=6)
        self.assertAlmostEqual(stub.battle_cy, IH / 2.0, places=6)

    def test_redraw_works_before_any_game_data(self):
        """沒有遊戲資料也要畫得出地圖（縮放測試不依賴遊戲）。"""
        stub = self.stub
        stub._battle_redraw()
        kinds = [item[0] for item in stub.battle_map.items]
        self.assertIn('image', kinds)

    def test_city_markers_follow_the_map(self):
        stub = self.stub
        stub.battle_zoom = 1.0
        cities = [{'xy': [0, 0], 'name': 'A', 'owner': 1},
                  {'xy': [WORLD_X - 1, WORLD_Y - 1], 'name': 'B', 'owner': 2}]
        stub._battle_draw_map(cities, [], {})
        rects = [item for item in stub.battle_map.items if item[0] == 'rect']
        # 提示底板很寬，城池方塊固定 8×8
        city_rects = [r for r in rects if len(r) == 5 and abs(r[3] - r[1] - 8) < 0.01]
        self.assertEqual(len(city_rects), 2)
        cam = map_camera(IW, IH, W, H, 1.0, stub.battle_cx, stub.battle_cy)
        first = map_project((0, 0), cam, W, H)
        self.assertAlmostEqual(city_rects[0][1] + 4, first[0], places=6)
        self.assertAlmostEqual(city_rects[0][2] + 4, first[1], places=6)

    def test_map_image_is_not_stretched_at_high_zoom(self):
        """畫在畫布上的圖塊長寬比 == 可見範圍長寬比（不變形）。"""
        stub = self.stub
        stub.battle_zoom = 2.5
        stub._battle_draw_map([], [], {})
        cam = map_camera(IW, IH, W, H, 2.5, stub.battle_cx, stub.battle_cy)
        left, top, right, bottom = cam['box']
        vw, vh = right - left, bottom - top
        dw, dh = cam['draw'][2], cam['draw'][3]
        self.assertAlmostEqual(dw / dh, vw / vh, places=9)

    def test_labels_do_not_pile_up(self):
        """1x 一次 92 座城：名稱重疊就跳過，不要糊成一團。"""
        stub = self.stub
        stub.battle_zoom = 1.0
        cities = [{'xy': [10 + (i % 3) * 0.05, 10], 'name': '城%d' % i, 'owner': 1}
                  for i in range(20)]
        stub._battle_draw_map(cities, [], {})
        labels = [item for item in stub.battle_map.items if item[0] == 'text']
        names = [t[3] for t in labels if t[3].startswith('城')]
        self.assertLess(len(names), len(cities), '重疊的名稱沒有被跳過')

    def test_every_city_keeps_its_marker_even_when_the_label_is_dropped(self):
        stub = self.stub
        stub.battle_zoom = 1.0
        cities = [{'xy': [10, 10], 'name': '同位置A', 'owner': 1},
                  {'xy': [10, 10], 'name': '同位置B', 'owner': 2}]
        stub._battle_draw_map(cities, [], {})
        rects = [r for r in stub.battle_map.items
                 if r[0] == 'rect' and len(r) == 5 and abs(r[3] - r[1] - 8) < 0.01]
        self.assertEqual(len(rects), 2)

    def test_hint_has_a_dark_plate(self):
        """左下角提示在淺色地形上要看得見（先鋪深色底）。"""
        stub = self.stub
        stub._battle_draw_map([], [], {})
        plates = [r for r in stub.battle_map.items if r[0] == 'rect']
        self.assertTrue(plates, '沒有提示底板')
        texts = [t for t in stub.battle_map.items if t[0] == 'text']
        self.assertTrue(any('滾輪' in (t[3] or '') for t in texts))


class FakeEvent:
    """假的 Tk 事件（只要 x / y / delta）。"""

    def __init__(self, x=0, y=0, delta=0):
        self.x = x
        self.y = y
        self.delta = delta


class AnchorRegressionTests(unittest.TestCase):
    """2026-10-20：「一滾就下移」的真正根因與修法。

    根因不是算式，是**相機夾邊界**：
      戰場畫布比底圖寬（1164×362 vs 9744×4872 → 3.2:1 vs 2:1），
      1x~1.7x 之間「可見寬度」大於底圖寬度，舊版在這種情況把水平相機
      **釘死在底圖中央** → 水平軸完全不吃游標錨點，游標底下的地圖會橫向
      跳走（實測一格滾輪最多跳 108 px）；垂直軸那時已經可以自由移動，
      兩邊行為不一致，使用者看到的就是「地圖歪掉、往下移」。

    修法：相機中心永遠落在底圖上（底圖比畫布小時可以滑動），
    游標錨點在每一格滾輪都成立。
    """

    def setUp(self):
        if map_terrain() is None:
            self.skipTest('缺少 app/assets/SanInet.mbm')
        self.stub = make_stub()

    def _world_under(self, stub, ax, ay):
        cam = map_camera(IW, IH, W, H, stub.battle_zoom, stub.battle_cx, stub.battle_cy)
        return map_unproject(ax, ay, cam, W, H)

    def _screen_of(self, stub, world):
        cam = map_camera(IW, IH, W, H, stub.battle_zoom, stub.battle_cx, stub.battle_cy)
        return (W / 2.0 + (world[0] - cam['cx']) * cam['scale'],
                H / 2.0 + (world[1] - cam['cy']) * cam['scale'])

    def test_one_notch_keeps_the_point_under_the_pointer(self):
        """第一格滾輪：游標底下的地圖不能橫向跳走（舊版最多跳 108 px）。"""
        for ax, ay in ((300, 80), (450, 120), (582, 40), (700, 200), (900, 120)):
            stub = make_stub()
            stub.battle_zoom = 1.0
            stub.battle_cx = None
            stub.battle_cy = None
            world = self._world_under(stub, ax, ay)
            stub._battle_set_zoom(1.2, anchor=(ax, ay))
            x, y = self._screen_of(stub, world)
            self.assertAlmostEqual(x, ax, delta=0.5)
            self.assertAlmostEqual(y, ay, delta=0.5)

    def test_two_notches_keep_the_pointer_point(self):
        """連滾兩格（1x → 1.44x）游標底下那一點還在原處。"""
        for ax, ay in ((300, 80), (582, 120), (900, 120)):
            stub = make_stub()
            stub.battle_zoom = 1.0
            stub.battle_cx = None
            stub.battle_cy = None
            world = self._world_under(stub, ax, ay)
            stub._battle_set_zoom(1.2, anchor=(ax, ay))
            stub._battle_set_zoom(1.2, anchor=(ax, ay))
            x, y = self._screen_of(stub, world)
            self.assertAlmostEqual(x, ax, delta=0.5)
            self.assertAlmostEqual(y, ay, delta=0.5)

    def test_camera_is_not_pinned_to_the_centre_when_the_map_is_smaller(self):
        """底圖比畫布小時，水平相機必須能動（舊版釘死中央）。"""
        cam = map_camera(IW, IH, W, H, 1.0, 4872.0, 2436.0)
        self.assertGreater(cam['view'][0], IW)      # 可見寬度 > 底圖寬度
        moved = map_camera(IW, IH, W, H, 1.0, 3000.0, 2436.0)
        self.assertNotAlmostEqual(moved['cx'], 4872.0, places=1)

    def test_exactly_fitting_axis_is_pinned_but_smaller_axis_may_slide(self):
        """1x：地圖高度剛好塞滿畫布 → 垂直釘住（不會露出一條綠邊）；
        寬度比畫布小 → 水平可以滑（游標錨點才成立）。"""
        cam = map_camera(IW, IH, W, H, 1.0, 4872.0, 2436.0)
        self.assertAlmostEqual(cam['view'][1], IH, places=6)     # 可見高度 == 底圖高度
        self.assertGreater(cam['view'][0], IW)                  # 可見寬度 > 底圖寬度
        vertical = map_camera(IW, IH, W, H, 1.0, 4872.0, 1000.0)
        self.assertAlmostEqual(vertical['cy'], 2436.0, places=6)
        horizontal = map_camera(IW, IH, W, H, 1.0, 3000.0, 2436.0)
        self.assertNotAlmostEqual(horizontal['cx'], 4872.0, places=1)

    def test_camera_center_always_stays_on_the_map(self):
        """相機中心永遠在底圖上：地圖不會整個滑出畫布。"""
        for zoom in (1.0, 1.2, 1.44, 1.728, 2.5, 5.0, 10.0):
            for want in ((-5000, -5000), (0, 0), (50000, 50000), (IW, IH)):
                cam = map_camera(IW, IH, W, H, zoom, want[0], want[1])
                self.assertGreaterEqual(cam['cx'], -1e-6)
                self.assertLessEqual(cam['cx'], IW + 1e-6)
                self.assertGreaterEqual(cam['cy'], -1e-6)
                self.assertLessEqual(cam['cy'], IH + 1e-6)

    def test_sliding_the_map_does_not_stretch_it(self):
        """底圖在畫布裡滑動時，等比關係不能壞掉。"""
        cam = map_camera(IW, IH, W, H, 1.0, 3000.0, 2436.0)
        left, top, right, bottom = cam['box']
        self.assertAlmostEqual((right - left) * cam['scale'], cam['draw'][2], places=6)
        self.assertAlmostEqual((bottom - top) * cam['scale'], cam['draw'][3], places=6)

    def test_zoom_stores_a_center_that_is_valid_for_the_new_zoom(self):
        """縮放後存回去的相機中心要已經是新倍率的合法值（否則下次縮放會跳版）。"""
        stub = self.stub
        stub.battle_zoom = 1.0
        stub.battle_cx = None
        stub.battle_cy = None
        stub._battle_set_zoom(1.2, anchor=(300.0, 80.0))
        cam = map_camera(IW, IH, W, H, stub.battle_zoom, stub.battle_cx, stub.battle_cy)
        self.assertAlmostEqual(cam['cx'], stub.battle_cx, places=6)
        self.assertAlmostEqual(cam['cy'], stub.battle_cy, places=6)
        self.assertGreaterEqual(stub.battle_cx, 0.0)
        self.assertLessEqual(stub.battle_cx, IW)
        self.assertGreaterEqual(stub.battle_cy, 0.0)
        self.assertLessEqual(stub.battle_cy, IH)

    def test_wheel_burst_is_throttled(self):
        """觸控板一個手勢會送十幾個事件，不能一口氣衝到上限。"""
        stub = self.stub
        stub.battle_zoom = 1.0
        stub._battle_wheel_at = 0.0
        for _ in range(20):
            stub._battle_wheel(FakeEvent(300, 80, 1))
        self.assertLess(stub.battle_zoom, 2.0)

    def test_wheel_uses_the_pointer_as_the_anchor(self):
        """滾輪事件要帶上游標座標（沒有座標就退化成置中縮放）。"""
        stub = self.stub
        stub.battle_zoom = 2.0
        stub.battle_cx = IW / 2.0
        stub.battle_cy = IH / 2.0
        stub._battle_wheel_at = 0.0
        stub._battle_wheel(FakeEvent(300, 80, 1))
        self.assertNotAlmostEqual(stub.battle_cx, IW / 2.0, places=1)

    def test_drag_moves_the_map_with_the_pointer(self):
        """拖曳：往右拖 → 地圖跟著往右走（相機中心往左移）。"""
        stub = self.stub
        stub.battle_zoom = 3.0
        stub.battle_cx = IW / 2.0
        stub.battle_cy = IH / 2.0
        before_x = stub.battle_cx
        stub._battle_drag_start(FakeEvent(300, 150))
        stub._battle_drag_move(FakeEvent(400, 150))
        self.assertLess(stub.battle_cx, before_x)
        stub._battle_drag_end(FakeEvent(400, 150))

    def test_drag_without_movement_does_not_move_the_map(self):
        stub = self.stub
        stub.battle_zoom = 3.0
        stub.battle_cx = IW / 2.0
        stub.battle_cy = IH / 2.0
        stub._battle_drag_start(FakeEvent(300, 150))
        stub._battle_drag_move(FakeEvent(301, 151))
        self.assertAlmostEqual(stub.battle_cx, IW / 2.0, places=6)

    def test_drag_never_leaves_the_map(self):
        stub = self.stub
        stub.battle_zoom = 3.0
        stub.battle_cx = IW / 2.0
        stub.battle_cy = IH / 2.0
        stub._battle_drag_start(FakeEvent(300, 150))
        for dx in range(-2000, 2000, 50):
            stub._battle_drag_move(FakeEvent(300 + dx, 150))
            self.assertGreaterEqual(stub.battle_cx, -1e-6)
            self.assertLessEqual(stub.battle_cx, IW + 1e-6)


if __name__ == '__main__':
    unittest.main()
