"""The complete native OmniWindow with an additional Fengye console."""
import json
import os
from pathlib import Path
import queue
import shlex
import subprocess
import sys
import time
import threading
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import ttk, messagebox

from omni_window import OmniWindow, DAMASK, PANEL, WELL, INK, GOLD, GOLD_HI, MUTED, WARN, BG
from fengye_source import (FengyeSource, control_ready, load_one_click_progress,
                           status_items, validate_control)
from room_client import RoomClient
from backend.room_protocol import nickname
from backend.lab_remote import lab_remote
from command_service import CommandService
from chat_force_colors import chat_parts, sender_factions
from fengye_capture_status import CaptureStatus
from fengye_diagnostics import report
from map_navigation import bind_pointer_wheel
from player_text import (plain_error, room_summary, room_result, room_fresh,
                         control_event, force_choices, force_summary, lab_result)

# A separate player-facing palette; the inherited world renderer is untouched.
LEGACY_COLORS = {DAMASK: '#f3f6fa', PANEL: '#16343d', WELL: '#ffffff',
                 INK: '#203440', GOLD: '#286a72', GOLD_HI: '#f3fafb',
                 MUTED: '#657985', WARN: '#a13b42', BG: '#e6eef2'}
DAMASK, PANEL, WELL = '#f3f6fa', '#16343d', '#ffffff'
INK, GOLD, GOLD_HI = '#203440', '#286a72', '#f3fafb'
MUTED, WARN, BG = '#657985', '#a13b42', '#e6eef2' 


# 2026-10-20 使用者要求：地圖要回歸遊戲本身的地圖（全知情報的全景大地圖），
# 而不是空白畫布或 525×350 的全國示意圖。底圖快取在下面的 _MAP。


def _map_debug(text):
    """地圖除錯：/tmp/hub-map-debug.log（每行帶時間，方便對事件順序）。"""
    try:
        stamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        with open('/tmp/hub-map-debug.log', 'a', encoding='utf-8') as fh:
            fh.write('%s %s\n' % (stamp, text))
    except OSError:
        pass


# ---------------------------------------------------------------- 地圖底圖
# 2026-10-20 使用者要求：底圖要用「全知情報」的全景大地圖（原作地面），
# 不是 525×350 的全國示意圖（SanInet.lbm）。
# 原作地面在 app/assets/SanInet.mbm：9744×4872、8-bit 索引色、
# 48×24 的交錯菱格（每格 1152 bytes、列上下翻轉）。解碼交給
# app/tactical_terrain.py（跟全景地圖、城周邊同一套、唯讀、共用 mip 快取）。
MAP_FILL = '#2b3527'          # 地圖外的留白（接近原作地面底色）
WORLD = (101, 202)            # 世界格數（x, y）
MAP_MIN_ZOOM = 1.0
MAP_MAX_ZOOM = 10.0
MAP_WHEEL_THROTTLE = 0.04   # 秒：觸控板一個手勢會送十幾個滾輪事件

try:                          # app/ 在 sys.path 上（run.py 與 tests 都會加）
    from tactical_terrain import shared_terrain as _shared_terrain
    from tactical_terrain import world_pixel as _world_pixel
except Exception:             # noqa: BLE001
    _shared_terrain = None
    _world_pixel = None

_MAP = {'terrain': None, 'tried': False, 'error': ''}


def map_terrain():
    """原作地面（唯讀，載入一次共用）。載不到回 None。"""
    if _MAP['tried']:
        return _MAP['terrain']
    _MAP['tried'] = True
    if _shared_terrain is None:
        _MAP['error'] = 'tactical_terrain 匯入失敗'
        _map_debug('terrain FAILED: %s' % _MAP['error'])
        return None
    try:
        started = time.monotonic()
        terrain = _shared_terrain(warmup=True)
        _MAP['terrain'] = terrain
        _map_debug('terrain SanInet.mbm %sx%s tiles=%sx%s load=%.3fs' % (
            terrain.size[0], terrain.size[1], terrain.tiles_x, terrain.tiles_y,
            time.monotonic() - started))
    except Exception as exc:  # noqa: BLE001
        _MAP['terrain'] = None
        _MAP['error'] = '%s: %s' % (type(exc).__name__, exc)
        _map_debug('terrain FAILED: %s' % _MAP['error'])
    return _MAP['terrain']


def map_size():
    terrain = map_terrain()
    return terrain.size if terrain else None


def map_error():
    return _MAP['error'] or '缺少 app/assets/SanInet.mbm'


def map_render(box, dw, dh):
    """裁一塊原作地面（box 是 mbm 像素）並縮到 (dw, dh)。"""
    terrain = map_terrain()
    if terrain is None:
        return None
    try:
        return terrain.crop_to(box, dw, dh)
    except Exception as exc:  # noqa: BLE001
        _map_debug('render failed box=%s %sx%s: %s: %s' % (
            box, dw, dh, type(exc).__name__, exc))
        return None


def map_world_center():
    """相機預設中心：原作地面的正中央（mbm 像素）。"""
    size = map_size()
    if not size:
        return (0.0, 0.0)
    return (size[0] / 2.0, size[1] / 2.0)


def map_fit_scale(iw, ih, width, height):
    """contain 倍率：整張底圖等比塞進畫布時的縮放倍率。"""
    if iw <= 0 or ih <= 0 or width <= 0 or height <= 0:
        return 1.0
    return min(width / float(iw), height / float(ih))


def map_clamp_axis(value, span, total):
    """相機中心 → 合法範圍（單一軸）。

    舊版有兩套規則（可見範圍塞得下就夾在底圖內、塞不下就釘死中央），
    這正是「一滾就下移」的根因：

      畫布比底圖寬（3.2:1 vs 2:1）→ 1x~1.7x 之間「可見寬度」大於底圖寬度，
      舊版把水平相機釘死在底圖中央 → **水平軸完全不吃游標錨點**，
      游標底下的內容會橫向跳走（實測一格滾輪最多跳 108 px）；
      而垂直軸那時已經可以自由移動，於是使用者看到的就是「地圖歪、往下移」。

    現在只有一條規則：相機中心永遠落在底圖上。
      * 可見範圍比較小（放大後）→ 相機夾在底圖裡，地圖不會滑出畫面。
      * 可見範圍比較大（1x 整張看得到）→ 相機夾在底圖範圍內，地圖可以在
        畫布裡左右滑動，游標錨點照樣成立。
    兩種情況相機中心都是連續函式，縮放時不會突然跳版。
    """
    half = max(0.0, float(span) / 2.0)
    total = float(total)
    if span >= total:
        if span - total <= 1e-6 * max(1.0, total):
            # 底圖剛好塞滿畫布（1x 的垂直軸）：沒有可滑的空間，釘在中央，
            # 否則按平移會露出一條綠邊（看起來像地圖壞掉）。
            lo = hi = total / 2.0
        else:
            # 底圖比畫布小：相機中心留在底圖上（底圖可在畫布裡滑動，錨點成立）
            lo, hi = 0.0, total
    else:
        lo, hi = half, total - half
    if lo > hi:
        lo = hi = (lo + hi) / 2.0
    return min(max(float(value), lo), hi)


def map_clamp_center(iw, ih, width, height, zoom, cx, cy):
    """把相機中心夾到該倍率下的合法範圍（回傳 (cx, cy)）。"""
    cam = map_camera(iw, ih, width, height, zoom, cx, cy)
    return cam['cx'], cam['cy']


def map_camera(iw, ih, width, height, zoom, cx=None, cy=None):
    """地圖相機（純函式，不改任何狀態）。

    規則（0.2.30 修正後的單一模型，戰場頁與指令頁共用）：
      * ``scale = contain 倍率 × zoom``：底圖永遠等比縮放 → 不會變形。
      * ``zoom=1``：整張底圖可見並置中（contain，兩側留邊）。
      * 畫布看到的底圖範圍 = 畫布範圍 ÷ scale（不再被畫布長寬比硬切），
        所以 1.0 → 1.2 → 1.44 … 倍率連續，不會突然跳版。
      * 相機中心用 map_clamp_axis 夾：可見範圍塞得下就夾在底圖內，
        塞不下就夾成「底圖完整可見」——兩種情況都能吃游標錨點。

    回傳 dict：fit/scale/zoom、cx/cy（實際相機中心，底圖像素）、
    want_cx/want_cy（使用者要求的中心，只夾在底圖範圍內）、
    box（可見底圖區塊 left,top,right,bottom）、draw（圖塊畫在畫布的 x,y,w,h）、
    view（可見範圍大小，底圖像素）。
    """
    fit = map_fit_scale(iw, ih, width, height)
    zoom = max(MAP_MIN_ZOOM, float(zoom))
    scale = fit * zoom
    half_w = width / (2.0 * scale)
    half_h = height / (2.0 * scale)
    want_x = iw / 2.0 if cx is None else min(max(float(cx), 0.0), float(iw))
    want_y = ih / 2.0 if cy is None else min(max(float(cy), 0.0), float(ih))
    eff_x = map_clamp_axis(want_x, width / scale, iw)
    eff_y = map_clamp_axis(want_y, height / scale, ih)
    left = max(0.0, eff_x - half_w)
    right = min(float(iw), eff_x + half_w)
    top = max(0.0, eff_y - half_h)
    bottom = min(float(ih), eff_y + half_h)
    return {
        'fit': fit, 'scale': scale, 'zoom': zoom, 'iw': iw, 'ih': ih,
        'cx': eff_x, 'cy': eff_y, 'want_cx': want_x, 'want_cy': want_y,
        'box': (left, top, right, bottom),
        'draw': (width / 2.0 + (left - eff_x) * scale,
                 height / 2.0 + (top - eff_y) * scale,
                 (right - left) * scale, (bottom - top) * scale),
        'view': (width / scale, height / scale),
    }


def map_project(xy, cam, width, height):
    """世界格 → 畫布座標（城池方塊、名稱、部隊都走這裡）。

    原作地面是 48×24 的**交錯菱格**，不是線性縮放：``world_pixel`` 給的是
    格子中心，奇數列整排右移 48 px。舊版用 ``x / WORLD_X * 底圖寬`` 投影，
    城池方塊會跟地形差一格（越往東南差越多）。
    """
    if _world_pixel is None:
        return (-1e6, -1e6)
    px, py = _world_pixel(float(xy[0]), float(xy[1]))
    return (width / 2.0 + (px - cam['cx']) * cam['scale'],
            height / 2.0 + (py - cam['cy']) * cam['scale'])


def map_unproject(px, py, cam, width, height):
    """畫布座標 → mbm 像素（點擊用；城池命中仍然走 _cmd_map_hits）。"""
    return (cam['cx'] + (px - width / 2.0) / cam['scale'],
            cam['cy'] + (py - height / 2.0) / cam['scale'])


def map_xy(value):
    """城池／部隊座標 → (x, y)；不合法回 None。

    一筆壞座標（None、字串、NaN、負值）不該讓整張地圖畫不出來——舊版直接
    ``xy[0] < 0`` 比較，遇到字串或 None 就拋 TypeError，整張圖變成空白。
    """
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if x != x or y != y:          # NaN
        return None
    if x < 0 and y < 0:
        return None
    return x, y


def wheel_steps(delta):
    """滾輪 / 觸控板 → 縮放步數（1 步 = ×1.2）。

    實體滾輪一格通常是 ±120（X11/Windows）→ 1 步；macOS 觸控板給很多
    個 ±1 的小事件 → 每個事件 1 步。舊版只看正負號，所以一個手勢會
    連跳十幾格，縮放像失控。
    """
    try:
        delta = float(delta)
    except (TypeError, ValueError):
        return 0.0
    if delta == 0.0:
        return 0.0
    if abs(delta) >= 60.0:
        return max(-3.0, min(3.0, delta / 120.0))
    return max(-1.0, min(1.0, delta))


def map_zoom(zoom):
    try:
        zoom = float(zoom)
    except (TypeError, ValueError):
        return MAP_MIN_ZOOM
    return max(MAP_MIN_ZOOM, min(MAP_MAX_ZOOM, zoom))


def map_lock_viewport(canvas):
    """Keep Tk's viewport at (0,0); only the map camera may pan.

    Without a scrollregion, Tk can move its origin while yview() still says
    (0,1). The inherited panorama's TouchpadScroll fallback used to do this
    to our canvases. Match the region to the drawable interior, accounting
    for the border so canvasx(0)/canvasy(0) stay exactly zero.
    """
    inset = sum(canvas.winfo_pixels(canvas.cget(key))
                for key in ('borderwidth', 'highlightthickness'))
    width, height = canvas.winfo_width(), canvas.winfo_height()
    canvas.configure(scrollregion=(inset, inset, max(inset, width - inset),
                                   max(inset, height - inset)), confine=True)
    canvas.xview_moveto(0)
    canvas.yview_moveto(0)


# 聊天 → 遊戲時間（例：200年春）：第一次看到該條訊息時讀到的回合，存本機小檔。
CHAT_TIMES = Path(__file__).resolve().parent / 'data' / 'chat-times.json'


def wall_text(value):
    if not isinstance(value, (int, float)):
        return '—'
    try:
        return datetime.fromtimestamp(value).strftime('%m-%d %H:%M:%S')
    except (OSError, ValueError, OverflowError):
        return '—'


def dur_text(value):
    """Human duration for long-run listening windows; never negative."""
    try:
        seconds = int(max(0, float(value)))
    except (TypeError, ValueError):
        return '—'
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours:
        return '{}時{:02d}分'.format(hours, minutes)
    if minutes:
        return '{}分'.format(minutes)
    return '{}秒'.format(rem)


def force_payload(result):
    """席位助手 JSON（{'slot_forces': ...}）：直接給的 dict 或 stdout 尾行的 JSON。"""
    if isinstance(result, dict) and 'slot_forces' in result:
        return result
    raw = (result.get('stdout') or '').strip()
    for line in reversed(raw.splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and 'slot_forces' in payload:
            return payload
    return None


def notify_operator(title, message, sound='Glass'):
    """摘席流程的本地提示：聲音＋系統通知。

    讓操作者在遊戲視窗在前時也能察覺「先勿按開始／可以按開始」。
    只在本機發出（macOS osascript/afplay）；不觸碰遊戲、會話或網路。
    """
    try:
        if sys.platform == 'darwin':
            safe_title = str(title).replace('"', ' ')
            safe_message = str(message).replace('"', ' ')
            subprocess.Popen(
                ['osascript', '-e',
                 'display notification "{}" with title "{}"'.format(safe_message, safe_title)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.Popen(
                ['afplay', '/System/Library/Sounds/{}.aiff'.format(sound)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


class FengyeWindow(OmniWindow):
    # 每回合 2 分鐘才推一次廣播 → 門檻必須大於 2 分鐘：
    # 130 秒＝已經錯過一輪（黃）、260 秒＝連錯兩輪（紅，判定掉線）。
    WIRE_WARN = 130
    WIRE_SILENCE = 260
    def __init__(self, root, source=None):
        self.source = source or FengyeSource()
        self.messages = queue.Queue()
        self.jobs = queue.Queue(maxsize=1)
        self.view = self.source.view
        self.control_busy = False
        self.cooldown = 0
        self.pending_id = None
        self.pending_run = None
        self.pending_uncertain = False
        self.render_signature = None
        self.render_error = None
        self.rooms = RoomClient(host=self.source.sources.host, replay=bool(self.source.sources.source_file))
        self.room_busy = False
        self.room_pending = None
        self.room_uncertain = False
        self.room_rows = {}
        self.room_signature = None
        self.retry = None
        self.capture_status = CaptureStatus()
        super().__init__(root)
        root.title('化神指揮部')
        root.minsize(1120, 700)
        try:
            _release = json.loads((Path(__file__).resolve().parent / 'RELEASE.json').read_text(encoding='utf-8'))
            _version = str(_release.get('version') or '0.0.0')
        except Exception:
            _version = '0.0.0'
        self.version_label.configure(text='版本 ' + _version)
        self.identity_label.master.pack_forget()
        self.status.configure(text='掌握風夜狀態，再開始遊戲', fg='#d7ebea')
        self.coverage.configure(text='只顯示已確認的情況；尚未讀到的資料會清楚標示。')
        # 2026-10-17：玩家視角頁面（永久停用）不再顯示會誤導的等待文案。
        try:
            self.resources.configure(
                text='本頁是原版「玩家視角」世界情報（已永久關閉，不會有資料）。\n'
                     '風夜相關操作與狀態請看「風夜操控台」。',
                font=(self.face, 12), justify='left')
        except Exception:
            pass
        top = self.version_label.master
        from fengye_icon import logo_photo
        logo = logo_photo(top, 44)
        if logo is not None:
            self.fengye_logo = tk.Label(top, image=logo, bg=PANEL)
            self.fengye_logo.image = logo
            self.fengye_logo.pack(side='left', before=top.winfo_children()[0], padx=(12, 0))
        for w in top.winfo_children():
            if isinstance(w, tk.Label) and w.cget('text') == '全知情报':
                w.configure(text='化神指揮部')
        self.original_tabs = list(self.workspace.tabs())
        # 2026-10-18（0.2.18）：遊戲記錄顯示由全知情報來源承擔；本 Hub 收攏為單一
        # 「風夜操控台」——原「本局局勢／房間與來源記錄／風夜指令解讀」分頁移除。
        # 原版「玩家視角」頁面永久關閉（不會有資料），入口收起避免混淆。
        self._build_console()
        for tab in self.original_tabs:
            try:
                self.workspace.hide(tab)
            except Exception:
                pass
        from fengye_force_views import mount_force_views
        mount_force_views(self)
        self.workspace.select(self.console_page)
        self._style_player_shell()
        self.render_view(self.view)
        threading.Thread(target=self._fetch_fengye, daemon=True, name='fengye-evidence-reader').start()
        self.root.after(250, self._tick_fengye)

    def fetch(self):
        """Never start the inherited player API/evidence polling path."""
        return

    def tick(self):
        return

    def confirm_player(self, clear=False):
        return

    def pick_history_archive(self):
        return

    def clear_history_review(self):
        return

    def _apply_review(self, bundle):
        raise ValueError('玩家視角的全知檔案來源已關閉')

    def _page(self, title, index=None):
        page = tk.Frame(self.workspace, bg=DAMASK)
        if index is None:
            self.workspace.add(page, text=title)
        else:
            self.workspace.insert(index, page, text=title)
        return page

    def _text(self, parent, height=5):
        frame = tk.Frame(parent, bg=WELL)
        frame.pack(fill='both', expand=True, padx=8, pady=6)
        w = tk.Text(frame, height=height, bg=WELL, fg=INK, wrap='word', relief='flat',
                    font=(self.face, 11), state='disabled', padx=10, pady=8)
        scroll = ttk.Scrollbar(frame, command=w.yview)
        scroll.pack(side='right', fill='y')
        w.configure(yscrollcommand=scroll.set)
        w.pack(side='left', fill='both', expand=True)
        return w

    @staticmethod
    def _set_text(widget, text):
        if widget.get('1.0', 'end-1c') == text:
            return
        pos = widget.yview()[0]
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text)
        widget.configure(state='disabled')
        widget.yview_moveto(pos)

    def _box(self, parent, title):
        return tk.LabelFrame(parent, text=title, bg=DAMASK, fg=GOLD,
                             font=(self.face, 12, 'bold'), relief='flat', bd=0,
                             padx=8, pady=8)

    def _style_player_shell(self):
        self.root.configure(bg=DAMASK)
        def restyle(widget):
            options = {}
            for key in ('background', 'foreground'):
                try:
                    value = str(widget.cget(key))
                    if value in LEGACY_COLORS:
                        options[key] = LEGACY_COLORS[value]
                except tk.TclError:
                    pass
            if isinstance(widget, tk.Button):
                options.update(relief='flat', bd=0, padx=12, pady=7,
                               font=(self.face, 11), cursor='hand2')
            if options:
                widget.configure(**options)
            for child in widget.winfo_children():
                restyle(child)
        restyle(self.root)
        style = ttk.Style(self.root)
        style.configure('TNotebook', background=DAMASK, borderwidth=0)
        style.configure('FengyeOuter.TNotebook', background=DAMASK, borderwidth=0)
        style.layout('FengyeOuter.TNotebook.Tab', [])
        self.workspace.configure(style='FengyeOuter.TNotebook')
        style.configure('TNotebook.Tab', padding=(18, 10), font=(self.face, 11),
                        background=BG, foreground=MUTED)
        style.map('TNotebook.Tab', background=[('selected', WELL)],
                  foreground=[('selected', GOLD)])
        style.configure('Treeview', background=WELL, fieldbackground=WELL,
                        foreground=INK, rowheight=36, borderwidth=0,
                        font=(self.face, 11))
        style.configure('Treeview.Heading', background=BG, foreground=GOLD,
                        font=(self.face, 11, 'bold'), relief='flat')
        style.map('Treeview', background=[('selected', '#d9eceb')],
                  foreground=[('selected', INK)])
        self.reload_btn.configure(text='更新資料', command=self.request_refresh)
        self.console_state.configure(wraplength=1040, justify='left')
        if self.source.sources.source_file:
            def disable(widget):
                if isinstance(widget, tk.Button):
                    widget.configure(state='disabled')
                for child in widget.winfo_children():
                    disable(child)
            disable(self.console_page)

    def _build_console(self):
        self.console_page = self._page('化神指揮部', 1)
        self.console_state = tk.Label(self.console_page, text='未就緒', bg=PANEL, fg=GOLD_HI,
                                      font=(self.face, 15, 'bold'), anchor='w', padx=16, pady=12)
        self.console_state.pack(fill='x', padx=12, pady=8)
        self.control_book = ttk.Notebook(self.console_page)
        self.control_book.pack(fill='both', expand=True, padx=12, pady=(0, 10))
        self.room_control_page = tk.Frame(self.control_book, bg=DAMASK)
        self.chat_control_page = tk.Frame(self.control_book, bg=DAMASK)
        self.command_page = tk.Frame(self.control_book, bg=DAMASK)
        self.control_book.add(self.room_control_page, text='進房與準備')
        self.control_book.add(self.chat_control_page, text='聊天與操作結果')
        self.control_book.add(self.command_page, text='指令')
        self._build_room_controls()
        self._build_command_controls()
        tk.Label(self.chat_control_page, text='以風夜的名義發言', bg=DAMASK, fg=GOLD,
                 font=(self.face, 14, 'bold'), anchor='w').pack(fill='x', padx=18)
        self.chat_input = tk.Text(self.chat_control_page, height=4, wrap='word', bg=WELL, fg=INK,
                                  font=(self.face, 13), padx=12, pady=10)
        self.chat_input.pack(fill='x', padx=16, pady=8)
        buttons = tk.Frame(self.chat_control_page, bg=DAMASK)
        buttons.pack(fill='x', padx=16)
        self.chat_button = tk.Button(buttons, text='以風夜發言', bg=BG, fg=INK, command=self.send_chat)
        self.chat_button.pack(side='left')
        self.char_label = tk.Label(buttons, text='0 / 120 字', bg=DAMASK, fg=MUTED)
        self.char_label.pack(side='left', padx=12)
        self.stop_button = tk.Button(buttons, text='風夜下線（正常退出）', bg='#ead4c6', fg=WARN, command=self.send_stop)
        self.stop_button.pack(side='right')
        self.chat_input.bind('<<Modified>>', self.input_changed)
        self.control_result = tk.Label(self.chat_control_page, text='每按一次只送出一次；還沒看到結果時，請先更新狀態。',
                                      bg=DAMASK, fg=MUTED, anchor='w', justify='left', wraplength=1050)
        self.control_result.pack(fill='x', padx=18, pady=10)
        panes = tk.PanedWindow(self.chat_control_page, orient='horizontal', bg=DAMASK, sashwidth=9)
        panes.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        chats = self._box(panes, '聊天記錄')
        receipts = self._box(panes, '最近操作結果')
        panes.add(chats, minsize=360, stretch='always')
        panes.add(receipts, minsize=360, stretch='always')
        self.console_chat = self._text(chats, 10)
        self.control_log = self._text(receipts, 10)
        self.chat_history_page = tk.Frame(self.control_book, bg=DAMASK)
        self.control_book.add(self.chat_history_page, text='聊天歷史')
        tk.Label(self.chat_history_page, text='本局收到的聊天（唯讀，逐條按時間）', bg=DAMASK, fg=GOLD,
                 font=(self.face, 13, 'bold'), anchor='w').pack(fill='x', padx=16, pady=(10, 2))
        tk.Label(self.chat_history_page, text='目前只顯示風夜連線收到的聊天；同盟／私聊頻道是否可旁聽尚未驗證（P60）。'
                                       '名字後面括號是勢力，名字與內文用該勢力的原作配色（太亮會壓暗以便閱讀）。'
                                       '每條前面的「200年春」是 Hub 第一次看到該訊息時讀到的回合'
                                       '（每 3 秒更新，可能差幾秒；讀不到就寫「回合未記錄」，不補造）。',
                 bg=DAMASK, fg=MUTED, anchor='w', justify='left',
                 wraplength=1100).pack(fill='x', padx=16, pady=(0, 4))
        self.chat_history = self._text(self.chat_history_page, 14)
        # 2026-10-21 使用者要求：實驗室、玩家與遊戲分頁都已移除。
        # 2026-10-19 用戶要求：只留一頁聊天歷史；其餘兩頁隱藏（元件保留，避免既有刷新路徑失效）。
        self.control_book.hide(self.chat_control_page)
        # 2026-10-21 使用者要求：戰場／玩家與遊戲兩頁徹底移除（不再 hide 保留元件）。
        # 0.2.18：資料讀取等系統訊息集中在這一行（原「本局局勢」頁的提示已移除）。
        self.notice_label = tk.Label(self.console_page, text='', bg=DAMASK, fg=MUTED, anchor='w',
                                     justify='left', wraplength=1100)
        self.notice_label.pack(fill='x', padx=14, pady=(0, 8))

    # ---------------------------------------------------------- 指令
    def _build_command_controls(self):
        from command_panel import CommandPanel
        replay = bool(self.source.sources.source_file)
        history = None if replay else Path(__file__).resolve().parent / 'data' / 'command-history.json'
        self.command_service = CommandService(history_path=history)
        self.command_panel = CommandPanel(
            self.command_page, self.command_service,
            on_snapshot=self._command_snapshot, readonly=replay, on_error=self._capture_failed)
        try:
            self._load_account()
        except Exception:  # noqa: BLE001
            pass
        # 2026-10-21 使用者定案：這一頁只留「切換勢力 + 身份」＋快速軍令入口。
        # CommandPanel 仍建立但不顯示，它的 3 秒讀取繼續供身份/勢力清單使用。
        self.command_panel.pack_forget()
        self._build_quick_bar()

    def _build_quick_bar(self):
        """指令頁＝風夜席位 ＋ 即時狀態／回合跟隨 ＋ 內嵌快速軍令 ＋ 讓對手掉線。

        2026-10-21 使用者三項定案：
        ①快速軍令搬進本頁（不再另開獨立視窗）；
        ②拿掉「重新连接／刷新状态／回合 +10秒」三個手動鈕，改成每秒自動顯示目前狀態與
          回合跟隨判定（玩家資訊 120 秒內要回來，240 秒判定掉隊）；
        ③實驗室的「讓對手掉線」搬到本頁最下方。
        """
        holder = tk.Frame(self.command_page, bg=DAMASK)
        holder.pack(side='left', fill='both', expand=True, padx=14, pady=12)
        # 面板維持原本「單欄」的比例（太寬會把按鈕拉成長條）：置中，最寬 1040。
        column = tk.Frame(holder, bg=DAMASK, width=1040)
        column.place(relx=0.5, rely=0.0, anchor='n', relheight=1.0)

        def fit_column(event, frame=column):
            frame.configure(width=max(680, min(1040, int(event.width))))

        holder.bind('<Configure>', fit_column, add='+')
        # 2026-10-22 使用者定案：刪除「讓對手掉線」（遠端沒有執行能力，功能無效）
        # self._build_drop_box(column)
        head = tk.Frame(column, bg=DAMASK)
        head.pack(fill='x')
        tk.Label(head, text='風夜席位', bg=DAMASK, fg=GOLD,
                 font=(self.face, 13, 'bold')).pack(side='left')
        self.quick_force = tk.StringVar()
        self.quick_box = ttk.Combobox(head, textvariable=self.quick_force, width=26, state='readonly')
        self.quick_box.pack(side='left', padx=8)
        tk.Button(head, text='切換', bg=BG, command=self._quick_switch).pack(side='left')
        self.quick_state = tk.Label(head, text='讀取中…', bg=DAMASK, fg=MUTED,
                                    anchor='w', font=(self.face, 11, 'bold'))
        self.quick_state.pack(side='left', padx=12)
        tk.Label(column,
                 text='快速軍令已內嵌在本頁：連上遊戲後直接按面板按鈕（F7／F8–F11 只在這一頁生效）。',
                 bg=DAMASK, fg=MUTED, anchor='w', justify='left',
                 font=(self.face, 11)).pack(fill='x', pady=(6, 6))

        strip = tk.Frame(column, bg=WELL, highlightthickness=1, highlightbackground='#d7e3ea')
        strip.pack(fill='x', pady=(0, 8))
        self.cmd_live = tk.Label(strip, text='即時狀態：等待讀取…', bg=WELL, fg=INK,
                                 anchor='w', justify='left', wraplength=990,
                                 font=(self.face, 11))
        self.cmd_live.pack(fill='x', padx=12, pady=(8, 2))
        self.cmd_follow = tk.Label(strip, text='回合跟隨：等待玩家資訊', bg=WELL, fg=MUTED,
                                   anchor='w', justify='left', wraplength=990,
                                   font=(self.face, 11, 'bold'))
        self.cmd_follow.pack(fill='x', padx=12, pady=(0, 8))

        self.quick_panel_host = tk.Frame(column, bg=DAMASK)
        self.quick_panel_host.pack(fill='both', expand=True)
        self.quick_panel = None
        from turn_follow import TurnFollower
        self._turn_follower = TurnFollower()
        self._last_when = ''
        self._cmd_wire = {}
        self.control_book.bind('<<NotebookTabChanged>>', self._quick_tab_changed, add='+')
        self.root.after(1200, self._tick_command_status)

    # ------------------------------------------------------------ 即時狀態／回合跟隨
    def _round_when(self, data):
        """「200年春」這種回合座標；讀不到就回空字串（不補造）。"""
        from turn_follow import round_when
        return round_when(data)

    def _poll_command_wire(self, now):
        """每 3 秒在背景讀一次風夜自己連線的收包計數（不阻塞畫面）。"""
        if now - getattr(self, '_cmd_wire_at', 0) < 3 or getattr(self, '_cmd_wire_busy', False):
            return

        self._cmd_wire_at = now
        self._cmd_wire_busy = True

        def work():
            try:
                info = self.command_service.wire_health()
            except Exception as error:  # noqa: BLE001
                info = {'ok': False, 'error': str(error)}
            self._cmd_wire = info
            self._cmd_wire_busy = False

        threading.Thread(target=work, daemon=True, name='command-wire').start()

    def _tick_command_status(self):
        try:
            self._render_command_status()
        except Exception as error:  # noqa: BLE001
            report('command-status', error)
        try:
            self.root.after(1000, self._tick_command_status)
        except tk.TclError:
            pass

    def _render_command_status(self):
        now = time.monotonic()
        self._poll_command_wire(now)
        wire = getattr(self, '_cmd_wire', None) or {}
        data = getattr(self, 'cmd_targets_data', None) or {}
        panel = getattr(self, 'quick_panel', None)
        state = dict(getattr(panel, 'current_state', None) or {}) if panel is not None else {}
        when = self._round_when(data)

        bits = []
        remaining = state.get('remaining_ms')
        if state.get('timer_known') is False:
            bits.append('計時未知')
        elif isinstance(remaining, int):
            bits.append('倒計時 %.1f 秒' % (max(0, remaining) / 1000.0))
        phase = (data.get('phase_text') or '').strip()
        if phase and phase != '未知':
            bits.append(phase)
        used = state.get('orders_used')
        if isinstance(used, int):
            bits.append('指令 %d/3' % used)
        if when:
            bits.append(when)
        if panel is None:
            bits.append('面板尚未建立（切到本頁就會連接）')
        elif not panel.ready:
            note = (panel.status.get() or '').strip()
            bits.append(note or '等待對局')
        self.cmd_live.configure(text='即時狀態：' + ' · '.join(bits), fg=INK)

        received = wire.get('received')
        event = self._turn_follower.observe(
            now, received=received if isinstance(received, int) else None,
            run=wire.get('run'), connected=wire.get('connected'))
        if event in ('start', 'data', 'recovered') and when:
            self._last_when = when          # 最近一次真的收到玩家資訊時的回合座標
        from turn_follow import round_shift, sync_phrase
        # 回合座標只講一次：有「收包 vs 現在」那段時就不再重複塞在判詞後面。
        shift = round_shift(getattr(self, '_last_when', ''), when)
        state_name, text = self._turn_follower.describe(now, '' if shift else when)
        colour = {'ok': '#2e7d32', 'warn': WARN, 'lost': WARN}.get(state_name, MUTED)
        extra = ['120 秒正常／240 秒判掉隊']
        if shift:
            extra.append(shift)
        phrase = sync_phrase(getattr(self, 'sync_data', None))
        if phrase:
            extra.append(phrase)
        if isinstance(received, int) and received > 0:
            extra.append('累計 %s 筆' % format(received, ','))
        if wire and not wire.get('ok'):
            extra.append('讀不到風夜連線狀態')
        self.cmd_follow.configure(text='回合跟隨：%s ｜%s' % (text, '｜'.join(extra)), fg=colour)

    # ------------------------------------------------------------ 讓對手掉線（原實驗室）
    def _build_drop_box(self, column):
        """把「讓對手掉線」壓在指令頁最下方：破壞性操作，維持每次二次確認。"""
        box = tk.Frame(column, bg='#fdeeee', highlightthickness=1, highlightbackground='#e6c9c9')
        box.pack(side='bottom', fill='x', pady=(8, 0))
        head = tk.Frame(box, bg='#fdeeee')
        head.pack(fill='x', padx=10, pady=(6, 0))
        tk.Label(head, text='讓對手掉線', bg='#fdeeee', fg=WARN,
                 font=(self.face, 12, 'bold')).pack(side='left')
        tk.Label(head, text='破壞性操作：每次確認、失敗不重試；對方約 30–40 秒後被主機判離線。',
                 bg='#fdeeee', fg=MUTED, font=(self.face, 10)).pack(side='left', padx=8)
        bar = tk.Frame(box, bg='#fdeeee')
        bar.pack(fill='x', padx=10, pady=4)
        tk.Label(bar, text='目標：', bg='#fdeeee', fg=INK).pack(side='left')
        self.drop_target = tk.StringVar(value='丁滿（主機）')
        ttk.Combobox(bar, textvariable=self.drop_target, width=14, state='readonly',
                     values=['丁滿（主機）', '風雲']).pack(side='left', padx=6)
        self.drop_button = tk.Button(bar, text='讓對手掉線', bg='#f7e5e5', fg=WARN,
                                     command=self.drop_client)
        self.drop_button.pack(side='left', padx=4)
        tk.Button(bar, text='檢查本機客戶端', bg=BG, command=self.drop_check).pack(side='left', padx=4)
        self.drop_label = tk.Label(box, text='', bg='#fdeeee', fg=INK, anchor='w',
                                   justify='left', wraplength=980, font=(self.face, 10))
        self.drop_label.pack(fill='x', padx=10, pady=(0, 6))

    def _quick_tab_changed(self, _event=None):
        try:
            page = self.control_book.nametowidget(self.control_book.select())
        except Exception:  # noqa: BLE001
            return
        if page is self.command_page:
            self._ensure_quick_panel()

    def _panel_palette(self):
        """內嵌面板改用 Hub 的淺藍白／墨綠配色（不再出現整片米黃＋金色）。"""
        return dict(paper=DAMASK, rim='#c3d3dd', ink=INK, muted=MUTED,
                    title=GOLD, gold=GOLD, timer=INK, hint='#3f6b74',
                    receipt=GOLD, candidate='#dcebf1', button=BG,
                    button_active='#f2f7fa', button_pressed='#d5e3ea',
                    button_border='#a9bcc7', button_light='#ffffff', button_dark='#b9c9d4',
                    disabled='#9cb0bd', disabled_bg='#eef3f6', separator='#cfdbe3',
                    trough='#d7e4ea', root_bg=DAMASK)

    def _ensure_quick_panel(self):
        """第一次切到指令頁時建立面板；之後直接沿用同一個面板。"""
        if getattr(self, 'quick_panel', None) is not None:
            return self.quick_panel
        host = getattr(self, 'quick_panel_host', None)
        if host is None:
            return None
        try:
            from quick_command_embed import mount_quick_panel
            self.quick_panel = mount_quick_panel(host, bg=DAMASK,
                                                 palette=self._panel_palette())
        except Exception as error:  # noqa: BLE001
            for child in host.winfo_children():
                child.destroy()
            tk.Label(host, text='快速軍令載入失敗：%s' % error, bg=DAMASK, fg=WARN,
                     anchor='w', justify='left', wraplength=900,
                     font=(self.face, 11)).pack(fill='x', padx=6, pady=10)
            report('quick-command-embed', error)
            self.quick_panel = None
            return None
        try:
            self.quick_panel.focus_panel()
        except Exception:  # noqa: BLE001
            pass
        return self.quick_panel

    def dispose_quick_panel(self):
        """Hub 關閉時收掉面板（會請 Wine 輔助程式退出，不會動遊戲）。"""
        panel = getattr(self, 'quick_panel', None)
        self.quick_panel = None
        if panel is None:
            return
        try:
            panel.close()
        except Exception as error:  # noqa: BLE001
            report('quick-command-close', error)

    def _quick_switch(self):
        choice = (self.quick_force.get() or '').strip()
        import re as _re
        if choice.startswith('無勢力'):
            self._switch_seat(5, '無勢力')
            return
        found = _re.search(r'slot\s*(\d)', choice)
        if found:
            self._switch_seat(int(found.group(1)), choice.split('（')[0])

    def _autostart_quick_panel(self):
        """（已停用）2026-10-21 使用者：不再自動開獨立視窗；面板改成內嵌在指令頁。"""
        return None

    def _open_quick_panel(self, silent=False):
        """舊入口（開獨立視窗）→ 改成切到指令頁並確保內嵌面板存在。"""
        for tid in self.control_book.tabs():
            if self.control_book.tab(tid, 'text') == '指令':
                self.control_book.select(tid)
                break
        return self._ensure_quick_panel()

    def _cmd_refresh(self):
        return self.command_panel.refresh()

    def _cmd_draw_map(self):
        # The original world map and its timeline keep their view on tab change.
        self.command_panel.render_jobs()

    # ------------------------------------------------------------ 戰場（唯讀）
    def _render_quick_bar(self, data):
        if not hasattr(self, 'quick_state'):
            return
        players = {s.get('force_id'): s.get('nickname') for s in data.get('player_slots') or []}
        values = ['無勢力']
        for force in data.get('forces') or []:
            name = players.get(force.get('force_id')) or '未知玩家'
            values.append('%s（slot %s）· %s' % (name, force.get('slot'),
                                                force.get('name') or ''))
        current = self.quick_force.get()
        self.quick_box.configure(values=values)
        if current not in values:
            self.quick_force.set(values[0])
        local = data.get('local') or {}
        force = local.get('force_id')
        if not isinstance(force, int) or force < 0:
            text = '風夜目前：無勢力（旁聽）'
            colour = MUTED
        else:
            name = next((f.get('name') for f in data.get('forces') or []
                         if f.get('force_id') == force), None)
            text = '風夜目前：%s（force %s，slot %s）' % (name or '?', force, local.get('slot'))
            colour = ACCENT
        self.quick_state.configure(text=text, fg=colour)

    def _command_snapshot(self, data):
        self.cmd_targets_data = data
        try:
            self._render_quick_bar(data)
        except Exception:  # noqa: BLE001
            pass
        if data.get('_battle_payload'):
            self._accept_shadow_snapshot(data['_battle_payload'])

    def _accept_shadow_snapshot(self, payload):
        changed = self.capture_status.observe(payload)
        if changed:
            from fengye_force_views import update_force_views
            try:
                if not update_force_views(self, payload) and getattr(self, 'force_views_error', None):
                    report('force-views', RuntimeError(self.force_views_error))
            except Exception as exc:
                report('force-views', exc)
        self._render_capture_status()

    def _capture_failed(self):
        self.capture_status.failed = True
        self._render_capture_status()

    def _render_capture_status(self):
        self.status.configure(text=self.capture_status.text(replay=bool(self.source.sources.source_file)))

    def _build_room_controls(self):
        box = self._box(self.room_control_page, '幽靈進房與準備')
        box.pack(fill='both', expand=True, padx=14, pady=14)
        tk.Label(box, text='進房、確認準備狀態，然後開始遊戲。',
                 bg=DAMASK, fg=MUTED, anchor='w').pack(fill='x', padx=14, pady=(10, 8))
        probe_box = tk.Frame(box, bg=DAMASK)
        self.room_line = tk.StringVar(value='多线3')
        self.room_nickname = tk.StringVar(value='待秋至')
        primary = tk.Frame(probe_box, bg=DAMASK)
        primary.pack(fill='x', padx=8, pady=(8, 0))
        self.room_once = tk.Button(primary, text='自動登入、找房並進入', bg=BG, command=self.one_click_enter)
        self.room_once.pack(side='left')
        bar = tk.Frame(probe_box, bg=DAMASK)
        bar.pack(fill='x', padx=8, pady=8)
        self.room_line_combo = ttk.Combobox(bar, textvariable=self.room_line, width=8,
                                          values=['多线2', '多线3'], state='readonly')
        self.room_line_combo.pack(side='left')
        self.room_start = tk.Button(bar, text='登入風夜', bg=BG,
                                    command=lambda: self.room_action({'op': 'start', 'line': self.room_line.get()}))
        self.room_start.pack(side='left', padx=5)
        # 2026-10-21：一鍵（線路＋房間號/IP）→ 登入→進房→補丁→綁勢力→藏身（D8）。
        tk.Label(bar, text='房間號/IP', bg=DAMASK, fg=INK).pack(side='left', padx=(10, 4))
        self.room_target = tk.StringVar(value='')
        ttk.Entry(bar, textvariable=self.room_target, width=16).pack(side='left')
        self.room_oneclick = tk.Button(bar, text='一鍵進房（IP/房間號）', bg='#cbe7e4', fg='#164d51',
                                       command=self.oneclick_by_target)
        self.room_oneclick.pack(side='left', padx=5)
        self.room_search = tk.Button(bar, text='更新房間', bg=BG,
                                     command=lambda: self.room_action({'op': 'search'}))
        self.room_search.pack(side='left')
        tk.Label(bar, text='進房暱稱', bg=DAMASK, fg=INK).pack(side='left', padx=(12, 5))
        try:
            _names = self.command_service.read_names().get('names') or ['待秋至']
        except Exception:  # noqa: BLE001
            _names = ['待秋至']
        self.room_nick_combo = ttk.Combobox(bar, textvariable=self.room_nickname, width=12,
                                          values=_names, state='normal')
        self.room_nick_combo.pack(side='left')
        # 2026-10-21：偽名庫——打過的名字可存起來，下次直接從下拉切換。
        tk.Button(bar, text='記住此名', bg=BG, command=self.remember_nickname).pack(side='left', padx=4)
        acc = tk.Frame(box, bg=DAMASK)
        acc.pack(fill='x', padx=12, pady=(4, 0))
        tk.Label(acc, text='登入帳號', bg=DAMASK, fg=INK,
                 font=(self.face, 11, 'bold')).pack(side='left')
        self.account_user = tk.StringVar(value='')
        self.account_pass = tk.StringVar(value='')
        try:
            _accounts = self.command_service.read_accounts()
        except Exception:  # noqa: BLE001
            _accounts = {'accounts': [], 'active': ''}
        self.account_choice = tk.StringVar(value=_accounts.get('active') or '')
        self.account_combo = ttk.Combobox(
            acc, textvariable=self.account_choice, width=12, state='readonly',
            values=[a.get('username') for a in _accounts.get('accounts') or []])
        self.account_combo.pack(side='left', padx=(6, 4))
        self.account_combo.bind('<<ComboboxSelected>>', lambda _e: self.switch_account())
        # 2026-10-21 使用者：帳號的新增／刪除移到「帳號／偽名設定」，這頁只留切換下拉。
        self.account_user_entry = ttk.Entry(acc, textvariable=self.account_user, width=14)
        self.account_pass_label = tk.Label(acc, text='密碼', bg=DAMASK, fg=INK)
        self.account_pass_entry = ttk.Entry(acc, textvariable=self.account_pass, width=14, show='*')
        self.account_save_btn = tk.Button(acc, text='儲存帳號', bg=BG, command=self._save_account)
        self.account_hint = tk.Label(acc, text='', bg=DAMASK, fg=MUTED)
        self.account_hint.pack(side='left', padx=8)
        self.room_join = tk.Button(bar, text='進入所選房間', bg=BG, command=self.join_selected_room)
        self.room_join.pack(side='left', padx=5)
        self.room_leave = tk.Button(bar, text='離開房間', bg=BG,
                                    command=lambda: self.room_action({'op': 'leave'}))
        self.room_leave.pack(side='left')
        self.room_stop = tk.Button(bar, text='幽靈下線', bg=BG,
                                   command=lambda: self.room_action({'op': 'stop'}))
        self.room_stop.pack(side='left', padx=5)
        flow = tk.Frame(probe_box, bg=DAMASK)
        flow.pack(fill='x', padx=8, pady=(0, 8))
        self.room_register = tk.Button(flow, text='完成報到', bg=BG, command=self.register_ghost)
        self.room_register.pack(side='left')
        self.room_d8 = tk.Button(flow, text='讓風夜藏好', bg=BG, command=self.withdraw_ghost)
        self.room_d8.pack(side='left', padx=8)
        self.room_flow_label = tk.Label(flow, bg=DAMASK, fg=MUTED)
        self.room_flow_label.pack(side='left', padx=8)
        pre = tk.Frame(box, bg=DAMASK)
        pre.pack(fill='x', padx=12, pady=(6, 2))
        tk.Label(pre, text='開局前上身（幽靈席位）', bg=DAMASK, fg=INK,
                 font=(self.face, 11, 'bold')).pack(side='left')
        self.pre_seat_value = tk.StringVar(value='0')
        self.bind_choice = tk.StringVar(value='玩家 2（slot 1）')
        self.bind_box = ttk.Combobox(
            pre, textvariable=self.bind_choice, width=18, state='readonly',
            values=['無勢力（不綁定）'] + ['玩家 %d（slot %d）' % (i + 1, i) for i in range(8)])
        self.bind_box.pack(side='left', padx=(6, 0))
        self.bind_box.bind('<<ComboboxSelected>>', lambda _event: self._sync_start_faction())
        self.pre_seat_hint = tk.Label(
            pre, bg=DAMASK, fg=INK, anchor='w',
            text='一鍵完成後自動綁定到這個玩家；選「無勢力」就不綁。')
        self.pre_seat_hint.pack(side='left', padx=(10, 0))
        sw = tk.Frame(box, bg=DAMASK)
        sw.pack(fill='x', padx=12, pady=(4, 0))
        tk.Label(sw, text='切換速鍵', bg=DAMASK, fg=INK,
                 font=(self.face, 11, 'bold')).pack(side='left')
        self.force_switch_row = tk.Frame(sw, bg=DAMASK)
        self.force_switch_row.pack(side='left', padx=8)
        self.pre_seat_label = tk.Label(pre, bg=DAMASK, fg=MUTED, anchor='w',
                                       text='0–7 是「席位」不是勢力；每局勢力隨機，套用後這裡會顯示 0→勢力X。')
        self.pre_seat_label.pack(side='left', padx=10, fill='x', expand=True)
        lab = tk.Frame(box, bg=DAMASK)
        lab.pack(fill='x', padx=12, pady=(2, 12))
        # 2026-10-21 使用者：主頁不再放「登入／下線／查看狀態／重新來過／搜索房間」。
        # 物件仍建立（其他流程會引用），只是不 pack 出來；入口統一成下面那一行
        # 「線路 → 房間號 → 一鍵登入」。
        self.lab_arm_btn = tk.Button(lab, text='登入（風夜）', bg='#cbe7e4', fg='#164d51',
                                     command=self.lab_arm, font=(self.face, 12, 'bold'))
        self.lab_stop_btn = tk.Button(lab, text='風夜下線', bg=BG, command=self.lab_stop)
        self.lab_status_btn = tk.Button(lab, text='查看幽靈狀態', bg=BG, command=self.lab_status)
        tk.Button(lab, text='卡住了？強制結束', bg='#f7e5e5', fg=WARN,
                  command=self.lab_force_quit).pack(side='left', padx=8)
        # 2026-10-22：替代 Launcher 的「結束遊戲」（那個 App 沒原始碼、按了沒反應）
        tk.Button(lab, text='結束客戶端（選帳號）', bg='#f7e5e5', fg=WARN,
                  command=self.open_end_client_dialog).pack(side='left', padx=8)
        # 2026-10-22：只關遊戲、保留大廳與協議會話 → 下次一鍵登入可直接再進
        tk.Button(lab, text='只關遊戲（大廳保留）', bg='#f7e5e5', fg=WARN,
                  command=self.game_off_local).pack(side='left', padx=8)
        # 2026-10-22：一鍵武裝（補丁→綁定 slot→D8），已在大廳/房間時也能用
        tk.Button(lab, text='一鍵武裝（補丁＋綁定＋摘席）', bg='#dff0d8', fg='#22551f',
                  command=self.arm_now_local,
                  font=(self.face, 12, 'bold')).pack(side='left', padx=8)
        # 2026-10-22：去霧（全視野）手動開關；一鍵預設「不裝」，保持開局迷霧
        tk.Button(lab, text='去霧（全視野）', bg='#fff4d6', fg='#6b4b00',
                  command=self.godview_on_local).pack(side='left', padx=8)
        # 2026-10-22 使用者定案：唯一保留的時間功能＝「本機 N 秒後自動結束回合」
        # 2026-10-22：自動結束放「獨立一列」，避免和上面那排按鈕擠在一起看不到
        auto_row = tk.Frame(box, bg=DAMASK)
        auto_row.pack(fill='x', padx=12, pady=(0, 10))
        tk.Label(auto_row, text='本機自動結束回合：每階段', bg=DAMASK, fg=INK).pack(side='left')
        self.auto_end_secs = tk.StringVar(value='45')
        tk.Entry(auto_row, textvariable=self.auto_end_secs, width=5).pack(side='left', padx=4)
        tk.Label(auto_row, text='秒後送出「階段結束」', bg=DAMASK, fg=INK).pack(side='left')
        tk.Button(auto_row, text='啟動', bg='#dff0d8', fg='#22551f',
                  command=self.auto_end_start).pack(side='left', padx=8)
        tk.Button(auto_row, text='停止', bg='#f7e5e5', fg=WARN,
                  command=self.auto_end_stop).pack(side='left')
        tk.Label(auto_row, text='（只作用本機風夜，不改任何人的倒數）', bg=DAMASK, fg=MUTED).pack(side='left', padx=8)
        self.auto_end_state = tk.Label(auto_row, text='狀態：未啟動', bg=DAMASK, fg=MUTED, anchor='w')
        self.auto_end_state.pack(side='left', padx=10)
        self.root.after(1200, self._refresh_auto_end)
        self.room_retry = tk.Button(lab, text='↻ 重新整理／再進房', bg=BG, command=self.one_click_retry)
        self.probe_toggle = tk.Button(lab, text='手動進房設定', bg=BG, command=self._toggle_probe_layer)
        self.probe_toggle.pack(side='right')
        # 2026-10-19 半自動進房：搜索房間（借探針）→ 清單選房（單房自動）→ 用指定暱稱走完整武裝進房。
        semi = tk.Frame(box, bg=DAMASK)
        semi.pack(fill='x', padx=12, pady=(0, 12))
        # 2026-10-21 使用者定案：主頁只留「線路 → 房間號 → 一鍵登入」。
        # 搜索房間／進房暱稱／記住此名／進入所選房間 收到「手動進房設定」與「帳號與偽名設定」裡。
        self.lab_nickname = tk.StringVar(value='')
        try:
            self.lab_nickname.set(self.command_service.active_name() or '')
        except Exception:  # noqa: BLE001
            pass
        # 2026-10-21：即時房間快選（多线2／多线3，來源 vkquant 的 sgi-tk 監控）。
        self.room_pick = ttk.Combobox(semi, width=40, state='readonly', values=[])
        self.room_pick.pack(side='left', padx=(0, 8))
        self.room_pick.bind('<<ComboboxSelected>>', lambda _e: self.pick_room())
        self._room_choices = []
        # 注意：_build_room_controls() 在 self.command_service 建立之前就跑，
        # 所以第一次抓取要排到初始化之後（after），不能同步呼叫。
        self.root.after(600, self._refresh_room_choices)
        self.root.after(700, self._refresh_identity)
        tk.Label(semi, text='房間號 / IP', bg=DAMASK, fg=INK,
                 font=(self.face, 11, 'bold')).pack(side='left', padx=(0, 6))
        ttk.Entry(semi, textvariable=self.room_target, width=16).pack(side='left')
        self.oneclick_btn = tk.Button(semi, text='一鍵登入', bg='#cbe7e4', fg='#164d51',
                                      command=self.oneclick_by_target, font=(self.face, 12, 'bold'))
        self.oneclick_btn.pack(side='left', padx=8)
        self.settings_btn = tk.Button(semi, text='帳號／偽名設定', bg=BG,
                                      command=self.open_settings_dialog)
        self.settings_btn.pack(side='left', padx=4)
        # 2026-10-21：拿掉「無勢力旁聽」勾選框。固定走 baseline：
        # 開局前 D8 摘席（名單看不到）→ 開局後 shadow_force 切席位上身 → 用遊戲自己的管線下指令。
        self.hide_after_join = tk.BooleanVar(value=True)
        self.oneclick_hint = tk.Label(semi, bg=DAMASK, fg=MUTED, anchor='w',
                                      text='房間號＝房主虛擬 IP（168593956 ↔ 10.12.138.36）；填哪個都行')
        self.oneclick_hint.pack(side='left', padx=6)
        # 一鍵的「執行中／結果」獨立一行，不會被房間表每 20 秒的刷新蓋掉。
        self.identity_label = tk.Label(box, bg=DAMASK, fg=INK, anchor='w', text='')
        self.identity_label.pack(fill='x', padx=14, pady=(4, 0))
        self.seat_status = tk.Label(box, bg=DAMASK, fg=MUTED, anchor='w', text='')
        self.seat_status.pack(fill='x', padx=14, pady=(2, 0))
        self.oneclick_state = tk.Label(box, bg=DAMASK, fg=MUTED, anchor='w', text='')
        self.oneclick_state.pack(fill='x', padx=14, pady=(2, 0))
        self._oneclick_busy = False
        # 2026-10-21（0.2.89）：線路選擇（房間清單在哪條線）＋解除卡住。
        line_row = tk.Frame(box, bg=DAMASK)
        line_row.pack(fill='x', padx=12, pady=(0, 8))
        tk.Label(line_row, text='線路', bg=DAMASK, fg=INK,
                 font=(self.face, 11, 'bold')).pack(side='left')
        self.ghost_line = tk.StringVar(value='多线3（备用）')
        self._line_state = {}
        ttk.Combobox(line_row, textvariable=self.ghost_line, width=14,
                     values=['多线2（主线）', '多线3（备用）'], state='readonly').pack(side='left', padx=(6, 0))
        tk.Button(line_row, text='解除卡住', bg=BG, command=self.lab_unblock).pack(side='left', padx=10)
        self.line_status_label = tk.Label(line_row, text='讀線路中…', bg=DAMASK, fg=MUTED, anchor='w')
        self.line_status_label.pack(side='left', padx=6)
        tk.Label(line_row, text='（線路＝房間清單所在的線；換線要重新登入一次）',
                 bg=DAMASK, fg=MUTED).pack(side='left', padx=4)
        self.probe_box, self._lab_row, self.probe_shown = probe_box, lab, False
        self.lab_label = tk.Label(box, text='',
                                 bg='#e4f1ef', fg='#245b61', anchor='w', justify='left',
                                 wraplength=1080, padx=14, pady=12)
        self.lab_label.pack(fill='x', padx=12, pady=(0, 12))
        # 2026-10-19 用戶裁定：固定無勢力旁觀 → 移除「起始勢力」切換列（功能仍在 CLI）。
        seat_row = tk.Frame(box, bg=DAMASK)
        self.start_faction = tk.StringVar(value='空位旁觀')
        # 2026-10-19 用戶要求：把風夜此刻可能的多種狀態用大白話列出來
        # （上帝視角已打開、回合自動跟隨…），不顯示任何欄位名或代碼。
        self.state_panel = tk.Frame(box, bg=WELL)
        # 2026-10-22：這塊是舊 collector 的檢查表（會說「不在線上／2-5」），與本機實況矛盾 → 收起。
        # 真實狀態看頂部「✅ 本機實況：…」那條。
        self._state_panel_hidden = True
        tk.Label(self.state_panel, text='風夜現在的狀態', bg=WELL, fg=INK,
                 font=(self.face, 13, 'bold'), anchor='w').pack(fill='x', padx=14, pady=(10, 6))
        # 2026-10-21 使用者要求：一眼看到風夜「現在」在哪個階段（不等一鍵進度）。
        self.live_label = tk.Label(self.state_panel, text='風夜還沒開遊戲', bg=WELL, fg=MUTED,
                                   anchor='w', font=(self.face, 14, 'bold'))
        self.live_label.pack(fill='x', padx=14, pady=(0, 0))
        self.live_hint = tk.Label(self.state_panel, text='按「登入（風夜）」開始', bg=WELL, fg=MUTED,
                                  anchor='w', font=(self.face, 11))
        self.live_hint.pack(fill='x', padx=14, pady=(0, 6))
        self.progress_label = tk.Label(self.state_panel, text='一鍵進度：尚未開始', bg=WELL, fg=INK,
                                       anchor='w', font=(self.face, 12, 'bold'))
        self.progress_label.pack(fill='x', padx=14, pady=(0, 4))
        self.progress_canvas = tk.Canvas(self.state_panel, height=14, bg='#d5e4e2',
                                         highlightthickness=0)
        self.progress_canvas.pack(fill='x', padx=14, pady=(0, 8))
        self._progress_key = None
        self.state_rows = tk.Frame(self.state_panel, bg=WELL)
        self.state_rows.pack(fill='x', padx=14, pady=(0, 4))
        # 2026-10-21：回合同步偵測（風夜 vs 本機真實玩家）——落後就等於主機無用。
        self.sync_label = tk.Label(self.state_panel, text='回合同步：等待對局…', bg=WELL,
                                   fg=MUTED, anchor='w', font=(self.face, 12, 'bold'))
        self.sync_label.pack(fill='x', padx=14, pady=(0, 2))
        self.wire_label = tk.Label(self.state_panel, text='', bg=WELL, fg=MUTED,
                                   anchor='w', font=(self.face, 11))
        self.wire_label.pack(fill='x', padx=14, pady=(0, 10))
        tk.Label(self.state_rows, text='還沒有風夜的即時狀態。', bg=WELL, fg=MUTED,
                 anchor='w').pack(fill='x')
        self.room_tree = self.tree(box, [('name', '房間名稱', 220), ('host', '房主', 180), ('count', '目前人數', 100)])
        self.room_tree.configure(height=6)
        self.room_tree.bind('<<TreeviewSelect>>', lambda _e: self.update_room_controls())
        self.room_empty = tk.Label(self.room_tree, text='還沒有房間資料\n先請房主建好房間，再讓風夜進房。',
                                   bg=WELL, fg=MUTED, font=(self.face, 13), justify='center')
        self.room_empty.place(relx=.5, rely=.5, anchor='center')
        # 2026-10-22：Hub 自己的 collector 不是唯一真相——直接讀本機實況（進程／席位／補丁回執／D8）
        self.live_label = tk.Label(box, bg=DAMASK, fg=MUTED, anchor='w', text='')
        self.live_label.pack(fill='x', padx=14, pady=(0, 8))
        self.root.after(1500, self._refresh_live_state)

        # 2026-10-22：舊 collector 那一塊（開局標準 x/5、不在線上…）會與本機實況矛盾，收起來。
        # 要看真實狀態就看上面那行「✅ 本機實況：…」。
        self.room_status = tk.Label(box, bg=DAMASK, fg=MUTED, anchor='w', justify='left', wraplength=1080)
        self.room_channel = tk.Label(box, bg=WELL, fg=INK, anchor='w', justify='left', wraplength=1080,
                                     font=(self.face, 12), padx=14, pady=12)
        self._legacy_status_hidden = True
        self.room_receipt = tk.Label(box, text='',
                                     bg=DAMASK, fg=MUTED, anchor='w', justify='left', wraplength=1080)
        self.room_receipt.pack(fill='x', padx=14, pady=(0, 12))

    def _saved_start_faction(self):
        path = Path.home() / 'sgi-fengye-lab/shadow/start-faction.json'
        names = {0: '丁滿', 1: '風雲', 5: '空位旁觀'}
        try:
            slot = int(json.loads(path.read_text(encoding='utf-8')).get('slot'))
        except (OSError, ValueError, TypeError):
            slot = 5
        return names.get(slot, '空位旁觀')

    def apply_start_faction(self):
        slots = {'丁滿': 0, '風雲': 1, '空位旁觀': 5}
        name = self.start_faction.get()
        slot = slots.get(name)
        if slot is None:
            self.lab_label.configure(text='請先選擇起始勢力：丁滿、風雲或空位旁觀。')
            return
        path = Path.home() / 'sgi-fengye-lab/shadow/start-faction.json'
        path.write_text(json.dumps({'slot': slot, 'name': name}, ensure_ascii=False), encoding='utf-8')
        self.lab_label.configure(text='正在把風夜切到「%s」…' % name)

        def work():
            script = Path.home() / 'sgi-fengye-lab/shadow/shadow_force.sh'
            try:
                result = subprocess.run(['bash', str(script), 'switch', str(slot)],
                                        cwd=str(script.parent), capture_output=True, text=True, timeout=40)
                ok = result.returncode == 0 and ('"requested": %d' % slot) in (result.stdout or '')
            except (OSError, subprocess.TimeoutExpired) as error:
                result = None
                ok = False
                err = str(error)
            else:
                err = (result.stderr or result.stdout or '')[-180:]

            def show():
                if ok:
                    self.lab_label.configure(text='起始勢力已設為「%s」。按「開始」後第一輪就用這個席位。' % name)
                else:
                    self.lab_label.configure(text='起始勢力沒切成：' + err.replace('\n', ' ')[:180])
            self.root.after(0, show)

        threading.Thread(target=work, daemon=True, name='fengye-start-faction').start()

    def _toggle_probe_layer(self):
        """0.2.22：探針層默認收起（日常只用帶客戶端的流程）；要查房等再展開。"""
        self.probe_shown = not getattr(self, 'probe_shown', False)
        if self.probe_shown:
            self.probe_box.pack(fill='x', before=self._lab_row)
        else:
            self.probe_box.pack_forget()
        self.probe_toggle.configure(text=('收起手動設定' if self.probe_shown else '手動進房設定'))

    def join_selected_room(self):
        if self._protocol_session_alive():
            ids = self.room_tree.selection()
            row = self.room_rows.get(ids[0]) if ids else None
            name = (row or {}).get('name') or (getattr(self, '_sticky_rooms', None) or [''])[0]
            if not name:
                self.room_receipt.configure(text='請先按「搜索房間」，再點一個房間列。')
                return
            room = str(name).split('[')[0].strip() or str(name)
            lab = self._lab_root()
            self._lab_async('進入房間並武裝（協議會話，不重新登入）',
                            'cd {} && bash sticky/sticky.sh join {} && bash sticky/sticky.sh arm'
                            .format(shlex.quote(str(lab)), shlex.quote(room)),
                            timeout=420)
            return
        ids = self.room_tree.selection()
        row = self.room_rows.get(ids[0]) if ids else None
        if row is None and len(self.room_rows) == 1:
            row = next(iter(self.room_rows.values()))  # 只有一個房間：未選取也可直接進入
        if row is None:
            self.room_receipt.configure(text='請先在房間列表點選一個房間列，再按「進入所選房間」。')
            return
        try:
            name = nickname(self.room_nickname.get())
        except ValueError as error:
            self.room_receipt.configure(text=plain_error(error))
            return
        self.room_action({'op': 'join', 'room_id': row['id'], 'nickname': name, 'quick': True})

    def register_ghost(self):
        state = self.rooms.state
        if not (state.get('fresh') and state.get('connected')):
            return
        if not messagebox.askokcancel('風夜報到',
                                      '讓風夜在房間名單報到（只送一次）。\n'
                                      '名單會短暫出現風夜的名字；失敗不重試。確認執行？', parent=self.root):
            return
        self.room_action({'op': 'register'})

    def withdraw_ghost(self):
        if self._protocol_session_alive():
            lab = self._lab_root()
            if not messagebox.askokcancel(
                    '風夜藏身（協議會話）',
                    '對目前這局的遊戲進程打補丁＋送一次 D8 摘席（不重新登入）。\n'
                    '請在房主按「開始」之前完成。確定執行？', parent=self.root):
                return
            self._lab_async('讓風夜藏好（協議會話）',
                            'cd {} && bash sticky/sticky.sh arm'.format(shlex.quote(str(lab))),
                            timeout=300)
            return
        state = self.rooms.state
        if not (state.get('fresh') and state.get('connected')):
            return
        if self._ghost_hall_alive():
            lab = self._lab_root()
            if not messagebox.askokcancel(
                    '風夜藏身（大廳不動）',
                    '對目前這局的遊戲進程打補丁＋送一次 D8 藏身（不重啟大廳）。\n'
                    '請在房主按「開始」之前完成。確定執行？', parent=self.root):
                return
            self._lab_async('讓風夜藏好（大廳不動）',
                            'cd {} && bash sticky/sticky.sh arm'.format(shlex.quote(str(lab))),
                            timeout=300)
            return
        if not messagebox.askokcancel('風夜藏身',
                                      '把風夜從名單中藏起來：這樣遊戲開局時不會等風夜，\n'
                                      '風夜可以一直暗中旁聽（名單會出現一行「風夜从游戏中退出了」）。\n'
                                      '請在遊戲按「開始」之前完成；只送一次、失敗不重試。確認執行？', parent=self.root):
            return
        self.room_action({'op': 'd8'})

    def _seat_table(self):
        """seat index -> (player name, faction name) from the current session snapshot."""
        view = getattr(self, 'view', None) or {}
        p = (view.get('p34') or {}) if isinstance(view, dict) else {}
        snapshots = p.get('snapshots') or {}
        block = snapshots.get('start') or snapshots.get('initial') or {}
        table = {}
        for row in block.get('rows') or []:
            try:
                seat = int(row.get('i'))
            except (TypeError, ValueError):
                continue
            name = row.get('name') or ('電腦' if row.get('state42') == 2 else '空席' if not row.get('id') else '未命名')
            table[seat] = (name, row.get('faction') or '—')
        return table

    def _update_slot_buttons(self, result):
        payload = force_payload(result)
        choices = force_choices(payload, self._seat_table()) if payload is not None else {}
        for table in (getattr(self, 'local_slot_buttons', None), getattr(self, 'fengye_slot_buttons', None)):
            for seat, button in (table or {}).items():
                button.configure(text=choices.get(seat, '等待玩家名單'),
                                 state='normal' if seat in choices else 'disabled')
                if seat in choices:
                    button.grid()
                else:
                    button.grid_remove()

    def _format_force(self, label, result):
        payload = force_payload(result)
        if payload is not None:
            return force_summary(payload, self._seat_table())
        return plain_error(result.get('stderr') or result.get('error'),
                           '還沒讀到本局玩家。請先進入對局，再按「更新可選玩家」。')

    def _sync_start_faction(self):
        """把「開局綁定」同步成 start-faction.json——任何進房路徑（一鍵／重新來過／
        手動進房）都會讀這個檔決定 7.5 步要占哪個席位。"""
        try:
            slot = self.bind_slot()
        except Exception:  # noqa: BLE001
            return
        if not isinstance(slot, int):
            return
        if slot == getattr(self, '_start_faction_slot', None):
            return
        try:
            self.command_service.write_start_faction(slot)
            self._start_faction_slot = slot
        except Exception:  # noqa: BLE001
            pass

    def _reconcile_seat(self, state):
        """開局前如果風夜不在綁定的席位，自動拉回去（每 20 秒檢查一次）。

        2026-10-21：實測「一鍵重啟」走的是實驗室腳本，Hub 的完成回呼不會被觸發，
        所以改用週期性校正，不論哪條路徑進房都會被綁到指定玩家。
        """
        self._refresh_actual_slot()
        self._refresh_sync_check()
        self._refresh_wire()
        ready = bool(state.get('connected') and state.get('ghost_withdrawn'))
        if ready and not getattr(self, '_recon_ready', False):
            self._recon_ready = True
            self._recon_at = 0          # 剛就緒：立刻校正一次，不等節流
        if not ready:
            self._recon_ready = False
        if time.time() - getattr(self, '_recon_at', 0) < 1 or getattr(self, '_recon_busy', False):
            return
        if not state.get('connected'):
            return
        if state.get('phase') == 'match':
            return
        if getattr(self, '_recon_busy', False) and time.time() - getattr(self, '_recon_busy_at', 0) > 60:
            self._recon_busy = False          # 卡住的執行緒不要永久鎖住校正
        slot = self.bind_slot()
        if slot is None:
            return
        self._recon_at = time.time()
        self._recon_busy = True
        self._recon_busy_at = time.time()

        def work():
            try:
                result = self.command_service.reconcile_seat(slot)
            except Exception as error:  # noqa: BLE001
                result = {'ok': False, 'error': str(error)}
            self.root.after(0, lambda: self._recon_done(result, slot))

        threading.Thread(target=work, daemon=True, name='seat-reconcile').start()

    def _refresh_sync_check(self):
        """每 20 秒比對風夜與本機真實玩家的回合座標（只讀）。"""
        if time.time() - getattr(self, '_sync_at', 0) < 20 or getattr(self, '_sync_busy', False):
            return
        self._sync_at = time.time()
        self._sync_busy = True

        def work():
            try:
                data = self.command_service.sync_check()
            except Exception as error:  # noqa: BLE001
                data = {'ok': None, 'note': str(error)}
            self.root.after(0, lambda: self._sync_done(data))

        threading.Thread(target=work, daemon=True, name='sync-check').start()

    def _refresh_wire(self):
        """風夜自己的收包心跳（陌生人局唯一的「有沒有在動」依據）。"""
        try:
            info = self.command_service.wire_health()
        except Exception:  # noqa: BLE001
            return
        label = getattr(self, 'wire_label', None)
        if label is None or not info.get('ok'):
            return
        now = time.time()
        count = info.get('received')
        prev = getattr(self, '_wire_prev', None)
        self._wire_prev = (now, count)
        if not info.get('connected'):
            self._wire_last_at = None
            label.configure(text='網線：風夜目前沒連線（%s）' % (info.get('run') or ''), fg=MUTED)
            return
        if not isinstance(count, int):
            label.configure(text='網線：讀不到收包數（phase=%s）' % info.get('phase'), fg=MUTED)
            return
        if prev and isinstance(prev[1], int) and count > prev[1]:
            self._wire_last_at = now
            label.configure(text='網線：最近 %.0f 秒收到 %d 筆（累計 %d）'
                                 % (now - prev[0], count - prev[1], count), fg=MUTED)
            return
        last = getattr(self, '_wire_last_at', None) or getattr(self, '_wire_started', now)
        self._wire_started = last
        silent = now - last
        if silent >= self.WIRE_SILENCE:
            label.configure(
                text='⚠️ 風夜已 %.0f 秒沒收到回合資料（連錯兩輪）→ 判定掉線' % silent, fg=WARN)
        elif silent >= self.WIRE_WARN:
            label.configure(text='網線：已靜默 %.0f 秒（累計 %d，phase=%s）'
                                 % (silent, count, info.get('phase')), fg=WARN)
        else:
            label.configure(text='網線：已連線，累計 %d 筆（phase=%s）'
                                 % (count, info.get('phase')), fg=MUTED)

    def _sync_done(self, data):
        self._sync_busy = False
        self.sync_data = data or {}
        label = getattr(self, 'sync_label', None)
        if label is None:
            return
        shadow = (data or {}).get('shadow') or {}
        reference = (data or {}).get('reference') or {}
        season_names = '春夏秋冬'

        def when(state):
            season = state.get('season')
            year = state.get('year')
            if not isinstance(season, int):
                return '?'
            name = season_names[season] if 0 <= season < 4 else '季%d' % season
            return '%s年%s' % (year, name) if isinstance(year, int) else name

        if data.get('ok') is True:
            label.configure(text='回合同步：✓ 風夜與玩家同步（%s）' % when(shadow), fg='#2e7d32')
        elif data.get('ok') is False:
            label.configure(
                text='回合同步：⚠️ 落後 %s 季（風夜 %s ｜ 玩家 %s）——主機可能已無用'
                     % (data.get('lag_seasons'), when(shadow), when(reference)), fg=WARN)
        else:
            label.configure(text='回合同步：%s' % (data.get('note') or '讀不到'),
                            fg=MUTED)

    def _refresh_actual_slot(self):
        """約 0.4 秒看一次 slotkeep 寫下的席位，不開 Wine。"""
        if time.time() - getattr(self, '_slot_at', 0) < 0.4:
            return
        self._slot_at = time.time()
        try:
            actual = self.command_service.applied_slot()
        except Exception:  # noqa: BLE001
            return
        if isinstance(actual, int) and actual != getattr(self, '_actual_slot', None):
            self._actual_slot = actual
            self.after_actual_slot()

    def after_actual_slot(self):
        """真實席位變了就重畫狀態面板。"""
        try:
            self.status_signature = None
            current = getattr(self.source, 'view', None)
            if isinstance(current, dict):
                self.render_status_panel(current)
        except Exception:  # noqa: BLE001
            pass

    def _recon_done(self, result, slot):
        self._recon_busy = False
        if isinstance(result, dict):
            actual = result.get('actual')
            if isinstance(actual, int):
                self._actual_slot = actual
            elif result.get('ok'):
                self._actual_slot = result.get('slot')
        if isinstance(result, dict) and result.get('changed'):
            if result.get('ok'):
                self.pre_seat_label.configure(text='已自動綁定到 slot %d' % slot)
            else:
                self.pre_seat_label.configure(
                    text='自動綁定失敗：%s' % (result.get('error') or result.get('note')))

    def _render_force_switch(self, players):
        """「切換速鍵」：無勢力 ＋ 每個玩家一家，按了立刻切風夜的席位。"""
        row = getattr(self, 'force_switch_row', None)
        if row is None:
            return
        for child in row.winfo_children():
            child.destroy()
        tk.Button(row, text='無勢力', bg=BG,
                  command=lambda: self._switch_seat(5, '無勢力')).pack(side='left')
        seen = set()
        for player in players or []:
            slot = player.get('slot')
            name = player.get('name')
            if not isinstance(slot, int) or slot in seen:
                continue
            seen.add(slot)
            tk.Button(row, text='%s' % name, bg=BG,
                      command=lambda s=slot, n=name: self._switch_seat(s, n)).pack(side='left', padx=4)

    def _switch_seat(self, slot, name=''):
        self.pre_seat_label.configure(text='切換到 %s（slot %d）…' % (name or 'slot', slot))

        def work():
            try:
                result = self.command_service.switch_ghost_seat(slot)
            except Exception as error:  # noqa: BLE001
                result = {'ok': False, 'error': str(error)}

            def show():
                if isinstance(result, dict) and result.get('ok'):
                    self.pre_seat_label.configure(
                        text='已切到 %s（slot %d）' % (name or 'slot', slot))
                else:
                    self.pre_seat_label.configure(
                        text='切換失敗：%s' % ((result or {}).get('error') if isinstance(result, dict) else result))
            self.root.after(0, show)

        threading.Thread(target=work, daemon=True, name='seat-switch').start()

    def _load_account(self):
        try:
            data = self.command_service.read_credentials()
        except Exception:  # noqa: BLE001
            data = {'ok': False}
        if data.get('ok'):
            self.account_user.set(data.get('username') or '')
            self.account_pass.set(data.get('password') or '')
            self.account_hint.configure(text='目前：%s' % data.get('username'))

    def _save_account(self):
        try:
            result = self.command_service.write_credentials(
                self.account_user.get(), self.account_pass.get())
        except Exception as error:  # noqa: BLE001
            result = {'ok': False, 'error': str(error)}
        if result.get('ok'):
            self.account_hint.configure(text='已儲存：%s（下次一鍵生效）' % result.get('username'))
        else:
            self.account_hint.configure(text='儲存失敗：%s' % (result.get('error') or '未知'))

    def remember_nickname(self):
        """把目前輸入的偽名記進本機偽名庫，並更新下拉選單。"""
        name = (self.room_nickname.get() or '').strip()
        try:
            result = self.command_service.remember_name(name)
        except Exception as error:  # noqa: BLE001
            result = {'ok': False, 'error': str(error)}
        if result.get('ok'):
            try:
                names = self.command_service.read_names().get('names') or []
                self.room_nick_combo.configure(values=names)
            except Exception:  # noqa: BLE001
                pass
            self.room_receipt.configure(text='已記住偽名：%s（下次直接從下拉選）' % result.get('name'))
        else:
            self.room_receipt.configure(text='記不住：%s' % (result.get('error') or '未知'))

    def _refresh_room_choices(self):
        """背景抓即時房間表，回主執行緒更新下拉（Tk 只能在主執行緒動 widget）。"""
        def work():
            try:
                data = self.command_service.live_rooms()
            except Exception as error:  # noqa: BLE001
                data = {'ok': False, 'error': str(error), 'rows': []}
            try:
                self.root.after(0, lambda: self._apply_room_choices(data))
            except Exception:  # noqa: BLE001
                pass

        try:
            import threading
            threading.Thread(target=work, daemon=True, name='room-feed').start()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.root.after(20000, self._refresh_room_choices)
        except Exception:  # noqa: BLE001
            pass

    def _apply_room_choices(self, data):
        """把抓到的房間表套進下拉（主執行緒）。"""
        rows = (data or {}).get('rows') or []
        choices = []
        self._room_choices = []
        for row in rows:
            line = ('多线%d' % row['line']) if row.get('line') else '?'
            choices.append('%s · %s · %s · %s/%s' % (
                line, row.get('host') or '?', row.get('virtual_ip') or row.get('room_id'),
                row.get('current'), row.get('maximum')))
            self._room_choices.append(row)
        try:
            import pathlib as _pl
            _pl.Path(__file__).resolve().parent.joinpath('data', 'room-feed.log').open(
                'a', encoding='utf-8').write(
                '%s ok=%s rows=%d choices=%s\n' % (time.strftime('%H:%M:%S'),
                                                    (data or {}).get('ok'), len(rows),
                                                    choices[:2]))
        except Exception:  # noqa: BLE001
            pass
        try:
            if choices:
                self.room_pick.configure(values=choices)
                # 預設選「目前線路上的那間房」，房間號/IP 直接填好（其餘仍可下拉換）。
                cur_line = (self.room_line.get() or '').strip()
                idx = next((i for i, row in enumerate(self._room_choices)
                            if row.get('line') and ('多线%d' % row['line']) == cur_line), None)
                if idx is None and len(choices) == 1:
                    idx = 0
                if idx is not None:
                    self.room_pick.current(idx)
                    if not getattr(self, '_oneclick_busy', False):
                        self.pick_room()
                else:
                    self.room_pick.set('選一間房（多线2／多线3）')
            else:
                err = (data or {}).get('error') or '監控沒有回報房間'
                self.room_pick.configure(values=['（房間表讀取失敗：%s）' % str(err)[:36]])
                self.room_pick.current(0)
                self.oneclick_hint.configure(text='即時房間表讀取失敗：%s' % str(err)[:80])
        except Exception:  # noqa: BLE001
            pass

    def pick_room(self):
        """從下拉選一間房：自動填線路與房間號/IP。"""
        idx = self.room_pick.current()
        if not (0 <= idx < len(self._room_choices)):
            return
        row = self._room_choices[idx]
        try:
            if row.get('line'):
                self.room_line.set('多线%d' % row['line'])
            if row.get('virtual_ip'):
                self.room_target.set(row['virtual_ip'])
        except Exception:  # noqa: BLE001
            pass
        self.oneclick_hint.configure(
            text='已選 %s（房主 %s，%s/%s）→ 按「一鍵登入」' % (
                row.get('virtual_ip') or row.get('room_id'), row.get('host') or '?',
                row.get('current'), row.get('maximum')))

    def _alias_name(self):
        """目前要顯示的名字（偽名庫的 active；沒有就用『幽靈』）。"""
        try:
            name = (self.command_service.active_name() or '').strip()
        except Exception:  # noqa: BLE001
            name = ''
        return name or '幽靈'

    def _live_snapshot(self):
        import json as _json
        import subprocess as _sp
        import os as _os
        out = {}
        try:
            pids = _sp.run(['pgrep', '-f', 'SANPK.exe'], capture_output=True, text=True).stdout.split()
            mine = []
            for pid in pids:
                lsof = _sp.run(['lsof', '-p', pid], capture_output=True, text=True, timeout=8).stdout
                if 'prefix-fengye-shadow' in lsof:
                    mine.append(pid)
            out['online'] = bool(mine)
            out['pids'] = mine
        except Exception:  # noqa: BLE001
            out['online'] = False
        lab = _os.path.expanduser('~/sgi-fengye-lab/shadow')
        try:
            receipt = _json.load(open(_os.path.join(lab, 'patch-receipt.json'), encoding='utf-8'))
            out['patch'] = receipt
        except Exception:  # noqa: BLE001
            out['patch'] = None
        try:
            st = _os.stat(_os.path.join(lab, 'shadow_d8_receipt.bin'))
            out['d8_wall'] = time.strftime('%H:%M', time.localtime(st.st_mtime))
        except Exception:  # noqa: BLE001
            out['d8_wall'] = None
        try:
            seat = _sp.run(['/bin/bash', '-lc', 'bash ~/sgi-fengye-lab/shadow/shadow_force.sh read'],
                           capture_output=True, text=True, timeout=25).stdout.strip().splitlines()
            line = next((l for l in reversed(seat) if l.startswith('{')), '')
            out['seat'] = _json.loads(line) if line else None
        except Exception:  # noqa: BLE001
            out['seat'] = None
        # 2026-10-22：接上「全知情報」資料源——讀當前 active 會話的 status.json 與封包數
        try:
            home = _os.path.expanduser('~/sgi-fengye-lab/fengye-hub-session')
            active = _json.load(open(_os.path.join(home, 'active.json'), encoding='utf-8'))
            sess = active.get('directory') or ''
            st = _json.load(open(_os.path.join(sess, 'status.json'), encoding='utf-8'))
            link = st.get('link') or {}
            scene = st.get('scene') or {}
            seat2 = st.get('seat') or {}
            patches2 = st.get('patches') or {}
            opening = patches2.get('opening') or {}
            guard = patches2.get('guard') or {}
            out['collector'] = {
                'session': _os.path.basename(sess),
                'connected': link.get('connected'),
                'sync': link.get('sync'),
                'tx': link.get('tx'),
                'in_map': scene.get('in_map'),
                'phase': scene.get('phase'),
                'slot': seat2.get('slot'),
                'force': seat2.get('force'),
                'fog_original': st.get('fog_original'),
                'patch_ok': (opening.get('ok') or 0) + (guard.get('ok') or 0),
                'patch_total': (opening.get('total') or 0) + (guard.get('total') or 0),
            }
            pk = _os.path.join(sess, 'packets.jsonl')
            out['packets'] = sum(1 for _ in open(pk, 'rb')) if _os.path.exists(pk) else 0
        except Exception:  # noqa: BLE001
            out['collector'] = None
            out['packets'] = None
        return out

    def _refresh_live_state(self):
        import threading

        def work():
            snap = self._live_snapshot()
            online = '在線' if snap.get('online') else '不在線'
            pids = ','.join(snap.get('pids') or []) or '—'
            patch = snap.get('patch') or {}
            seat = snap.get('seat') or {}
            seat_now = seat.get('slot_now')
            forces = seat.get('slot_forces') or {}
            mine_force = forces.get(str(seat_now)) if seat_now is not None else None
            bits = ['客戶端 %s（pid %s）' % (online, pids)]
            if patch:
                bits.append('補丁 pid %s ｜ guard %s ｜ D8 %s' % (
                    patch.get('pid') or '—',
                    '✓' if patch.get('myforce_guard') else '✗',
                    '✓' if patch.get('d8_hidden') else '✗'))
            if seat_now is not None:
                bits.append('席位 slot %s（勢力 %s）' % (seat_now, mine_force if mine_force not in (None, -1) else '未分配'))
            if snap.get('d8_wall'):
                bits.append('D8 回執 %s' % snap['d8_wall'])
            col = snap.get('collector') or {}
            if col:
                bits.append('全知情報 %s：連線 %s ｜ 場 %s／phase %s ｜ 席位 %s→勢力 %s ｜ 補丁 %s/%s ｜ 迷霧%s ｜ 封包 %s' % (
                    col.get('session') or '—',
                    '✓' if col.get('connected') else '✗',
                    '地圖' if col.get('in_map') else '非地圖',
                    col.get('phase'),
                    col.get('slot'), col.get('force'),
                    col.get('patch_ok'), col.get('patch_total'),
                    '原版' if col.get('fog_original') else '已去霧',
                    snap.get('packets') if snap.get('packets') is not None else '—'))
            text = '本機實況：' + ' ｜ '.join(bits)
            colour = '#164d51' if snap.get('online') else MUTED

            self._live_online = bool(snap.get('online'))
            self._live_text = text

            def apply():
                self.live_label.configure(text=text, fg=colour)
                # 舊 collector 的橫幅會說「尚未進房／不在線上」——用本機實況蓋掉，畫面才不會說謊
                try:
                    online_txt = '風夜在線' if snap.get('online') else '風夜不在線'
                    self.console_state.configure(text='%s ｜ %s' % (online_txt, text))
                except Exception:  # noqa: BLE001
                    pass
            self.root.after(0, apply)

        threading.Thread(target=work, daemon=True).start()
        self.root.after(5000, self._refresh_live_state)

    def _refresh_identity(self):
        """把帳號庫／偽名庫的目前值補進下拉，並在畫面上寫清楚「現在用哪個」。"""
        try:
            acc = self.command_service.read_accounts()
            accounts = acc.get('accounts') or []
            active = acc.get('active') or ''
            names = [a.get('username') for a in accounts if a.get('username')]
            try:
                self.account_combo.configure(values=names)
                if active:
                    self.account_choice.set(active)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            accounts, active, names = [], '', []
        try:
            name = self.command_service.active_name() or ''
        except Exception:  # noqa: BLE001
            name = ''
        if name:
            try:
                self.lab_nickname.set(name)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.identity_label.configure(
                text='目前偽名：%s　｜　目前帳號：%s　（在「帳號／偽名設定」裡切換）'
                     % (name or '（未設定）', active or (names[0] if names else '（未設定）')))
        except Exception:  # noqa: BLE001
            pass
        try:
            self.root.after(15000, self._refresh_identity)
        except Exception:  # noqa: BLE001
            pass

    def open_settings_dialog(self):
        """後台設定：帳號庫／偽名庫的新增、刪除、切換。"""
        try:
            from settings_dialog import open_settings
            open_settings(self.root, self.command_service, on_change=self._after_settings)
        except Exception as error:  # noqa: BLE001
            self.room_receipt.configure(text='設定視窗開不起來：%s' % error)

    def _after_settings(self):
        """設定改完：主頁只跟著更新「目前偽名」。"""
        try:
            name = self.command_service.active_name() or ''
        except Exception:  # noqa: BLE001
            name = ''
        try:
            self.lab_nickname.set(name)
        except Exception:  # noqa: BLE001
            pass
        if name:
            self.room_receipt.configure(text='目前偽名：%s' % name)
        try:
            self._refresh_identity()
        except Exception:  # noqa: BLE001
            pass

    def remember_lab_nickname(self):
        """把「進房暱稱」記進本機偽名庫，下拉立刻可用。"""
        name = (self.lab_nickname.get() or '').strip()
        try:
            result = self.command_service.remember_name(name)
        except Exception as error:  # noqa: BLE001
            result = {'ok': False, 'error': str(error)}
        if result.get('ok'):
            try:
                names = self.command_service.read_names().get('names') or []
                self.lab_nick_combo.configure(values=names)
            except Exception:  # noqa: BLE001
                pass
            self.room_receipt.configure(text='已記住偽名：%s' % result.get('name'))
        else:
            self.room_receipt.configure(text='記不住：%s' % (result.get('error') or '未知'))

    def switch_account(self):
        """切換登入帳號庫裡的帳號（會寫 fengye-credentials.json，一鍵時生效）。"""
        wanted = (self.account_choice.get() or '').strip()
        if not wanted:
            return
        try:
            result = self.command_service.use_account(wanted)
        except Exception as error:  # noqa: BLE001
            result = {'ok': False, 'error': str(error)}
        if result.get('ok'):
            data = self.command_service.read_credentials()
            self.account_user.set(data.get('username') or wanted)
            self.account_pass.set(data.get('password') or '')
            self.account_hint.configure(text='已切換：%s' % wanted)
        else:
            self.account_hint.configure(text='切換失敗：%s' % (result.get('error') or '未知'))

    def _refresh_bind_choices(self, state):
        """把「開局綁定」的選項換成房間裡的玩家名字（每 15 秒一次）。"""
        if time.time() - getattr(self, '_bind_at', 0) < 15 or getattr(self, '_bind_busy', False):
            return
        if not (state.get('connected') or state.get('fresh')):
            return
        self._bind_at = time.time()
        self._bind_busy = True
        me = (self.room_nickname.get() or '').strip()

        def work():
            try:
                data = self.command_service.room_players()
            except Exception as error:  # noqa: BLE001
                data = {'ok': False, 'players': [], 'error': str(error)}
            self.root.after(0, lambda: self._apply_bind_choices(data, me))

        threading.Thread(target=work, daemon=True, name='bind-choices').start()

    def _apply_bind_choices(self, data, me):
        self._bind_busy = False
        players = [p for p in (data or {}).get('players') or []
                   if p.get('name') and p['name'] != me]
        if not players:
            return
        try:
            self._render_force_switch(players)
        except Exception:  # noqa: BLE001
            pass
        unique = {}
        for player in players:
            unique.setdefault(player['slot'], player['name'])
        values = ['無勢力（不綁定）'] + ['%s（slot %d）' % (name, slot)
                                       for slot, name in sorted(unique.items())]
        current = self.bind_choice.get()
        self.bind_box.configure(values=values)
        if current in values:
            return
        import re as _re
        found = _re.search(r'slot\s*(\d)', current or '')
        slot = int(found.group(1)) if found else 0
        pick = next((v for v in values[1:] if v.endswith('slot %d）' % slot)), values[1])
        self.bind_choice.set(pick)

    def _maybe_auto_seat(self, state):
        """進房並藏好後，自動把風夜坐到所選席位（開局前上身）。

        2026-10-21 使用者要求：不要再手動按「套用」，把它當默認補丁。
        """
        if self.retry is not None or self.room_busy or self.room_pending:
            return
        if not (state.get('fresh') and state.get('connected')
                and state.get('ghost_withdrawn')):
            return
        key = (state.get('room_name') or state.get('room') or state.get('room_id')
               or state.get('started_at') or 'room')
        if getattr(self, 'auto_seat_done', None) == key:
            return
        self.auto_seat_done = key
        self._auto_seat_now()

        def work():
            try:
                result = self.command_service.switch_ghost_seat(slot)
            except Exception as error:  # noqa: BLE001
                result = {'ok': False, 'error': str(error)}

            def show():
                if isinstance(result, dict) and result.get('ok'):
                    self.pre_seat_label.configure(
                        text='已自動上身 slot %d（開局前生效）；按遊戲的「開始」即可。' % slot)
                else:
                    self.pre_seat_label.configure(
                        text='自動上身失敗：%s（可手動按套用）' %
                             ((result or {}).get('error') if isinstance(result, dict) else result))
            self.root.after(0, show)

        threading.Thread(target=work, daemon=True, name='auto-seat').start()

    def bind_slot(self):
        """回傳要綁定的 slot；選「無勢力」時回 None。"""
        choice = (self.bind_choice.get() or '').strip()
        if choice.startswith('無勢力'):
            return None
        import re as _re
        found = _re.search(r'slot\s*(\d)', choice)
        if found:
            return int(found.group(1))
        try:
            return int(self.pre_seat_value.get())
        except (TypeError, ValueError):
            return 0

    def _auto_seat_now(self):
        """立刻把風夜綁進所選席位（開局前上身）。"""
        slot = self.bind_slot()
        if slot is None:
            self.pre_seat_label.configure(text='開局綁定：無勢力（不綁定）')
            return
        self.pre_seat_value.set(str(slot))
        self.pre_seat_label.configure(
            text='進房後自動上身：切到 slot %d…' % slot)

        def work():
            try:
                result = self.command_service.switch_ghost_seat(slot)
            except Exception as error:  # noqa: BLE001
                result = {'ok': False, 'error': str(error)}

            def show():
                if isinstance(result, dict) and result.get('ok'):
                    self.pre_seat_label.configure(
                        text='已自動上身 slot %d（開局前生效）；按遊戲的「開始」即可。' % slot)
                else:
                    self.pre_seat_label.configure(
                        text='自動上身失敗：%s（可手動按套用）' %
                             ((result or {}).get('error') if isinstance(result, dict) else result))
            self.root.after(0, show)

        threading.Thread(target=work, daemon=True, name='auto-seat').start()

    def _auto_seat_now(self):
        """立刻把風夜坐進所選席位（開局前上身）。"""
        try:
            slot = int(self.pre_seat_value.get())
        except (TypeError, ValueError):
            slot = 0
        self.pre_seat_label.configure(
            text='進房後自動上身：切到 slot %d…' % slot)

        def work():
            try:
                result = self.command_service.switch_ghost_seat(slot)
            except Exception as error:  # noqa: BLE001
                result = {'ok': False, 'error': str(error)}

            def show():
                if isinstance(result, dict) and result.get('ok'):
                    self.pre_seat_label.configure(
                        text='已自動上身 slot %d（開局前生效）；按遊戲的「開始」即可。' % slot)
                else:
                    self.pre_seat_label.configure(
                        text='自動上身失敗：%s（可手動按套用）' %
                             ((result or {}).get('error') if isinstance(result, dict) else result))
            self.root.after(0, show)

        threading.Thread(target=work, daemon=True, name='auto-seat').start()

    def _lab_async(self, label, script, timeout=360):
        def work():
            try:
                result = lab_remote(self.source.sources.host, script, timeout=timeout)
            except Exception as error:
                result = {'rc': -1, 'stderr': str(error)}
            text = lab_result(label, result)

            def show():
                display = text
                if label == '查看風夜狀態' and result.get('rc') == 0:
                    display = '\n'.join(room_summary(self.rooms.state))
                self.lab_label.configure(text=display[:2600])
            self.root.after(0, show)

        self.lab_label.configure(text=label + '…執行中（可能需數分鐘）')
        threading.Thread(target=work, daemon=True, name='fengye-lab').start()

    def _lab_async_receipt(self, label, script, timeout=900):
        """跟 _lab_async 一樣跑本機 lab，但把進度與結果寫在「一鍵」那行（看得到）。"""
        try:
            self.room_receipt.configure(text='%s…執行中（含登入/進房/補丁，約 1–4 分鐘）' % label)
        except Exception:  # noqa: BLE001
            pass

        def work():
            # 2026-10-22：這些一鍵腳本都在「本機」lab，改成本機執行（原本走 SSH 遠端會 No such file）
            try:
                import subprocess as _sp
                cp = _sp.run(['/bin/bash', '-lc', script], capture_output=True, text=True, timeout=timeout)
                result = {'rc': cp.returncode, 'stdout': cp.stdout, 'stderr': cp.stderr}
            except Exception as error:  # noqa: BLE001
                result = {'rc': -1, 'stdout': '', 'stderr': str(error)}
            out = ((result.get('stdout') or '') + (result.get('stderr') or '')).strip()
            tail = [ln for ln in out.splitlines() if ln.strip()][-6:]
            refused = next((ln for ln in out.splitlines() if '参加游戏区域失败' in ln or '线路正在繁忙' in ln), '')
            if result.get('rc') == 0:
                head = '一鍵完成'
            elif refused:
                head = '被房主端拒絕'
            else:
                head = '一鍵失敗 rc=%s' % result.get('rc')
            text = head + '\n' + '\n'.join(tail)[-1200:]

            def show():
                try:
                    self.room_receipt.configure(text=text)
                except Exception:  # noqa: BLE001
                    pass
                first = text.splitlines()[0] if text else ''
                bad = ('拒絕' in first) or ('失敗' in first)
                try:
                    self.oneclick_state.configure(
                        text=first[:80] + ('｜' + text.splitlines()[-1][:60] if len(text.splitlines()) > 1 else ''),
                        fg=('#a33b3b' if bad else '#164d51'))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._oneclick_busy = False
                    self.oneclick_btn.configure(state='normal')
                except Exception:  # noqa: BLE001
                    pass
            self.root.after(0, show)

        threading.Thread(target=work, daemon=True, name='fengye-oneclick').start()

    def _lab_run_json(self, script, on_done, timeout=90):
        """跑一支 lab 指令，解析輸出的 JSON，交給 on_done(payload, raw)。"""

        def work():
            try:
                result = lab_remote(self.source.sources.host, script, timeout=timeout)
            except Exception as error:  # noqa: BLE001
                result = {'rc': -1, 'stdout': '', 'stderr': str(error)}
            out = (result.get('stdout') or '') + (result.get('stderr') or '')
            payload = {}
            for raw in out.splitlines():
                raw = raw.strip()
                if raw.startswith('{'):
                    try:
                        payload = json.loads(raw)
                    except ValueError:
                        payload = {}
            self.root.after(0, lambda: on_done(payload, out))

        threading.Thread(target=work, daemon=True, name='fengye-lab-json').start()

    def _line_wanted(self):
        combo = getattr(self, 'ghost_line', None)
        return ((combo.get() if combo else '') or '多线3（备用）').strip()

    def _line_session(self):
        return ((getattr(self, '_line_state', None) or {}).get('session') or '').strip()

    def _line_needs_relogin(self):
        session = self._line_session()
        return bool(session) and session != self._line_wanted()

    def lab_line_refresh(self):
        """讀目前線路：風夜現在在哪條線／下次登入要用哪條線。"""
        lab = self._lab_root()
        script = 'cd {} && bash sticky/sticky.sh line'.format(shlex.quote(str(lab)))

        def done(payload, out):
            if not payload:
                self.line_status_label.configure(text='讀不到線路狀態（實驗室可能沒在線）')
                return
            self._line_state = payload
            session = payload.get('session') or '（沒登入）'
            configured = payload.get('configured') or '（沒設定）'
            wanted = self._line_wanted()
            if session != wanted and payload.get('session'):
                text = ('⚠ %s現在在 %s，你要的是 %s；按「讓幽靈進房」會重新登入換線'
                        % (session, wanted))
            else:
                text = '%s現在在 %s／下次登入：%s' % (self._alias_name(), session, configured)
            self.line_status_label.configure(text=text)

        self._lab_run_json(script, done, timeout=60)

    def lab_unblock(self):
        """清掉堆疊的「搜尋伺服器」彈窗，恢復遊戲選擇視窗（2026-10-21 卡住的原因）。"""
        lab = self._lab_root()
        script = 'cd {} && bash sticky/sticky.sh unblock'.format(shlex.quote(str(lab)))

        def done(payload, out):
            if payload.get('ok'):
                rooms = payload.get('rooms_after') or []
                self.lab_label.configure(text=(
                    '已解除：關掉 %s 個搜尋彈窗，遊戲選擇視窗%s。%s'
                    % (payload.get('drained') or 0,
                       '恢復可點' if payload.get('select_enabled') else '還是鎖著（可能沒開遊戲）',
                       ('\n房間：' + '、'.join(rooms)) if rooms else '')))
            else:
                self.lab_label.configure(text='解除失敗：%s' % (out[-400:] or '沒有輸出'))

        self.lab_label.configure(text='解除卡住…（清掉搜尋彈窗）')
        self._lab_run_json(script, done, timeout=120)

    def lab_search_rooms(self):
        """半自動①：借探針登入並搜房；搜完自動收線，把風夜帳號讓給武裝客戶端。

        2026-10-21：大廳已用風夜帳號登入時，這支探針等於同帳號重複登入，
        對面會看到上線／離線抖動——所以直接拒絕，改用客戶端自己的房間列表。
        """
        if self._ghost_hall_alive():
            self.lab_label.configure(text=(
                '大廳已在線：不要用探針搜房（同一支風夜帳號會重複登入）。\n'
                '請在大廳按「啟動遊戲」，遊戲裡的房間列表就是你要的房間清單。'))
            return
        if self._line_needs_relogin():
            self.lab_label.configure(text=(
                '風夜現在在 %s，你要找的是 %s 的房間。\n'
                '先按「讓風夜進房」換線（會重新登入一次），再回來搜索房間。'
                % (self._line_session(), self._line_wanted())))
            return
        lab = self._lab_root()
        script = 'cd {} && bash sticky/sticky.sh rooms'.format(shlex.quote(str(lab)))
        self.lab_label.configure(text='搜索房間…（讀客戶端自己的清單，不登入）')

        def work():
            try:
                res = lab_remote(self.source.sources.host, script, timeout=120)
                out = (res.get('stdout') or '') + (res.get('stderr') or '')
            except Exception as error:  # noqa: BLE001
                out = 'ERROR: %s' % error

            def show():
                items = []
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith('{') and '"items"' in line:
                        try:
                            items = json.loads(line).get('items') or []
                        except ValueError:
                            items = []
                items = [i for i in items if isinstance(i, str) and i.strip()]
                self._sticky_rooms = items
                rows = []
                for raw in items:
                    raw = raw.strip()
                    room = raw.split('[')[0].strip() or raw
                    host = ''
                    if '[' in raw and ']' in raw:
                        host = raw[raw.find('[') + 1:raw.rfind(']')].strip()
                    rows.append({'id': raw, 'name': room, 'host': host or '未知',
                                 'current': None, 'maximum': None})
                self.room_tree.delete(*self.room_tree.get_children())
                self.room_rows = {}
                for row in rows:
                    iid = self.room_tree.insert('', 'end', values=(
                        row['name'], row['host'], '— / —'))
                    self.room_rows[iid] = row
                stamp = time.strftime('%H:%M:%S')
                if rows:
                    self.room_empty.place_forget()
                    self.lab_label.configure(text='房間 %d 間（%s 讀取）：%s\n（點一列→「進入所選房間」；只有一間時自動選）'
                                             % (len(rows), stamp, '、'.join(r['name'] for r in rows)))
                else:
                    # 空房也要有話說：不是「什麼都沒顯示」。
                    self.room_empty.configure(text='這條線目前沒有房間（0 間）\n讀取時間 %s' % stamp)
                    self.room_empty.place(relx=.5, rely=.5, anchor='center')
                    self.lab_label.configure(text='房間 0 間（%s 讀取）：請房主先建好房間，再按一次「搜索房間」' % stamp)
            self.root.after(0, show)

        threading.Thread(target=work, daemon=True, name='sticky-rooms').start()

    def _lab_search_when_lobby(self, tries=0):
        state = self.rooms.state
        if state.get('phase') == 'lobby' and not state.get('connected') and not self.room_busy:
            self.room_action({'op': 'search'})
            self.root.after(1500, self._lab_release_probe)
        elif tries < 24 and not state.get('connected'):
            self.root.after(500, lambda: self._lab_search_when_lobby(tries + 1))
        else:
            self.lab_label.configure(text='還沒有房間資料：請確認房主已建房，再按「搜索房間」。')

    def _lab_release_probe(self, tries=0):
        """搜完就讓探針下線：風夜帳號讓給帶客戶端的武裝鏈。"""
        state = self.rooms.state
        if state.get('alive') and not state.get('connected'):
            self.room_action({'op': 'stop'})
            self.lab_label.configure(text='房間清單已更新；探針已下線，接下來可選房進入。')
        elif tries < 10:
            self.root.after(600, lambda: self._lab_release_probe(tries + 1))
        else:
            self.lab_label.configure(text='房間清單已更新；若探針仍佔用帳號，按「進入所選房間」時會先自動收線。')

    def lab_enter_selected(self):
        rows = list(self.room_rows.values())
        selected = self.room_tree.selection()
        room = self.room_rows.get(selected[0]) if selected else None
        if room is None and len(rows) == 1:
            room = rows[0]
        if room is None and getattr(self, '_sticky_rooms', None):
            # 2026-10-21：本機模式沒有探針會話，用「搜索房間」剛讀到的第一間。
            room = {'name': self._sticky_rooms[0]}
        if not room:
            self.lab_label.configure(text='請先按「搜索房間」，再在清單點選要進入的房間（只有一間時自動選）。')
            return
        raw = str(room.get('name') or '').strip()
        subset = raw.split('[')[0].strip() or raw
        nick = (self.lab_nickname.get() or '待秋至').strip() or '待秋至'
        alive = bool(self.rooms.state.get('alive'))
        if not messagebox.askokcancel(
                '進入所選房間？',
                '房間：{}\n暱稱：{}\n\n{}這會結束風夜先前連線，重新進房、藏身並開啟上帝視角；'
                '準備期間先別按「開始」。確定繼續？'.format(
                    raw or '（未命名）', nick,
                    '（會先讓探針下線釋放帳號）\n' if alive else ''),
                parent=self.root):
            return
        if self._ghost_hall_alive():
            self.lab_label.configure(text=(
                '大廳已在線，**不重啟**。請在大廳按「啟動遊戲」，用遊戲裡的房間列表選房；\n'
                '進房後按「讓風夜藏好」，採集器會自動接上。'))
            return
        if self._line_needs_relogin():
            self.lab_label.configure(text=(
                '風夜現在在 %s，你要進的是 %s 的房間。\n'
                '先按「讓風夜進房」換線（會重新登入一次），再回來進入房間。'
                % (self._line_session(), self._line_wanted())))
            return
        lab = self._lab_root()
        if getattr(self, '_sticky_rooms', None) or self._protocol_session_alive():
            cmd = ('cd {} && bash sticky/sticky.sh join {} && bash sticky/sticky.sh arm'
                   .format(shlex.quote(str(lab)), shlex.quote(subset)))
            self._lab_async('進入房間並武裝（大廳／登入都不重做）', cmd, timeout=420)
            return
        if alive:
            self.room_action({'op': 'stop'})
            self.root.after(1600, lambda: self._lab_arm(subset, nick))
        else:
            self._lab_arm(subset, nick)

    def _lab_root(self):
        """實驗室根目錄：真實局在本機 lab；舊遠端 lab 由 data/config.json 覆寫。"""
        try:
            cfg = json.loads((Path(__file__).resolve().parent / 'data' / 'config.json')
                             .read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cfg = {}
        return Path(cfg.get('lab_root') or (Path.home() / 'sgi-fengye-lab' / 'shadow')).expanduser()

    def _lab_arm(self, room_name=None, nickname=None):
        try:
            slot = self.bind_slot()
            if isinstance(slot, int):
                self.command_service.write_start_faction(slot)
        except Exception:  # noqa: BLE001
            pass
        env = ''
        if room_name:
            env += 'JOIN_NAME={} '.format(shlex.quote(room_name))
        if nickname:
            env += 'JOIN_NICKNAME={} '.format(shlex.quote(nickname))
        # 2026-10-21：把「開局綁定」直接交給進房腳本，一鍵結束時就已經坐在該席位，
        # 不用等 Hub 之後的校正（使用者常在腳本結束後幾秒就按開始）。
        try:
            slot = self.bind_slot()
        except Exception:  # noqa: BLE001
            slot = None
        if isinstance(slot, int):
            env += 'SEAT_SLOT={} SLOT={} '.format(slot, slot)
        lab = self._lab_root()
        if self._ghost_hall_alive():
            self.lab_label.configure(text=(
                '大廳已在線，**不重啟**（重啟會讓對面看到離線／上線）。\n'
                '請直接在遊戲大廳按「啟動遊戲」→ 用遊戲裡的房間列表進房→ 再按「讓風夜藏好」。\n'
                '採集器由 sticky watcher 自動接上，不用按一鍵。\n'
                '（大廳路線的線路由官方大廳決定，這裡的線路下拉只對協議路線有效。）'))
            return
        wanted = self._line_wanted()
        line_set = 'bash sticky/sticky.sh line set {}'.format(shlex.quote(wanted))
        if self._protocol_session_alive():
            if self._line_needs_relogin():
                if not messagebox.askokcancel(
                        '換線路？',
                        '風夜現在在 %s，你要進 %s。\n\n'
                        '換線路要重新登入一次（對面會看到一次離線／上線）。\n'
                        '確定繼續？' % (self._line_session(), wanted),
                        parent=self.root):
                    return
                self._lab_async(
                    '風夜進房（換線路，重新登入一次）',
                    'cd {} && {} && bash sticky/sticky.sh protocol-down && '
                    'bash sticky/sticky.sh protocol-up'.format(
                        shlex.quote(str(lab)), line_set),
                    timeout=420)
                return
            self._lab_async('風夜進房（自動選房，不再登入）',
                            'cd {} && bash sticky/sticky.sh autojoin'.format(shlex.quote(str(lab))),
                            timeout=600)
            return
        # 2026-10-21 使用者要求：一顆按鈕到底——必要時才登入一次，然後自動選房、
        # 進房、補丁、摘席，全部一條命令。
        self._lab_async('風夜進房（自動選房＝進房＋補丁＋摘席）',
                        'cd {} && {} && bash sticky/sticky.sh autojoin'.format(
                            shlex.quote(str(lab)), line_set),
                        timeout=900)

    def _ghost_hall_alive(self):
        """風夜的大廳（SANGUO.exe）是否還活著。

        2026-10-21：官方大廳登入後，任何「重啟客戶端」的流程都會在對面留下
        離線／上線兩次事件。大廳活著時一律不准走 arm_now 那條路。
        """
        now = time.time()
        cached = getattr(self, '_hall_cache', None)
        if cached and now - cached[0] < 5:
            return cached[1]
        alive = False
        try:
            lab = self._lab_root()
            out = subprocess.run(['bash', str(lab / 'sticky' / 'ghost_prefix.sh')],
                                 capture_output=True, text=True, timeout=10)
            prefix = (out.stdout or '').strip()
            bottle = Path(prefix).name if prefix else ''
            if bottle:
                for pid in subprocess.run(['pgrep', '-f', 'SANGUO\\.exe'],
                                          capture_output=True, text=True, timeout=5).stdout.split():
                    listing = subprocess.run(['lsof', '-p', pid], capture_output=True,
                                             text=True, timeout=5).stdout
                    if 'SGI-Wine/%s/drive_c/sgi' % bottle in listing:
                        alive = True
                        break
        except Exception:  # noqa: BLE001
            alive = False
        self._hall_cache = (now, alive)
        return alive

    def _protocol_session_alive(self):
        """協議 sticky 會話（launch_shadow_sticky.py）是否還活著。"""
        now = time.time()
        cached = getattr(self, '_proto_cache', None)
        if cached and now - cached[0] < 5:
            return cached[1]
        alive = False
        try:
            alive = subprocess.run(['pgrep', '-f', 'launch_shadow_sticky.py'],
                                   capture_output=True, text=True, timeout=5).returncode == 0
        except Exception:  # noqa: BLE001
            alive = False
        self._proto_cache = (now, alive)
        return alive

    def lab_arm(self):
        if not messagebox.askokcancel(
                '登入風夜（一鍵到底）？',
                '會做：必要時協議登入一次 → 自動選房（房主名單優先）→ 進房 → 補丁 → 摘席。\n'
                '已經在線的會話不會重登、不會退房重進。\n'
                '準備期間先別按「開始」。確定繼續？', parent=self.root):
            return
        self._lab_arm()

    def lab_stop(self):
        lab = self._lab_root()
        if self._ghost_hall_alive():
            if not messagebox.askokcancel(
                    '讓風夜下線？',
                    '風夜目前是用官方大廳登入的。\n'
                    '下線會關掉大廳（對面會看到一次離線）；之後要走協議登入（偽名、只登入一次）。\n'
                    '確定要下線？', parent=self.root):
                return
            self._lab_async('風夜下線（關大廳）',
                            'cd {} && bash sticky/sticky.sh hall-down'.format(shlex.quote(str(lab))),
                            timeout=120)
            return
        self._lab_async('讓風夜下線',
                        'cd {} && bash sticky/sticky.sh protocol-down'.format(shlex.quote(str(lab))),
                        timeout=90)

    _CLIENT_PREFIXES = {
        '丁满': 'prefix-dingman-local',
        '风云': 'prefix-sikarugir10',
        '風夜(小白)': 'prefix-fengye-shadow',
    }

    def _running_clients(self):
        out = {}
        try:
            pids = subprocess.run(['pgrep', '-f', 'SANPK.exe'], capture_output=True, text=True).stdout.split()
        except OSError:
            return out
        for pid in pids:
            try:
                lsof = subprocess.run(['lsof', '-p', pid], capture_output=True, text=True, timeout=10).stdout
            except (OSError, subprocess.TimeoutExpired):
                continue
            for name, pref in self._CLIENT_PREFIXES.items():
                if pref in lsof:
                    out.setdefault(name, []).append(pid)
        return out

    def open_end_client_dialog(self):
        win = tk.Toplevel(self.root)
        win.title('結束客戶端（大廳保留）')
        win.configure(bg=DAMASK)
        win.geometry('460x320')
        body = tk.Frame(win, bg=DAMASK)
        body.pack(fill='both', expand=True, padx=16, pady=12)
        tk.Label(body, text='勾選要結束的帳號（只關遊戲，大廳不動）', bg=DAMASK, fg=INK,
                 font=(self.face, 12, 'bold')).pack(anchor='w')
        holder = tk.Frame(body, bg=DAMASK)
        holder.pack(fill='x', pady=8)
        state = {}

        def refresh():
            for w in holder.winfo_children():
                w.destroy()
            state.clear()
            cur = self._running_clients()
            if not cur:
                tk.Label(holder, text='目前沒有執行中的客戶端', bg=DAMASK, fg=MUTED).pack(anchor='w')
                return
            for name, pids in sorted(cur.items()):
                var = tk.BooleanVar(value=True)
                state[name] = (var, pids)
                tk.Checkbutton(holder, text='%s（pid %s）' % (name, ', '.join(pids)),
                               variable=var, bg=DAMASK, fg=INK, selectcolor=DAMASK,
                               activebackground=DAMASK, activeforeground=INK).pack(anchor='w')

        def kill_selected(all_flag=False):
            killed = []
            for name, (var, pids) in state.items():
                if not all_flag and not var.get():
                    continue
                for pid in pids:
                    try:
                        os.kill(int(pid), 9)
                        killed.append('%s(%s)' % (name, pid))
                    except OSError:
                        pass
            messagebox.showinfo('結束客戶端', '已結束：\n' + ('\n'.join(killed) if killed else '（沒有選取）'),
                                parent=win)
            refresh()

        bar = tk.Frame(body, bg=DAMASK)
        bar.pack(fill='x')
        tk.Button(bar, text='↻ 重新整理', bg=BG, command=refresh).pack(side='left')
        tk.Button(bar, text='結束所選', bg='#f7e5e5', fg=WARN,
                  command=kill_selected).pack(side='left', padx=8)
        tk.Button(bar, text='全部結束', bg='#f7e5e5', fg=WARN,
                  command=lambda: kill_selected(True)).pack(side='left')
        tk.Button(bar, text='關閉', bg=BG, command=win.destroy).pack(side='right')
        refresh()

    def _refresh_auto_end(self):
        """每秒刷新「自動結束」狀態：有沒有在跑＋日誌最後一行。"""
        import subprocess as _sp

        def work():
            try:
                running = _sp.run(['pgrep', '-f', 'auto_end.sh'], capture_output=True, text=True).stdout.strip()
            except Exception:  # noqa: BLE001
                running = ''
            tail = ''
            try:
                log = os.path.expanduser('~/sgi-fengye-lab/shadow/logs/auto-end.log')
                lines = open(log, encoding='utf-8', errors='replace').read().strip().splitlines()
                tail = lines[-1] if lines else ''
            except Exception:  # noqa: BLE001
                tail = ''
            if running:
                text = '狀態：已啟動（pid %s）｜%s' % (running.split()[0], tail[-90:])
                colour = '#22551f'
            else:
                text = '狀態：已停止'
                colour = MUTED
            self.root.after(0, lambda: self.auto_end_state.configure(text=text, fg=colour))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(2000, self._refresh_auto_end)

    def auto_end_start(self):
        """本機自動結束回合：每階段等 N 秒後用遊戲自己的管線送 PhaseEnd（不改倒數）。"""
        secs = (self.auto_end_secs.get() or '45').strip()
        if not secs.isdigit():
            messagebox.showwarning('自動結束', '秒數要填數字（例如 45）', parent=self.root)
            return
        self.auto_end_stop(quiet=True)
        cmd = 'pkill -f auto_end.sh 2>/dev/null; cd ~/sgi-fengye-lab/shadow && ' \
              'nohup bash auto_end.sh %s > logs/auto-end.log 2>&1 &' % secs
        try:
            subprocess.Popen(['/bin/bash', '-lc', cmd])
            self.room_receipt.configure(text='自動結束已啟動：每階段 %s 秒後送出「階段結束」（只作用本機）' % secs)
        except Exception as exc:  # noqa: BLE001
            self.room_receipt.configure(text='自動結束啟動失敗：%s' % exc)

    def auto_end_stop(self, quiet=False):
        try:
            subprocess.Popen(['/bin/bash', '-lc', 'pkill -f auto_end.sh 2>/dev/null; true'])
        except Exception:  # noqa: BLE001
            pass
        if not quiet:
            self.room_receipt.configure(text='自動結束已停止')

    def game_off_local(self):
        """只關風夜的遊戲（SANPK），保留大廳與協議會話；下次「一鍵登入」可直接再進。"""
        if not messagebox.askokcancel('只關遊戲？',
                                      '會關掉風夜的遊戲客戶端（SANPK），\n'
                                      '**保留大廳與協議會話** → 下次「一鍵登入」可以直接再進，不用重新登入。\n\n確定？',
                                      parent=self.root):
            return
        import threading

        def work():
            try:
                proc = subprocess.run(['/bin/bash', '-lc', 'bash ~/sgi-fengye-lab/shadow/game_off.sh'],
                                      capture_output=True, text=True, timeout=120)
                out = [l for l in proc.stdout.splitlines() if l.strip()][-4:]
                msg = '只關遊戲：' + ' ｜ '.join(out)
                self.root.after(0, lambda: self.room_receipt.configure(text=msg[:260]))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.room_receipt.configure(text='關閉失敗：%s' % exc))

        threading.Thread(target=work, daemon=True).start()

    def godview_on_local(self):
        """手動開全視野（15 個 p52 UI 元素 + 5 個 p53 開關）。執行期補丁，重開客戶端即消失。"""
        if not messagebox.askokcancel('開全視野（去霧）？',
                                      '這會對目前的風夜客戶端安裝 22 項 UI 補丁（去霧＋圖層）。\n'
                                      '它是執行期補丁：重開客戶端就會恢復正常迷霧。\n'
                                      '一鍵武裝預設「不裝」，所以開局預設是有霧的。確定要開？',
                                      parent=self.root):
            return
        self.room_receipt.configure(text='去霧安裝中（22 項）…')
        import threading

        def work():
            try:
                proc = subprocess.run(['/bin/bash', '-lc', 'bash ~/sgi-fengye-lab/shadow/godview_on.sh'],
                                      capture_output=True, text=True, timeout=300)
                line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith('{')), '')
                msg = '去霧結果：' + (line[:160] if line else ('沒有輸出 rc=%d' % proc.returncode))
                self.root.after(0, lambda: self.room_receipt.configure(text=msg))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.room_receipt.configure(text='去霧失敗：%s' % exc))

        threading.Thread(target=work, daemon=True).start()

    def arm_now_local(self):
        """對目前這台風夜：補丁 → 還原 suppress → myforce 智能守衛 → 綁 slot0 → D8。"""
        if not messagebox.askokcancel('一鍵武裝？',
                                      '會對目前這台風夜：\n'
                                      '① 上補丁（nullguard／開局守衛，跳 myforce）\n'
                                      '② 還原 suppress（正常參與）\n'
                                      '③ myforce 智能守衛\n'
                                      '④ 綁定 slot0\n'
                                      '⑤ D8 摘席\n\n約 1–2 分鐘，確定？',
                                      parent=self.root):
            return
        seat = 0
        try:
            bound = self.bind_slot()          # 讀「開局前上身（幽靈席位）」下拉
            if isinstance(bound, int):
                seat = bound
        except Exception:  # noqa: BLE001
            seat = 0
        self.room_receipt.configure(text='武裝中：補丁→綁定 slot %s→D8 …' % seat)
        import threading

        def work():
            try:
                proc = subprocess.run(['/bin/bash', '-lc',
                                       'SEAT=%s bash ~/sgi-fengye-lab/shadow/patch_now.sh' % seat],
                                      capture_output=True, text=True, timeout=420)
                line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith('{')), '')
                msg = '武裝結果：' + (line[:260] if line else ('沒有輸出 rc=%d' % proc.returncode))
                self.root.after(0, lambda: self.room_receipt.configure(text=msg))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.room_receipt.configure(text='武裝失敗：%s' % exc))

        threading.Thread(target=work, daemon=True).start()

    def lab_force_quit(self):
        if not messagebox.askokcancel('風夜卡住了？',
                                      '這會強制關閉風夜的遊戲與相關連線。\n'
                                      '正常離開請用「風夜下線」；只有卡住、無法正常離開時才使用這個按鈕。確定繼續？',
                                      parent=self.root):
            return
        lab = self._lab_root()
        self._lab_async('強制結束風夜',
                        'cd {} && bash sticky/sticky.sh protocol-down && bash shadow_force_quit.sh'.format(
                            shlex.quote(str(lab))),
                        timeout=120)

    def lab_status(self):
        script = (
            "cd %s\n" % shlex.quote(str(self._lab_root())) +
            "echo '[進程]'\n"
            "(pgrep -fl prefix-fengye-shadow | head -3 || echo 無進程)\n"
            "echo '[D8 藏身回執]'\n"
            "(xxd -l 16 shadow_d8_receipt.bin 2>/dev/null || echo 無回執)\n"
            "echo '[崩潰台帳]'\n"
            "ls -la \"$HOME/Library/Application Support/SGI-Wine/prefix-fengye-shadow/drive_c/sgi/run-3.5/3I/sgi-crash-context.bin\" 2>/dev/null | awk '{print $5, $6, $7, $8}'\n"
            "echo '[app.log 尾]'\n"
            "tail -2 logs/app.log 2>/dev/null\n"
        )
        self._lab_async('查看風夜狀態', script, timeout=60)

    @staticmethod
    def _drop_prefixes():
        return {'丁滿（主機）': 'prefix-dingman-local', '風雲': 'prefix-sikarugir10'}

    def drop_check(self):
        self.drop_label.configure(text='正在檢查本機客戶端…')

        def work():
            lines = []
            for label, prefix in self._drop_prefixes().items():
                try:
                    pid = self.command_service.pid(prefix)
                except Exception:
                    pid = None
                lines.append('%s：%s' % (label, '在線' if pid else '離線或未啟動'))
            text = '　'.join(lines) + '\n只列出本機客戶端；遠端主機請用實驗室 CLI。'
            try:
                self.after(0, lambda: self.drop_label.configure(text=text))
            except Exception:
                pass
        threading.Thread(target=work, name='drop-check', daemon=True).start()

    def drop_client(self):
        label = self.drop_target.get()
        prefix = self._drop_prefixes().get(label)
        if not prefix:
            return
        if not messagebox.askokcancel(
                '讓對手掉線？',
                '讓「%s」立刻斷線？\n\n這是破壞性操作：對方會直接退出，'
                '主機約 30–40 秒後顯示「無法重新連線／退出」。\n'
                '每次只送一次，失敗不重試。' % label, parent=self.root):
            return
        self.drop_button.configure(state='disabled')
        self.drop_label.configure(text='正在送出掉線…')

        def work():
            result = self.command_service.drop_client(prefix)
            if result.get('ok'):
                text = '%s 已送出掉線；約 30–40 秒主機顯示退出。' % label
            else:
                detail = result.get('error') or result.get('output') or '未知原因'
                text = '沒有送出：%s' % str(detail)[:300]

            def show():
                self.drop_button.configure(state='normal')
                self.drop_label.configure(text=text)
            try:
                self.after(0, show)
            except Exception:
                pass
        threading.Thread(target=work, name='drop-client', daemon=True).start()

    def room_action(self, payload):
        # 2026-10-21：大廳活著時，任何「開會話／搜房」都是同一支風夜帳號再登入一次。
        if (payload or {}).get('op') in ('start', 'search') and self._ghost_hall_alive():
            self.room_receipt.configure(text=(
                '大廳已在線（風夜帳號已登入）：不開探針會話、不重複登入。'
                '要看房間就在大廳按「啟動遊戲」，遊戲裡的房間列表就是清單。'))
            return
        if self.room_busy or self.room_pending or self.room_uncertain or self.source.sources.source_file:
            self.room_receipt.configure(text='上一個操作還沒確認結果。請先更新狀態，不用重複點擊。')
            return
        try:
            self.jobs.put_nowait(('room', payload))
        except queue.Full:
            self.room_receipt.configure(text='正在讀取狀態，請稍候。')
            return
        self.room_busy = True
        self.room_receipt.configure(text='正在處理，請稍候；不用重複點擊。')
        self.update_room_controls()
        self._render_capture_status()

    def update_room_controls(self):
        if not hasattr(self, 'room_start'):
            return
        state = self.rooms.state
        writable = not self.source.sources.source_file and not (self.room_busy or self.room_pending or self.room_uncertain)
        fresh = state.get('fresh') and (state.get('external') or
            isinstance(state.get('observed_at'), (int, float)) and 0 <= time.time()-state['observed_at'] <= 20)
        lobby = fresh and state.get('phase') == 'lobby' and not state.get('connected')
        q = state.get('room_query') or {}
        observed = q.get('observed_at')
        listed = isinstance(observed, (int, float)) and 0 <= time.time()-observed <= 60
        registered = bool(state.get('ghost_registered'))
        withdrawn = bool(state.get('ghost_withdrawn'))
        native_state = state.get('native_sync_state')
        modes = ((self.room_once, not (fresh and state.get('connected'))),
                 (self.room_start, not state.get('alive')),
                 (self.room_search, lobby or fresh and state.get('external')), (self.room_join, lobby and listed and (bool(self.room_tree.selection()) or len(self.room_rows) == 1)),
                 (self.room_leave, fresh and state.get('connected')), (self.room_stop, fresh and not state.get('external') and state.get('phase') != 'stopped'),
                 (self.room_register, fresh and state.get('connected') and not registered),
                 (self.room_d8, fresh and state.get('connected') and registered and not withdrawn
                  and native_state == 1))
        try:
            self._maybe_auto_seat(state)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._refresh_bind_choices(state)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._sync_start_faction()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._reconcile_seat(state)
        except Exception:  # noqa: BLE001
            pass
        retrying = self.retry is not None
        for button, allowed in modes:
            button.configure(state='normal' if writable and allowed and not retrying else 'disabled')
        if hasattr(self, 'room_retry'):
            self.room_retry.configure(
                state='disabled' if self.source.sources.source_file else 'normal',
                text=('✕ 取消重做' if retrying else '↻ 重新來過'))
        self.room_stop.configure(text='風夜下線',
                                 bg='#ead4c6' if withdrawn else BG)
        if fresh and state.get('connected') and registered and not withdrawn:
            self.room_flow_label.configure(text='⚠️ 正在藏身（幾秒）——先別按「開始」', fg=WARN)
        elif fresh and state.get('connected') and withdrawn:
            d8r = state.get('d8') or {}
            if d8r.get('fast') or state.get('exit_seen_wall'):
                self.room_flow_label.configure(text='✅ 已藏好——現在可以按「開始」', fg='#2f6a4f')
            else:
                self.room_flow_label.configure(text='⚠️ 藏身訊號已送出（主機處理約 2 分鐘）——等名單上風夜消失再按「開始」', fg=WARN)
        else:
            self.room_flow_label.configure(text='等待本次進房準備。', fg=MUTED)
        self.room_line_combo.configure(state='readonly' if writable and not state.get('alive') else 'disabled')
        self.room_nick_combo.configure(state='normal' if writable and not state.get('connected') else 'disabled')

    def render_rooms(self):
        state = self.rooms.state
        q = state.get('room_query') or {}
        signature = json.dumps(q, ensure_ascii=False, sort_keys=True)
        if signature != self.room_signature:
            selected = self.room_tree.selection()
            selected_id = self.room_rows.get(selected[0], {}).get('id') if selected else None
            self.room_tree.delete(*self.room_tree.get_children())
            self.room_rows = {}
            for row in q.get('rooms') or []:
                iid = self.room_tree.insert('', 'end', values=(row.get('name') or '未命名房間',
                    row.get('host') or '尚未確認',
                    '{} / {}'.format(row.get('current', '未確認'), row.get('maximum', '未確認'))))
                self.room_rows[iid] = row
                if row.get('id') == selected_id:
                    self.room_tree.selection_set(iid)
            self.room_signature = signature
        if self.room_rows:
            self.room_empty.place_forget()
        else:
            self.room_empty.place(relx=.5, rely=.5, anchor='center')
            session_now = self.view.get('session') or {}
            if session_now.get('alive') and session_now.get('room_name'):
                self.room_empty.configure(text='已在房間：%s\n（按「搜索房間」可更新房間列表）'
                                          % session_now.get('room_name'))
            else:
                self.room_empty.configure(text=('還沒收到房間回覆，不能確定有沒有房間。'
                    if q.get('status') == 'unconfirmed_empty' else
                    '還沒有房間資料\n需要手動選房時，請展開「手動進房設定」。'))
        labels = {'idle': '還沒登入', 'starting': '正在登入', 'lobby': '正在查看房間',
                  'joining': '正在進房', 'room': '已進入房間', 'stopped': '風夜已停止連線',
                  'stale': '狀態暫未更新', 'disconnected': '連線已中斷',
                  'external_lobby': '正在查看現有大廳的房間'}
        line = str(state.get('line') or self.room_line.get()).replace('多线', '多線')
        text = '{} · {}'.format(labels.get(state.get('phase'), '正在確認'), line)
        if q.get('observed_at'):
            text += ' · 房間資料更新於 ' + wall_text(q['observed_at'])
        if state.get('error') or q.get('error'):
            text += '\n' + plain_error(state.get('error') or q.get('error'))
        if state.get('phase') in ('idle', 'stopped', 'disconnected') and not (self.view or {}).get('session'):
            self.lab_label.configure(text='還沒執行進房準備。準備期間請先別按遊戲的「開始」。')
        else:
            self.lab_label.configure(text='')
        try:
            _alias = (self.lab_nickname.get() or '').strip()
            if not _alias:
                _alias = (self.command_service.active_name() or '').strip()
            if _alias:
                text = text.replace('風夜', _alias)
        except Exception:  # noqa: BLE001
            pass
        # 2026-10-21：舊的一鍵進度機（「上次一鍵 … 占席（失敗）」）與新按鈕無關，別再顯示。
        text = '\n'.join(ln for ln in text.splitlines() if '上次一鍵' not in ln)
        self.room_status.configure(text=text)
        headline, hint = room_summary(state)
        # 2026-10-21：狀態列用「當前偽名」顯示，不要把固定字串『風夜』寫死。
        try:
            alias = (self.lab_nickname.get() or '').strip()
            if not alias:
                alias = (self.command_service.active_name() or '').strip()
            if alias:
                headline = headline.replace('風夜', alias)
                hint = hint.replace('風夜', alias)
        except Exception:  # noqa: BLE001
            pass
        # 舊的一鍵進度機（占席失敗那種）不要混進新狀態；藏身後也不需要「還沒進房」這句。
        # 2026-10-21：只認「活會話」的狀態，不要拿舊的 state 旗標冒充（曾出現上面說已藏身、
        # 下面說還沒藏身的矛盾）。session 為空＝未連線，一律當作未藏身。
        try:
            sess = ((self.view or {}).get('session') or {})
            hidden = bool(sess.get('ghost_withdrawn')) if sess else False
            online = bool(sess.get('connected') or sess.get('room_name')) if sess else False
        except Exception:  # noqa: BLE001
            hidden, online = False, False
        hint = '\n'.join(ln for ln in hint.splitlines() if '上次一鍵' not in ln)
        if hidden:
            headline = '已藏身（名單看不到）'
            hint = '房主可以直接按「開始」；開局後用「切換速鍵／shadow_force」切席位即可上身（不需要在名單上）'
        try:
            alias_now = ''
            try:
                alias_now = (self.command_service.active_name() or '').strip()
            except Exception:  # noqa: BLE001
                alias_now = ''
            if not online:
                text = '上身準備：— 目前沒有活會話（按「一鍵登入」會登入並武裝）'
                colour = MUTED
            elif hidden:
                text = '上身準備：☑ 已藏身（名單看不到）→ 開局後切席位（選：%s）' % (self.bind_choice.get() or '未選')
                colour = '#164d51'
            else:
                text = ('上身準備：☐ 已進房但還沒藏身（按一鍵會 D8 摘席）；'
                        '偽名庫目前：%s' % (alias_now or '未設'))
                colour = MUTED
            self.seat_status.configure(text=text, fg=colour)
        except Exception:  # noqa: BLE001
            pass
        self.room_channel.configure(text=headline + '\n' + hint)
        try:
            if hidden:
                items = [it for it in (state.get('items') or []) if '還沒進房' not in str(it)]
        except Exception:  # noqa: BLE001
            pass
        result = state.get('last_result') or {}
        if self.room_pending and result.get('id') == self.room_pending:
            self.room_receipt.configure(text=room_result(result))
            self.room_pending = None
            self.room_uncertain = result.get('status') == 'unknown'
            self._maybe_chain(result)
            self._notify_room_result(result)
            self._maybe_retry(result)
        self.update_room_controls()

    def _notify_room_result(self, result):
        """0.2.5：摘席流程關鍵節點的本機提示（遊戲視窗在前也看得到）。"""
        op, status = result.get('op'), result.get('status')
        room_state = self.rooms.state or {}
        d8r = room_state.get('d8') or {}
        ready = bool(d8r.get('fast') or room_state.get('exit_seen_wall'))
        if op == 'join' and status == 'completed':
            if room_state.get('ghost_withdrawn'):
                if ready:
                    notify_operator('風夜已藏好啦', '現在可以在遊戲按「開始」', sound='Glass')
                else:
                    notify_operator('藏身訊號已送出', '等風夜從遊戲名單消失（約 2 分鐘）再按「開始」', sound='Ping')
            else:
                notify_operator('風夜正在藏身', '幾秒就好——先別按「開始」', sound='Ping')
        elif op == 'join' and status == 'error':
            reason = plain_error(result.get('error') or result.get('detail'))
            notify_operator('風夜藏身沒成功', reason[:90], sound='Basso')
        elif op == 'd8' and status == 'completed':
            if ready:
                notify_operator('風夜已藏好啦', '現在可以在遊戲按「開始」', sound='Glass')
            else:
                notify_operator('藏身訊號已送出', '等風夜從遊戲名單消失（約 2 分鐘）再按「開始」', sound='Ping')
        elif op == 'd8' and status == 'error':
            reason = plain_error(result.get('error') or result.get('detail'))
            if '提前開始' not in reason and '開局等待' not in reason:
                notify_operator('風夜藏身沒成功', reason[:90], sound='Basso')

    def _maybe_chain(self, result):
        if result.get('status') != 'completed':
            return
        state = self.rooms.state
        op = result.get('op')
        if op == 'join' and state.get('connected') and not state.get('ghost_registered') and not state.get('ghost_withdrawn'):
            self.room_receipt.configure(text='自動準備：已進房，接著報到…')
            self.root.after(800, lambda: self._chain_fire('register'))
        elif op == 'register' and state.get('ghost_registered') and not state.get('ghost_withdrawn'):
            self.room_receipt.configure(text='自動準備：已報到，接著藏身…')
            self.root.after(800, lambda: self._chain_fire('d8'))

    def _chain_fire(self, op):
        self.room_action({'op': op})

    def _retry_label(self):
        return (self.retry or {}).get('label', '重新來過')

    def one_click_enter(self):
        """0.2.21 一鍵上場：登入(如需)→更新房間→進入(自動報到→藏身)；完成後流程自動收束。"""
        try:
            slot = self.bind_slot()
            if isinstance(slot, int):
                self.command_service.write_start_faction(slot)
        except Exception:  # noqa: BLE001
            pass
        if self.source.sources.source_file:
            return
        if self.retry is not None or self.room_busy or self.room_pending or self.room_uncertain:
            self.room_receipt.configure(text='上一個操作還在進行（或結果未知）——請稍候，或按「↻ 重新來過」。')
            return
        state = self.rooms.state or {}
        if state.get('fresh') and state.get('connected'):
            self.room_receipt.configure(text='風夜已經在房間裡了（報到／藏身狀態見下方）；要重來請按「↻ 重新來過」。')
            return
        steps = []
        if not (state.get('fresh') and state.get('alive')):
            steps += ['start', 'wait_lobby']
        q = state.get('room_query') or {}
        observed = q.get('observed_at')
        fresh_rooms = (isinstance(observed, (int, float)) and 0 <= time.time() - observed <= 30
                       and (q.get('rooms') or []))
        if not fresh_rooms:
            steps.append('search')
        steps.append('wait_rooms')
        self.auto_seat_done = None
        self.retry = {'steps': steps, 'deadline': time.monotonic() + 180, 'start_retries': 0,
                      'label': '一鍵上場'}
        self.retry_next()

    def oneclick_by_target(self):
        """一鍵：線路＋房間號或房主虛擬 IP → 登入 → 進房 → 補丁 → 綁勢力 → 藏身（D8）。

        房間號與 IP 是同一個東西（房間 id = 房主虛擬 IP 的大端），所以只收一個欄位，
        由 sticky.sh oneclick 內部轉換。進房位址一定要帶線路中繼埠（本線 29100），
        帶遊戲埠 7777 會等不到房主回應（2026-10-21 19:02/19:07 實測）。
        """
        target = (self.room_target.get() or '').strip()
        # 2026-10-21：按鈕有沒有被按到，先寫一行到 data/oneclick-clicks.log，
        # 這樣「按了沒反應」可以從檔案判斷是「沒觸發」還是「跑了但沒顯示」。
        try:
            import pathlib as _pl
            log = _pl.Path(__file__).resolve().parent / 'data' / 'oneclick-clicks.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('a', encoding='utf-8') as fh:
                fh.write('%s target=%r line=%r\n' % (time.strftime('%Y-%m-%dT%H:%M:%S'),
                                                      target, self.room_line.get()))
        except Exception:  # noqa: BLE001
            pass
        if getattr(self, '_oneclick_busy', False):
            try:
                self.oneclick_state.configure(text='上一次一鍵還在跑，等它結束（約 1–4 分鐘）', fg=MUTED)
            except Exception:  # noqa: BLE001
                pass
            return
        self._oneclick_busy = True
        try:
            self.oneclick_state.configure(text='一鍵執行中…（登入／進房／補丁，約 1–4 分鐘）', fg='#164d51')
            self.oneclick_btn.configure(state='disabled')
        except Exception:  # noqa: BLE001
            pass
        if not target:
            self._oneclick_busy = False
            self.room_receipt.configure(
                text='請先填房間號（例 168593956）或房主虛擬 IP（例 10.12.138.36）。')
            return
        line = (self.room_line.get() or '多线3').strip()
        nick = ''
        try:
            nick = (self.lab_nickname.get() or '').strip()
        except Exception:  # noqa: BLE001
            nick = ''
        try:
            slot = self.bind_slot()
        except Exception:  # noqa: BLE001
            slot = None
        lab = self._lab_root()
        prefix = ('JOIN_NICKNAME=%s ' % shlex.quote(nick)) if nick else ''
        host = ''
        try:
            idx = self.room_pick.current()
            if 0 <= idx < len(self._room_choices):
                host = (self._room_choices[idx].get('host') or '').strip()
        except Exception:  # noqa: BLE001
            host = ''
        # 2026-10-21：改用 baseline 驗證過的 arm_now.sh（22 補丁＋suppress＋D8＋常駐驅動），
        # 不是 5 補丁的 sticky oneclick——後者開局會被打回「遊戲選擇」（mode=0）。
        room_name = 'SGZWLB'
        try:
            idx = self.room_pick.current()
            if 0 <= idx < len(self._room_choices):
                room_name = (self._room_choices[idx].get('name') or 'SGZWLB').strip() or 'SGZWLB'
        except Exception:  # noqa: BLE001
            pass
        seat = 5
        try:
            bound = self.bind_slot()          # 開局前上身（幽靈席位）下拉
            if isinstance(bound, int):
                seat = bound
        except Exception:  # noqa: BLE001
            seat = 5
        # 2026-10-22：改用今天驗證過的本機鏈（join_now.sh → patch_now.sh），不再走 arm_now.sh（會 exited）
        script = 'cd ~/sgi-fengye-lab/shadow && bash one_click_ghost.sh --seat %s' % (seat if seat != 5 else 0)
        self.room_receipt.configure(text='一鍵：加入 %s／偽名 %s（清單加入→補丁→綁定→D8，約 2–4 分鐘）…'
                                    % (room_name, nick or '（未設）'))
        self._lab_async_receipt('一鍵武裝（%s）' % room_name, script, timeout=900)

    def one_click_retry(self):
        """失敗後一鍵收尾重來：退房→收線→重登→查房→進入（接手自動註冊→摘席）。"""
        if self.source.sources.source_file:
            return
        if self.retry is not None:
            self.retry = None
            self.room_receipt.configure(text='已取消「重新來過」；按鈕恢復正常。')
            return
        # 2026-10-21 使用者：原本的「重新來過」= 退房＋收線＋重登，會在對面製造一次
        # 「退出→進入」訊號。改成同一條會話重跑 autojoin（沒有會話時才登入一次）。
        lab = self._lab_root()
        self._lab_async('重新整理（同一條會話，不再登入）',
                        'cd {} && bash sticky/sticky.sh autojoin'.format(shlex.quote(str(lab))),
                        timeout=600)

    def retry_next(self):
        """推進「一鍵重來」流程；每步只發一次操作，結果經 _maybe_retry 續行。"""
        tag = (self.retry or {}).get('label', '重新來過')
        if self.retry is None:
            return
        # 2026-10-21：使用者手動結束遊戲／關掉所有客戶端時，一鍵要自己恢復。
        try:
            due = time.time() - getattr(self, '_clients_at', 0) > 2
        except Exception:  # noqa: BLE001 - 測試用 Mock 時間
            due = False
        if due:
            self._clients_at = time.time()
            try:
                import subprocess
                out = subprocess.run(['pgrep', '-f', 'SANPK.exe'], capture_output=True, text=True).stdout
                self._client_count = len([x for x in out.split() if x.strip()])
            except Exception:  # noqa: BLE001
                self._client_count = None
        if getattr(self, '_client_count', None) == 0:
            self.retry = None
            self.room_receipt.configure(
                text=tag + '：偵測到客戶端都已關閉，已中止（可重新按一鍵）。')
            return
        if time.monotonic() > self.retry.get('deadline', 0):
            self.retry = None
            self.room_receipt.configure(text=tag + '：超時中止；請確認狀態後再試。')
            return
        if self.room_uncertain:
            self.retry = None
            self.room_receipt.configure(text=tag + '：上次操作結果未知（不重複送），已中止。')
            return
        if self.room_busy or self.room_pending:
            return
        steps = self.retry['steps']
        if not steps:
            self.retry = None
            self.room_receipt.configure(text=tag + '：已進房並自動藏身——聽到「可以開始」提示音後再按「開始」。')
            # 2026-10-21：一鍵完成的當下就自動上身（不等房間狀態輪詢，
            # 否則常被一鍵自己的 slot 5 覆蓋、或狀態還來不及變 fresh）。
            try:
                self._auto_seat_now()
            except Exception:  # noqa: BLE001
                pass
            return
        step = steps[0]
        state = self.rooms.state
        if step == 'leave':
            self.retry['steps'] = steps[1:]
            self.room_action({'op': 'leave'})
            self.room_receipt.configure(text=tag + '：退出房間…（若有等待畫面請按掉）')
        elif step == 'stop':
            self.retry['steps'] = steps[1:]
            self.room_action({'op': 'stop'})
            self.room_receipt.configure(text=tag + '：讓風夜下線…')
        elif step == 'wait_teardown':
            if not state.get('alive') and not state.get('fresh'):
                self.retry['steps'] = steps[1:]
                self.room_receipt.configure(text=tag + '：已下線，重新登入…')
                self.retry_next()
        elif step == 'start':
            self.retry['steps'] = steps[1:]
            self.room_action({'op': 'start', 'line': self.room_line.get()})
            self.room_receipt.configure(text=tag + '：登入風夜大廳…')
        elif step == 'wait_lobby':
            if state.get('fresh') and state.get('alive') and state.get('phase') == 'lobby':
                self.retry['steps'] = steps[1:]
                self.retry_next()
        elif step == 'search':
            self.retry['steps'] = steps[1:]
            self.room_action({'op': 'search'})
            self.room_receipt.configure(text=tag + '：查房中…')
        elif step == 'wait_rooms':
            if not (state.get('fresh') and state.get('phase') == 'lobby'):
                return
            q = state.get('room_query') or {}
            observed = q.get('observed_at')
            if not isinstance(observed, (int, float)) or time.time() - observed > 60:
                return
            rooms = q.get('rooms') or []
            self.retry['steps'] = []
            if len(rooms) == 1:
                row = rooms[0]
                try:
                    name = nickname(self.room_nickname.get())
                except ValueError as error:
                    self.retry = None
                    self.room_receipt.configure(text=plain_error(error))
                    return
                self.room_action({'op': 'join', 'room_id': row['id'], 'nickname': name, 'quick': True})
                self.room_receipt.configure(text=tag + '：進入「{}」——等一下會通知「可以開始」…'.format(row.get('name') or '所選房間'))
            elif not rooms:
                self.retry = None
                self.room_receipt.configure(text=tag + '：查不到房間——請先在遊戲重開房間，再按「↻ 重新來過」。')
            else:
                self.retry = None
                self.room_receipt.configure(text=tag + '：有多個房間，請自行選房後按「進入所選房間」。')

    def _maybe_retry(self, result):
        if self.retry is None:
            return
        op, status = result.get('op'), result.get('status')
        if op == 'start':
            if status == 'started':
                self.retry_next()
            elif self.retry.get('start_retries', 0) < 2:
                self.retry['start_retries'] = self.retry.get('start_retries', 0) + 1
                self.retry['steps'].insert(0, 'start')
                self.room_receipt.configure(text='重新來過：登入暫未成功，4 秒後再試一次…')
                self.root.after(4000, self.retry_next)
            else:
                self.retry = None
                self.room_receipt.configure(text='重新來過：' + plain_error(result.get('error') or status))
            return
        if op in ('leave', 'stop', 'search') and status in ('completed', 'error'):
            # 收尾步驟失敗不致命（可能已斷線／已停止）：繼續下一步。
            self.retry_next()
        elif op == 'join':
            if status == 'completed':
                self.retry_next()
            else:
                self.retry = None
                self.room_receipt.configure(text='重新來過：' + plain_error(result.get('error') or result.get('detail') or status))

    # Keep the complete original polling/rendering path. Fengye has a separate
    # worker and queue, so an offline probe never replaces a valid world state.
    def _fetch_fengye(self):
        job = ('refresh', False)
        while not self.stop.is_set():
            op, payload = job
            try:
                if op == 'room':
                    result = self.rooms.call(payload)
                    self.messages.put(('room_result', result))
                if op == 'control':
                    try:
                        result = self.source.send(payload)
                    except Exception:
                        result = {'status': 'error', 'error': '控制結果未知；未重試'}
                    self.messages.put(('control', result))
            except Exception:
                self.messages.put(('error', '操作失敗；保留最後記錄'))
            # 2026-10-17：資料讀取與大廳心跳分開執行——資料通道失敗或超時時，
            # 房間監控（維持探針心跳）仍必須繼續，避免探針因心跳到期誤收尾。
            try:
                self.messages.put(('view', self.source.refresh(search=(op == 'refresh' and payload))))
            except Exception:
                self.messages.put(('error', '讀取失敗；保留最後記錄'))
            try:
                self.rooms.call({'op': 'status'})
                self.messages.put(('rooms', None))
            except Exception:
                pass
            self.messages.put(('idle', None))
            while not self.stop.is_set():
                try:
                    job = self.jobs.get(timeout=.25)
                    break
                except queue.Empty:
                    if self.stop.wait(.25):
                        return
                    # Poll only while this native window exists. 房間操作待回執時
                    # 加快輪詢（5s→1s），縮短一鍵流程的暴露窗口。
                    interval = 0.5 if (self.room_busy or self.room_pending) else 5
                    if time.monotonic() - getattr(self, '_last_poll', 0) >= interval:
                        job = ('refresh', False)
                        break
            self._last_poll = time.monotonic()

    def request_refresh(self, search=False):
        if self.stop.is_set():
            return
        try:
            self.jobs.put_nowait(('refresh', search))
        except queue.Full:
            pass

    def _tick_fengye(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'view':
                    self.view = value
                    self.render_view(value)
                elif kind == 'control':
                    self.control_busy = False
                    if value.get('status') == 'sent':
                        self.pending_id = value.get('id')
                        self.control_result.configure(text='操作已送出，正在等風夜回覆；還沒確認完成。')
                        if value.get('op') == 'chat':
                            self.chat_input.delete('1.0', 'end')
                    else:
                        self.pending_uncertain = True
                        self.control_result.configure(text=plain_error(value.get('error') or value.get('status')))
                elif kind == 'room_result':
                    self.room_busy = False
                    if value.get('status') == 'sent':
                        self.room_pending = value.get('id')
                        self.room_receipt.configure(text='操作已送出，正在等風夜回覆；不用重複點擊。')
                    else:
                        self.room_uncertain = value.get('status') == 'unknown'
                        self.room_receipt.configure(text=room_result(value))
                        self._maybe_retry(value)
                    self.render_rooms()
                elif kind == 'rooms':
                    self.render_rooms()
                elif kind == 'error':
                    self.notice_label.configure(text=plain_error(value, '資料暫時更新不到，舊紀錄不代表風夜仍在線。請稍後更新狀態。'))
                elif kind == 'idle':
                    self.reload_btn.configure(state='normal')
        except queue.Empty:
            pass
        except Exception as error:
            self.render_error = str(error)
            print('fengye-render', error, flush=True)
        self.update_control_state()
        self.update_room_controls()
        if self.retry is not None:
            try:
                self.retry_next()
            except Exception:
                self.retry = None
        # 2026-10-21（0.2.89）：線路狀態每 20 秒更新一次（本地 shell，很輕）。
        self._line_tick = getattr(self, '_line_tick', 0) + 1
        if self._line_tick % 80 == 1 and hasattr(self, 'line_status_label'):
            try:
                self.lab_line_refresh()
            except Exception:
                pass
        if not self.stop.is_set():
            self.root.after(250, self._tick_fengye)

    def _bind_label(self):
        """回傳 (名字, slot)；選「無勢力」或還沒讀到名字時回 None。"""
        choice = (self.bind_choice.get() or '').strip()
        if not choice or choice.startswith('無勢力'):
            return None
        import re as _re
        found = _re.search(r'slot\s*(\d)', choice)
        if not found:
            return None
        slot = int(found.group(1))
        if choice.startswith('玩家'):        # 名冊還沒讀到，先用第幾位
            return '第 %d 位玩家' % (slot + 1), slot
        name = choice.split('（')[0].strip()
        return (name, slot) if name else None

    def _paint_one_click_progress(self):
        now = time.time()
        width = self.progress_canvas.winfo_width()
        if (now - getattr(self, '_progress_checked', 0) < 1
                and width == getattr(self, '_progress_width', 0)
                and self.progress_canvas.find_all()):
            return
        self._progress_checked = now
        self._progress_width = width
        try:
            progress = load_one_click_progress()
        except Exception:
            progress = {'percent': 0, 'label': '尚未開始', 'failed': False}
        percent = max(0, min(100, int(progress.get('percent') or 0)))
        label = progress.get('label') or '尚未開始'
        stale = bool(progress.get('stale'))
        if progress.get('failed') and not stale:
            label = '%s · 未完成' % label
        if stale:
            # 2026-10-21：沒在跑就別掛著上一次的百分比（使用者：明明不在清單裡還停在 92%）。
            self.progress_label.configure(text='一鍵：%s' % label, fg=MUTED)
            percent = 0
        else:
            self.progress_label.configure(text='一鍵進度 %d%% · %s' % (percent, label),
                                         fg=WARN if progress.get('failed') else INK)
        width = max(self.progress_canvas.winfo_width(), 280)
        self.progress_canvas.delete('all')
        self.progress_canvas.create_rectangle(0, 2, width, 12, fill='#d5e4e2', outline='')
        if percent:
            self.progress_canvas.create_rectangle(0, 2, max(4, width * percent / 100.0), 12,
                                                 fill='#c45b4a' if progress.get('failed') else '#1f7a72',
                                                 outline='')
        elif stale:
            self.progress_canvas.create_rectangle(0, 2, width, 12, fill='#d5e4e2', outline='')

    def _paint_live(self, view):
        """一句玩家大白話說清風夜現在在哪：沒開／登入中／在遊戲選擇／在房間／藏好／對局中。"""
        label = getattr(self, 'live_label', None)
        hint = getattr(self, 'live_hint', None)
        if label is None:
            return
        now = time.time()
        if now - getattr(self, '_live_at', 0) < 1:
            return
        self._live_at = now
        s = (view or {}).get('status') or {}
        sess = (view or {}).get('session') or {}
        present = bool(s.get('present'))
        hall = bool((s.get('hall') or {}).get('present'))
        room = (sess.get('room_name') or '').strip()
        scene = s.get('scene') or {}
        in_map = bool(scene.get('in_map')) or (scene.get('mode') == 3)
        patches = s.get('patches') or {}
        rx = s.get('rx') or {}
        hidden = bool((s.get('hide') or {}).get('verified'))
        rounds = (s.get('driver') or {}).get('rounds')
        try:
            proto = self._protocol_session_alive()
        except Exception:  # noqa: BLE001
            proto = False

        def say(main, why, color):
            label.configure(text=main, fg=color)
            if hint is not None:
                hint.configure(text=why)

        if in_map:
            say('風夜正在旁聽' + ('（第 %s 回合）' % rounds if rounds else ''),
                '什麼都不用按；要收工按「風夜下線」', GOLD)
            return
        if room:
            if hidden:
                say('風夜已進房間、也藏好了：%s' % room,
                    '可以請房主按「開始」', GOLD)
            else:
                say('風夜已進房間：%s（還沒藏身）' % room,
                    '按「讓風夜藏好」，再請房主按「開始」', INK)
            return
        if present:
            if patches.get('ready'):
                say('風夜已登入，停在「遊戲選擇」', '等房主開房，或按「重新整理／再進房」', GOLD)
            else:
                say('風夜已登入，停在「遊戲選擇」（補丁還沒裝）',
                    '選到房間後會自動裝補丁＋藏身', INK)
            return
        if hall:
            say('風夜在大廳（還沒開遊戲）',
                '在大廳按「啟動遊戲」，再看房間清單', INK)
            return
        if proto:
            say('風夜正在登入…', '等遊戲視窗出現（大約 1 分鐘）', INK)
            return
        say('風夜還沒開遊戲', '按「登入（風夜）」開始', MUTED)

    def render_status_panel(self, view):
        self._paint_live(view)
        self._paint_one_click_progress()
        items = status_items(view)
        try:
            bind = self._bind_label()
        except Exception:  # noqa: BLE001
            bind = None
        if bind:
            seat = (view or {}).get('seat') or {}
            actual = getattr(self, '_actual_slot', None)
            if not isinstance(actual, int):
                actual = seat.get('slot')
            # 只顯示「已綁定」如果風夜真的在那個席位；否則老實說還沒上身。
            if isinstance(actual, int) and actual == bind[1]:
                label = '已綁定 %s 的勢力' % bind[0]
                detail = 'slot %d（已上身）' % bind[1]
            elif isinstance(actual, int) and actual >= 0:
                label = '還沒上身：綁定 %s，風夜目前在 slot %d' % (bind[0], actual)
                detail = '按「切換速鍵」或等自動校正'
            else:
                label = '還沒上身：綁定 %s（slot %d）' % (bind[0], bind[1])
                detail = '按「切換速鍵」立即切過去'
            seats_ok = isinstance(actual, int) and actual == bind[1]
            mapped = []
            for item in items:
                text = item.get('label') or ''
                if text == '風夜沒有自己的勢力（純旁觀）':
                    mapped.append(dict(item, label=label, detail=detail))
                elif not seats_ok and text.startswith('可以按'):
                    # 還沒坐進綁定席位前，不准說「可以按開始」
                    mapped.append(dict(item, level='warn',
                                       label='先別按開始：正在綁定 %s（slot %d）' % (bind[0], bind[1]),
                                       detail='等這行變成「已綁定」再按'))
                else:
                    mapped.append(item)
            items = mapped
        signature = json.dumps(items, ensure_ascii=False, sort_keys=True)
        if signature == getattr(self, 'status_signature', None):
            return
        self.status_signature = signature
        for child in self.state_rows.winfo_children():
            child.destroy()
        if not items:
            tk.Label(self.state_rows, text='還沒有風夜的即時狀態。', bg=WELL, fg=MUTED,
                     anchor='w').pack(fill='x')
            return
        from fengye_source import STATUS_ICONS
        for item in items:
            row = tk.Frame(self.state_rows, bg=WELL)
            row.pack(fill='x', pady=1)
            tk.Label(row, text=STATUS_ICONS.get(item.get('level'), '🔹'), bg=WELL, fg=INK,
                     width=3, anchor='w').pack(side='left')
            label = {'正在收遊戲資料': '正在接收同步封包',
                     '遊戲資料停下來了': '同步封包暫無新記錄'}.get(item.get('label'), item.get('label') or '')
            tk.Label(row, text=label, bg=WELL, fg=INK, anchor='w',
                     font=(self.face, 12)).pack(side='left')
            if item.get('detail'):
                tk.Label(row, text='　' + str(item['detail']), bg=WELL, fg=MUTED,
                         anchor='w').pack(side='left')

    def _chat_time_store(self):
        store = getattr(self, '_chat_times', None)
        if isinstance(store, dict):
            return store
        try:
            data = json.loads(CHAT_TIMES.read_text(encoding='utf-8'))
            store = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            store = {}
        self._chat_times = store
        return store

    def _tag_chat_times(self, chats):
        """每條聊天第一次出現時，記下當時讀到的遊戲時間（例：200年春）。

        聊天封包本身沒有帶年份季節，所以只能取「Hub 第一次看到這條訊息時」的回合，
        讀不到就留空、顯示「回合未記錄」，不補造。
        """
        store = self._chat_time_store()
        when = self._round_when(getattr(self, 'cmd_targets_data', None) or {})
        if not when:
            return store
        changed = False
        for message in chats or []:
            wall = message.get('wall')
            if not isinstance(wall, (int, float)):
                continue
            key = '%.3f' % wall
            if key in store:
                continue
            store[key] = when
            changed = True
        if changed:
            if len(store) > 600:
                for key in sorted(store)[:len(store) - 600]:
                    store.pop(key, None)
            try:
                CHAT_TIMES.parent.mkdir(parents=True, exist_ok=True)
                CHAT_TIMES.write_text(json.dumps(store, ensure_ascii=False, sort_keys=True),
                                      encoding='utf-8')
            except OSError:
                pass
        return store

    def _render_chat_text(self, widget, chats, store, factions, empty_text):
        """把聊天寫進 Text：時間行灰色，名字（勢力）與內文用該勢力的遊戲配色。"""
        if widget is None:
            return
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.tag_configure('chat_meta', foreground=MUTED, font=(self.face, 10))
        widget.tag_configure('chat_name', font=(self.face, 11, 'bold'))
        widget.tag_configure('chat_body', font=(self.face, 11))
        if not chats:
            widget.insert('end', empty_text)
        for index, message in enumerate(chats):
            stamp, label, text, colour = chat_parts(message, store, factions)
            if index:
                widget.insert('end', '\n\n')
            tag = 'chat_colour_%s' % (colour or 'ink')
            widget.tag_configure(tag, foreground=colour or INK)
            widget.insert('end', stamp + '  ', 'chat_meta')
            widget.insert('end', label, ('chat_name', tag))
            widget.insert('end', '\n' + text, ('chat_body', tag))
        widget.configure(state='disabled')

    def render_view(self, view):
        p = view.get('p34') or {}
        session = view.get('session') or {}
        transport = (view.get('transport') or {}).get('status')
        self._render_capture_status()
        self.render_status_panel(view)
        signature = json.dumps({k: view.get(k) for k in ('p34', 'host', 'members', 'events', 'directory', 'room_query', 'chain', 'source', 'ghost', 'collector')}, ensure_ascii=False, sort_keys=True)
        if signature != self.render_signature:
            chats = (p.get('chat') or {}).get('messages') or []
            chat_store = self._tag_chat_times(chats)
            factions = sender_factions(p)
            empty = '本局尚無聊天記錄。' if session else '目前沒有可核實的聊天記錄。'
            self._render_chat_text(self.console_chat, chats, chat_store, factions, empty)
            if getattr(self, 'chat_history', None) is not None:
                self._render_chat_text(self.chat_history, chats, chat_store, factions, empty)
            events = (p.get('control') or {}).get('events') or []
            self._set_text(self.control_log, '\n\n'.join(
                '{}\n{}'.format(wall_text(e.get('wall')), control_event(e))
                for e in reversed(events)) or '目前還沒有操作結果。')
            self.render_signature = signature
        control = p.get('control') or {}
        last = control.get('last_result') or {}
        if self.pending_id and last.get('id') == self.pending_id:
            self.control_result.configure(text=control_event(dict(last, ev='control_done')))
            self.pending_id = None
        if self.pending_run and p.get('run_name') != self.pending_run:
            self.pending_id = None
            self.pending_uncertain = False
            self.control_result.configure(text='目前顯示的是另一場對局；先前操作不會再次送出。')
            self.pending_run = None
        self.update_control_state()

    def input_changed(self, _=None):
        if not self.chat_input.edit_modified():
            return
        self.chat_input.edit_modified(False)
        text = self.chat_input.get('1.0', 'end-1c')
        try:
            text.encode('gbk')
            valid = len(text) <= 120
            suffix = '可以送出' if valid else '超過 120 字，請縮短訊息'
        except UnicodeEncodeError:
            valid = False
            suffix = '有遊戲無法顯示的字，請改用常見文字'
        self.char_label.configure(text='{} / 120 字 · {}'.format(len(text), suffix), fg=MUTED if valid else WARN)
        self.update_control_state()

    def update_control_state(self):
        if not hasattr(self, 'console_state'):
            return
        ready = control_ready(self.view)
        p = self.view.get('p34') or {}
        pending = self.pending_id or (p.get('control') or {}).get('pending')
        enabled = ready and not self.control_busy and not pending and not self.pending_uncertain and time.monotonic() >= self.cooldown
        lobby = self.rooms.state
        session = self.view.get('session') or {}
        status = self.view.get('status') or {}
        if self.source.sources.source_file:
            headline = '正在查看保存的記錄，這裡不能操作遊戲。'
        elif session.get('alive'):
            # 2026-10-19：有本局會話時以會話為準（用戶反饋：明明在房裡，
            # 橫幅還寫「風夜尚未進房」）。
            hide = status.get('hide') or {}
            in_match = bool((status.get('scene') or {}).get('in_map'))
            if isinstance(hide, dict) and hide.get('verified'):
                headline = ('✅ 風夜已在局中旁聽（已藏身、沒有勢力）' if in_match
                            else '✅ 風夜已在房間旁聽中（已藏身）——可以按「開始」')
            elif session.get('ghost_withdrawn'):
                headline = '⚠ 藏身訊號已送出——等遊戲名單上風夜消失再按「開始」'
            elif session.get('room_name'):
                headline = '⚠ 風夜已進房，但還沒藏身——開局前請先按「讓風夜藏好」'
            else:
                headline = '風夜還在大廳，尚未進入房間。'
        elif room_fresh(lobby):
            if lobby.get('connected') and not lobby.get('ghost_withdrawn'):
                if lobby.get('ghost_registered'):
                    headline = '⚠ 風夜正在藏身（幾秒）——先別按「開始」'
                else:
                    headline = '⚠ 風夜已進房，正在報到→藏身——先別按「開始」'
            elif lobby.get('connected') and lobby.get('ghost_withdrawn'):
                d8r = lobby.get('d8') or {}
                if d8r.get('fast') or lobby.get('exit_seen_wall'):
                    headline = '✅ 風夜已藏好·旁聽中——可以按「開始」'
                else:
                    headline = '⚠ 藏身訊號已送出——等風夜從遊戲名單消失再按「開始」（約 2 分鐘）'
            else:
                headline = '風夜還在大廳，尚未進入房間。'
        else:
            # 2026-10-20：幽靈是「影子實體客戶端」時，房間 probe 通常已收線，
            # 但它的進程與局內資料仍在——用指令頁的同一個讀取結果判斷「在局中」。
            cmd = getattr(self, 'cmd_targets_data', None) or {}
            live = any(t.get('alive') for t in (cmd.get('targets') or [])
                       if '風夜' in str(t.get('label')))
            phase = cmd.get('phase')
            if live and isinstance(phase, int) and phase >= 0:
                headline = '✅ 風夜已在局中（監聽中；%s）' % (cmd.get('phase_text') or ('phase=%s' % phase))
                headline = '✅ ' + getattr(self, '_live_text', '風夜在線（本機實況）')
            else:
                headline = (('✅ ' + getattr(self, '_live_text', '風夜在線（本機實況）'))
                             if getattr(self, '_live_online', False)
                             else '風夜尚未進房 · 先請房主建房，再讓風夜進房。')
        self.console_state.configure(text=headline)
        try:
            validate_control({'op': 'chat', 'text': self.chat_input.get('1.0', 'end-1c')})
            text_valid = True
        except ValueError:
            text_valid = False
        self.chat_button.configure(state='normal' if enabled and text_valid else 'disabled')
        self.stop_button.configure(state='normal' if enabled else 'disabled')

    def send_control(self, payload):
        if not control_ready(self.view) or self.control_busy or self.pending_id or self.pending_uncertain or (self.view.get('p34') or {}).get('control', {}).get('pending') or time.monotonic() < self.cooldown:
            return
        try:
            payload = validate_control(payload)
        except ValueError as error:
            messagebox.showerror('無法送出', plain_error(error), parent=self.root)
            return
        try:
            self.jobs.put_nowait(('control', payload))
        except queue.Full:
            self.control_result.configure(text='正在讀取狀態；本次未送出，請稍候。')
            return
        self.control_busy = True
        self.pending_run = (self.view.get('p34') or {}).get('run_name')
        self.cooldown = time.monotonic() + 2
        self.control_result.configure(text='送出單次請求中；不會自動重試。')
        self.update_control_state()

    def send_chat(self):
        self.send_control({'op': 'chat', 'text': self.chat_input.get('1.0', 'end-1c')})

    def send_stop(self):
        if not control_ready(self.view) or self.control_busy:
            return
        if messagebox.askokcancel('風夜下線（正常退出）',
                                  '讓風夜下線並結束旁聽？\n'
                                  '下線後要再旁聽需重新登入。', parent=self.root):
            self.send_control({'op': 'stop'})

