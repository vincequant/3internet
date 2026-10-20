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
from fengye_source import FengyeSource, control_ready, status_items, validate_control
from room_client import RoomClient
from backend.room_protocol import nickname
from backend import fengyun_local
from backend.lab_remote import lab_remote
from command_service import CommandService
from fengye_capture_status import CaptureStatus
from fengye_diagnostics import report
from map_navigation import bind_pointer_wheel
from player_text import (plain_error, room_summary, room_result, room_fresh,
                         operation_result, local_state, control_event,
                         force_choices, force_summary, lab_result)

# 2026-10-19 用戶要求：暫時關閉「切換對應的玩家」面板（風夜/本機兩行）。
# 等席位切換（含「無勢力觀戰」選項與玩家名單讀取）優化好再打開。
# 底層工具不受影響：遠端 `shadow_force.sh switch N` 與本機 fengyun_local.setforce 仍可 CLI 使用。
FORCE_SWITCH_UI = False

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

    規則（0.2.30 修正後的單一模型，戰場頁與外部指令頁共用）：
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
        root.title('風夜情報台')
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
                w.configure(text='風夜情報台')
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
        self.console_page = self._page('風夜情報台', 1)
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
        self.control_book.add(self.command_page, text='外部指令')
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
        self.battle_page = tk.Frame(self.control_book, bg=DAMASK)
        self.control_book.add(self.battle_page, text='戰場')
        self._build_battle_page()
        self.chat_history_page = tk.Frame(self.control_book, bg=DAMASK)
        self.control_book.add(self.chat_history_page, text='聊天歷史')
        tk.Label(self.chat_history_page, text='本局收到的聊天（唯讀，逐條按時間）', bg=DAMASK, fg=GOLD,
                 font=(self.face, 13, 'bold'), anchor='w').pack(fill='x', padx=16, pady=(10, 2))
        tk.Label(self.chat_history_page, text='目前只顯示風夜連線收到的聊天；同盟／私聊頻道是否可旁聽尚未驗證（P60）。',
                 bg=DAMASK, fg=MUTED, anchor='w', justify='left',
                 wraplength=1000).pack(fill='x', padx=16, pady=(0, 4))
        self.chat_history = self._text(self.chat_history_page, 14)
        self.lab_page = tk.Frame(self.control_book, bg=DAMASK)
        self.control_book.add(self.lab_page, text='實驗室')
        self._build_lab_page()
        self._build_local_controls()
        # 2026-10-19 用戶要求：只留一頁聊天歷史；其餘兩頁隱藏（元件保留，避免既有刷新路徑失效）。
        self.control_book.hide(self.chat_control_page)
        for tab in self.control_book.tabs():
            if self.control_book.tab(tab, 'text') == '玩家與遊戲':
                self.control_book.hide(tab)
        # 0.2.18：資料讀取等系統訊息集中在這一行（原「本局局勢」頁的提示已移除）。
        self.notice_label = tk.Label(self.console_page, text='', bg=DAMASK, fg=MUTED, anchor='w',
                                     justify='left', wraplength=1100)
        self.notice_label.pack(fill='x', padx=14, pady=(0, 8))

    # ---------------------------------------------------------- 外部指令
    def _build_command_controls(self):
        from command_panel import CommandPanel
        replay = bool(self.source.sources.source_file)
        history = None if replay else Path(__file__).resolve().parent / 'data' / 'command-history.json'
        self.command_service = CommandService(history_path=history)
        self.command_panel = CommandPanel(
            self.command_page, self.command_service,
            on_snapshot=self._command_snapshot, readonly=replay, on_error=self._capture_failed)
        self.command_panel.pack(fill='both', expand=True)

    def _cmd_refresh(self):
        return self.command_panel.refresh()

    def _cmd_draw_map(self):
        # The original world map and its timeline keep their view on tab change.
        self.command_panel.render_jobs()

    # ------------------------------------------------------------ 戰場（唯讀）
    def _build_battle_page(self):
        from fengye_battle_panel import BattlePanel
        self.battle_panel = BattlePanel(
            self.battle_page, self.command_service,
            autostart=not bool(self.source.sources.source_file))
        self.battle_panel.pack(fill='both', expand=True, padx=12, pady=8)
        self.battle_map = self.battle_panel.panorama.canvas
        self.battle_forces = self.battle_panel.forces
        self.battle_units = self.battle_panel.units
        self.battle_panel.on_state = self._accept_shadow_snapshot
        self.battle_panel.on_error = self._capture_failed

    def _command_snapshot(self, data):
        self.cmd_targets_data = data
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

    def _battle_refresh(self):
        self.battle_panel.refresh()

    def _canvas_size(self, canvas, min_w, min_h, fallback=(720, 230)):
        """畫布尺寸：分頁沒被選到（未映射）時沿用上次有效的尺寸。

        舊版用 ``canvas.winfo_width() or 720``，未映射時 winfo_width() 回 1（不是 0），
        會把地圖畫成 360 寬的窄條，切回分頁才會突然變寬 → 「版面不固定」。
        """
        try:
            width = canvas.winfo_width()
            height = canvas.winfo_height()
        except Exception:  # noqa: BLE001
            width = height = 1
        key = str(canvas)
        sizes = getattr(self, '_canvas_sizes', None)
        if sizes is None:
            sizes = self._canvas_sizes = {}
        if width <= 1 or height <= 1:
            last = sizes.get(key)
            width, height = last if last else fallback
        else:
            sizes[key] = (width, height)
        return max(min_w, int(width)), max(min_h, int(height))

    def _battle_draw_map(self, cities, units, name_of):
        self._battle_last = (list(cities or []), list(units or []), dict(name_of or {}))
        canvas = self.battle_map
        canvas.delete('all')
        width, height = self._canvas_size(canvas, 360, 160, (720, 230))
        try:
            self._battle_paint_map(canvas, width, height, cities, units)
        except Exception as exc:  # noqa: BLE001
            _map_debug('battle map FAILED: %s\n%s' % (exc, traceback.format_exc()))
            canvas.create_text(width / 2, height / 2,
                               text='地圖繪製失敗：%s（詳見 /tmp/hub-map-debug.log）'
                                    % type(exc).__name__,
                               fill='#ffffff', font=(self.face, 11, 'bold'))

    def _battle_paint_map(self, canvas, width, height, cities, units):
        view = self._battle_view(width, height)
        if view is None:
            canvas.create_text(width / 2, height / 2, text='地圖底圖不可用（%s）' % map_error(),
                               fill='#ffffff', font=(self.face, 11, 'bold'))
            return
        photo, pos, project, cam = view
        img_item = canvas.create_image(pos[0], pos[1], image=photo, anchor='nw')
        # 2026-10-20：畫面整張往下偏（內容被畫到畫布底部），先把畫布的捲動狀態
        # 寫進 log，才能分辨是「相機算錯」還是「Tk 畫布自己捲了」。
        try:
            _map_debug('battle canvas geom=%sx%s scrollregion=%s xview=%s yview=%s '
                       'origin=(%s,%s) '
                       'img_item=%s coords=%s winfo_h=%s' % (
                           canvas.winfo_width(), canvas.winfo_height(),
                           tuple(round(float(v)) for v in
                                 canvas.tk.splitlist(canvas.cget('scrollregion'))),
                           tuple(round(float(v), 4) for v in canvas.xview()),
                           tuple(round(float(v), 4) for v in canvas.yview()),
                           canvas.canvasx(0), canvas.canvasy(0),
                           img_item, tuple(round(float(v), 1) for v in canvas.coords(img_item)),
                           canvas.winfo_height()))
        except Exception as exc:  # noqa: BLE001
            _map_debug('battle canvas geom FAILED: %s' % (exc,))
        # 1x 時地圖比畫布窄，加一圈邊框才不會像「貼歪的圖」
        canvas.create_rectangle(pos[0], pos[1], pos[0] + cam['draw'][2], pos[1] + cam['draw'][3],
                                outline='#0f1710', width=1)
        _map_debug('battle draw canvas=%sx%s layer=mbm zoom=%.3f scale=%.4f fit=%.4f '
                   'cam=(%.1f,%.1f) want=(%.1f,%.1f) box=(%.1f,%.1f,%.1f,%.1f) '
                   'draw=(%.1f,%.1f,%.1f,%.1f) photo=%sx%s items=%s' % (
                       width, height, cam['zoom'], cam['scale'], cam['fit'],
                       cam['cx'], cam['cy'], cam['want_cx'], cam['want_cy'],
                       cam['box'][0], cam['box'][1], cam['box'][2], cam['box'][3],
                       cam['draw'][0], cam['draw'][1], cam['draw'][2], cam['draw'][3],
                       getattr(photo, 'width', lambda: '?')(), getattr(photo, 'height', lambda: '?')(),
                       len(canvas.find_all())))
        palette = {1: '#c0392b', 2: '#2b5fa8', 3: '#2f7a3f', 4: '#8a5a1f', 5: '#6b3fa0',
                   6: '#a0457a', 7: '#1f7a7a', 8: '#7a5c1f', 9: '#4a4a9a'}
        # 城池：方塊一定畫，名稱重疊就跳過（1x 一次 92 座，全畫會糊成一團）
        labels = []
        for city in cities:
            xy = map_xy(city.get('xy'))
            if xy is None:
                continue
            px, py = project(xy)
            if not (-20 <= px <= width + 20 and -20 <= py <= height + 20):
                continue
            canvas.create_rectangle(px - 4, py - 4, px + 4, py + 4,
                                    fill=palette.get(city.get('owner'), '#555555'),
                                    outline='#ffffff')
            name = str(city.get('name') or '')
            if name and self._map_label_fits(labels, px, py, name, width, height):
                self._map_label(canvas, px, py - 9, name)
        for unit in units:
            xy = map_xy(unit.get('xy'))
            if xy is None:
                continue
            px, py = project(xy)
            if not (-20 <= px <= width + 20 and -20 <= py <= height + 20):
                continue
            canvas.create_oval(px - 3, py - 3, px + 3, py + 3,
                               fill=palette.get(unit.get('owner'), '#333333'),
                               outline='#ffe08a')
        seen_x = min(100, round(cam['view'][0] / max(1.0, float(cam['iw'])) * 100))
        seen_y = min(100, round(cam['view'][1] / max(1.0, float(cam['ih'])) * 100))
        self._map_hint(canvas,
                       '滾輪縮放 %.1fx（可見 %d%%×%d%%）· 拖曳／WASD 平移 · 雙擊復原' % (
                           self.battle_zoom, seen_x, seen_y),
                       width, height)

    def _map_font(self, size=9, bold=True):
        """地圖用的字型（快取，不要每次重畫都建一次）。"""
        fonts = getattr(self, '_map_fonts', None)
        if fonts is None:
            fonts = self._map_fonts = {}
        key = (size, bold)
        font = fonts.get(key)
        if font is None:
            from tkinter import font as tkfont
            try:
                font = tkfont.Font(family=self.face, size=size,
                                   weight='bold' if bold else 'normal')
            except Exception:  # noqa: BLE001
                font = (self.face, size, 'bold' if bold else 'normal')
            fonts[key] = font
        return font

    def _map_label_fits(self, placed, px, py, text, width, height):
        """名稱是否放得下：不壓到已經畫過的名稱、不出界。"""
        font = self._map_font(9)
        try:
            tw = font.measure(text)
            th = font.metrics('linespace')
        except Exception:  # noqa: BLE001
            tw, th = 9 * len(text), 12
        left, right = px - tw / 2.0 - 1, px + tw / 2.0 + 1
        top, bottom = py - th - 1, py + 1
        if right < 0 or left > width or bottom < 0 or top > height:
            return False
        for other in placed:
            if left < other[2] and other[0] < right and top < other[3] and other[1] < bottom:
                return False
        placed.append((left, top, right, bottom))
        return True

    def _map_label(self, canvas, px, py, text):
        """白字加深色描邊（地形很花，單靠白字看不清楚）。"""
        font = self._map_font(9)
        for dx, dy in ((1, 1), (-1, 1), (1, -1)):
            canvas.create_text(px + dx, py + dy, text=text, fill='#101a12', font=font)
        canvas.create_text(px, py, text=text, fill='#ffffff', font=font)

    def _map_hint(self, canvas, text, width, height):
        """左下角操作提示：先鋪一條深色底，白字才看得見。"""
        font = self._map_font(9, bold=False)
        try:
            tw = font.measure(text)
            th = font.metrics('linespace')
        except Exception:  # noqa: BLE001
            tw, th = 9 * len(text), 14
        x0, y0 = 8, height - th - 12
        canvas.create_rectangle(x0, y0, x0 + tw + 14, y0 + th + 6,
                                fill='#1d2a1f', outline='')
        canvas.create_text(x0 + 7, y0 + 3, anchor='nw', text=text,
                           fill='#eef3e6', font=font)

    def _battle_geometry(self, width, height):
        """戰場地圖的幾何（不碰 Tk 物件，方便測試）。

        回傳 (key, pos, project, cam, crop)：
          key   快取鍵（含裁切區與畫上畫布的尺寸）
          pos   圖塊在畫布上的左上角
          project 世界格 → 畫布座標
          cam   相機（見 map_camera；單位是原作地面像素）
          crop  (x0, y0, x1, y1, dw, dh)：裁哪一塊原作地面、畫多大
        """
        size = map_size()
        if not size:
            return None
        iw, ih = size
        cam = map_camera(iw, ih, width, height, self.battle_zoom,
                         self.battle_cx, self.battle_cy)
        left, top, right, bottom = cam['box']
        x0 = max(0, min(iw - 1, int(round(left))))
        y0 = max(0, min(ih - 1, int(round(top))))
        x1 = max(x0 + 1, min(iw, int(round(right))))
        y1 = max(y0 + 1, min(ih, int(round(bottom))))
        dw = max(1, int(round(cam['draw'][2])))
        dh = max(1, int(round(cam['draw'][3])))
        key = ('battle', iw, ih, x0, y0, x1, y1, dw, dh)

        def project(xy):
            return map_project(xy, cam, width, height)

        return key, (cam['draw'][0], cam['draw'][1]), project, cam, (x0, y0, x1, y1, dw, dh)

    def _battle_view(self, width, height):
        """回傳 (photo, pos, project, cam)。

        底圖一律等比（不變形）；zoom=1 整張置中；放大時只看得到畫布範圍 ÷ 倍率
        那一塊原作地面，倍率連續、置中縮放不位移。
        """
        geo = self._battle_geometry(width, height)
        if geo is None:
            return None
        key, pos, project, cam, crop = geo
        from PIL import ImageTk
        photo = self._battle_photos.get(key)
        if photo is None:
            x0, y0, x1, y1, dw, dh = crop
            img = map_render((x0, y0, x1, y1), dw, dh)
            if img is None:
                return None
            photo = ImageTk.PhotoImage(img, master=self.battle_map)
            self._battle_photos[key] = photo
            while len(self._battle_photos) > 8:
                self._battle_photos.pop(next(iter(self._battle_photos)))
        self._battle_photo = photo
        self._battle_photo_key = key
        return photo, pos, project, cam

    def _battle_set_zoom(self, factor, anchor=None):
        """滾輪縮放：以**游標底下那一點**為軸等比縮放。

        舊版兩個問題：
          1. zoom<=1 走 contain、zoom>1 走「切畫布比例」分支，兩邊倍率對不上：
             1.0→1.0002 會讓地圖從 1.03x 突然跳成 1.72x（畫面整個被拉走）。
          2. 以畫布中心為軸：游標在上半部時，一放大內容就往游標下方滑走，
             使用者看到的就是「一滾地圖就往下移」。
        現在只有一條路徑：scale = contain 倍率 × zoom，而且縮放軸跟著游標
        （沒有游標座標時才用畫布中心）。

        2026-10-20 補上相機夾邊界：縮放後把相機中心夾到「新倍率」的合法
        範圍再存回去，舊的「想去的中心」不會留在地圖外，下一次縮放才不會
        突然跳版。
        """
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            return
        if not factor > 0:
            return
        size = map_size()
        width, height = self._canvas_size(self.battle_map, 360, 160, (720, 230))
        before = self.battle_zoom
        after = map_zoom(before * factor)
        if size and anchor is not None and after != before:
            iw, ih = size
            cam = map_camera(iw, ih, width, height, before,
                             self.battle_cx, self.battle_cy)
            ax, ay = float(anchor[0]), float(anchor[1])
            mx, my = map_unproject(ax, ay, cam, width, height)
            scale = cam['fit'] * after
            # 讓 (mx,my) 縮放後仍然落在游標那一點
            want_x = mx - (ax - width / 2.0) / scale
            want_y = my - (ay - height / 2.0) / scale
            self.battle_cx, self.battle_cy = map_clamp_center(
                iw, ih, width, height, after, want_x, want_y)
        self.battle_zoom = after
        _map_debug('battle zoom %.3f -> %.3f (factor=%.3f anchor=%s) cam=(%.1f,%.1f)' % (
            before, after, factor, anchor, self.battle_cx or 0.0, self.battle_cy or 0.0))
        self._battle_redraw()

    def _battle_wheel(self, event, anchor=None):
        """滾輪：把 delta 換成步數（1 步 = ×1.2），一個手勢不再連跳十幾格。

        另外加上 40 ms 的節流（跟 app/panorama_map.py 的全景地圖一致）：
        觸控板一次滑動會送十幾個小事件，沒有節流的話倍率會直接衝到上限。
        """
        steps = wheel_steps(getattr(event, 'delta', 0) or 0)
        if not steps:
            return 'break'
        now = time.monotonic()
        if now - getattr(self, '_battle_wheel_at', 0.0) < MAP_WHEEL_THROTTLE:
            return 'break'
        self._battle_wheel_at = now
        self._battle_set_zoom(1.2 ** steps,
                              anchor=anchor if anchor is not None else (
                                  getattr(event, 'x', 0), getattr(event, 'y', 0)))
        return 'break'

    def _battle_pan(self, dx, dy):
        """WASD 平移：每次移動「可見範圍」的 10%，並夾在合法範圍內。

        舊版用固定的 ``0.1 * 底圖高 / zoom``，在寬畫布上步幅跟畫面脫節；
        而且平移量沒有跟可見範圍綁定，越界時相機被硬夾 → 感覺「按了沒反應」。
        """
        size = map_size()
        if size is None:
            return
        iw, ih = size
        width, height = self._canvas_size(self.battle_map, 360, 160, (720, 230))
        cam = map_camera(iw, ih, width, height, self.battle_zoom,
                         self.battle_cx, self.battle_cy)
        step_x = 0.10 * cam['view'][0]
        step_y = 0.10 * cam['view'][1]
        base_x = self.battle_cx if self.battle_cx is not None else iw / 2.0
        base_y = self.battle_cy if self.battle_cy is not None else ih / 2.0
        self.battle_cx, self.battle_cy = map_clamp_center(
            iw, ih, width, height, self.battle_zoom,
            base_x + dx * step_x, base_y + dy * step_y)
        _map_debug('battle pan dx=%s dy=%s step=(%.1f,%.1f) cam=(%.1f,%.1f) zoom=%.3f' % (
            dx, dy, step_x, step_y, self.battle_cx, self.battle_cy, self.battle_zoom))
        self._battle_redraw()

    def _battle_drag_start(self, event):
        """拖曳平移：按下滑鼠開始拖地圖（全景地圖也有這套）。"""
        size = map_size()
        iw, ih = size if size else (0, 0)
        cx = self.battle_cx if self.battle_cx is not None else iw / 2.0
        cy = self.battle_cy if self.battle_cy is not None else ih / 2.0
        self._battle_drag = (float(event.x), float(event.y), cx, cy)

    def _battle_drag_move(self, event):
        """拖曳中：地圖跟著游標走（1 畫布像素 = 1/scale 個底圖像素）。"""
        drag = getattr(self, '_battle_drag', None)
        if not drag:
            return
        x0, y0, cx0, cy0 = drag
        dx = float(event.x) - x0
        dy = float(event.y) - y0
        if abs(dx) + abs(dy) < 4:
            return
        size = map_size()
        if size is None:
            return
        iw, ih = size
        width, height = self._canvas_size(self.battle_map, 360, 160, (720, 230))
        cam = map_camera(iw, ih, width, height, self.battle_zoom,
                         self.battle_cx, self.battle_cy)
        # 往右拖 → 地圖跟著往右走 → 相機中心往左移
        self.battle_cx, self.battle_cy = map_clamp_center(
            iw, ih, width, height, self.battle_zoom,
            cx0 - dx / cam['scale'], cy0 - dy / cam['scale'])
        self._battle_redraw()

    def _battle_drag_end(self, event=None):
        self._battle_drag = None

    def _battle_reset_view(self):
        if hasattr(self, 'battle_panel'):
            return self.battle_panel.fit()
        """復原視角：1x 整張地圖置中（相機回到原作地面中心）。"""
        self.battle_zoom = MAP_MIN_ZOOM
        self.battle_cx, self.battle_cy = map_world_center()
        _map_debug('battle reset view -> zoom=1.0 cam=(%.1f,%.1f)' % (
            self.battle_cx, self.battle_cy))
        self._battle_redraw()

    def _battle_key(self, dx, dy):
        def handler(event=None):
            self._battle_pan(dx, dy)
            return 'break'
        return handler

    def _on_tab_changed(self, event=None):
        try:
            current = str(self.control_book.select())
            if current == str(self.battle_page):
                self.root.after(60, self._battle_redraw)
            elif current == str(self.command_page):
                self.root.after(60, self._cmd_draw_map)
        except Exception:  # noqa: BLE001
            pass

    def _battle_redraw(self):
        if hasattr(self, 'battle_panel'):
            return self.battle_panel.redraw()
        last = getattr(self, '_battle_last', None)
        if last:
            self._battle_draw_map(*last)
        else:
            # 還沒讀到遊戲資料也要能看地圖（縮放不需要遊戲資料）。
            self._battle_draw_map([], [], {})

    def _build_room_controls(self):
        box = self._box(self.room_control_page, '風夜進房與準備')
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
        self.room_search = tk.Button(bar, text='更新房間', bg=BG,
                                     command=lambda: self.room_action({'op': 'search'}))
        self.room_search.pack(side='left')
        tk.Label(bar, text='進房暱稱', bg=DAMASK, fg=INK).pack(side='left', padx=(12, 5))
        self.room_nick_combo = ttk.Combobox(bar, textvariable=self.room_nickname, width=12,
                                          values=['待秋至', '風夜', '小白'], state='normal')
        self.room_nick_combo.pack(side='left')
        self.room_join = tk.Button(bar, text='進入所選房間', bg=BG, command=self.join_selected_room)
        self.room_join.pack(side='left', padx=5)
        self.room_leave = tk.Button(bar, text='離開房間', bg=BG,
                                    command=lambda: self.room_action({'op': 'leave'}))
        self.room_leave.pack(side='left')
        self.room_stop = tk.Button(bar, text='風夜下線', bg=BG,
                                   command=lambda: self.room_action({'op': 'stop'}))
        self.room_stop.pack(side='left', padx=5)
        flow = tk.Frame(probe_box, bg=DAMASK)
        flow.pack(fill='x', padx=8, pady=(0, 8))
        self.room_register = tk.Button(flow, text='完成報到', bg=BG, command=self.register_ghost)
        self.room_register.pack(side='left')
        self.room_d8 = tk.Button(flow, text='讓風夜藏好', bg=BG, command=self.withdraw_ghost)
        self.room_d8.pack(side='left', padx=8)
        self.room_retry = tk.Button(flow, text='↻ 重新來過', bg=BG, command=self.one_click_retry)
        self.room_retry.pack(side='left')
        self.room_flow_label = tk.Label(flow, bg=DAMASK, fg=MUTED)
        self.room_flow_label.pack(side='left', padx=8)
        lab = tk.Frame(box, bg=DAMASK)
        lab.pack(fill='x', padx=12, pady=(2, 12))
        tk.Button(lab, text='讓風夜進房', bg='#cbe7e4', fg='#164d51', command=self.lab_arm,
                  font=(self.face, 12, 'bold')).pack(side='left')
        tk.Button(lab, text='風夜下線', bg=BG, command=self.lab_stop).pack(side='left', padx=8)
        tk.Button(lab, text='查看風夜狀態', bg=BG, command=self.lab_status).pack(side='left')
        tk.Button(lab, text='卡住了？強制結束', bg='#f7e5e5', fg=WARN,
                  command=self.lab_force_quit).pack(side='left', padx=8)
        self.probe_toggle = tk.Button(lab, text='手動進房設定', bg=BG, command=self._toggle_probe_layer)
        self.probe_toggle.pack(side='right')
        # 2026-10-19 半自動進房：搜索房間（借探針）→ 清單選房（單房自動）→ 用指定暱稱走完整武裝進房。
        semi = tk.Frame(box, bg=DAMASK)
        semi.pack(fill='x', padx=12, pady=(0, 12))
        tk.Button(semi, text='搜索房間', bg=BG, command=self.lab_search_rooms).pack(side='left')
        tk.Label(semi, text='進房暱稱', bg=DAMASK, fg=INK).pack(side='left', padx=(12, 4))
        self.lab_nickname = tk.StringVar(value='待秋至')
        ttk.Combobox(semi, textvariable=self.lab_nickname, width=10,
                     values=['待秋至', '風夜', '小白'], state='normal').pack(side='left')
        tk.Button(semi, text='進入所選房間', bg='#cbe7e4', fg='#164d51',
                  command=self.lab_enter_selected).pack(side='left', padx=10)
        tk.Label(semi, text='（先搜索：下方清單選房；只有一間時自動選）', bg=DAMASK, fg=MUTED).pack(side='left')
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
        self.state_panel.pack(fill='x', padx=12, pady=(0, 12))
        tk.Label(self.state_panel, text='風夜現在的狀態', bg=WELL, fg=INK,
                 font=(self.face, 13, 'bold'), anchor='w').pack(fill='x', padx=14, pady=(10, 6))
        self.state_rows = tk.Frame(self.state_panel, bg=WELL)
        self.state_rows.pack(fill='x', padx=14, pady=(0, 10))
        tk.Label(self.state_rows, text='還沒有風夜的即時狀態。', bg=WELL, fg=MUTED,
                 anchor='w').pack(fill='x')
        self.room_tree = self.tree(box, [('name', '房間名稱', 220), ('host', '房主', 180), ('count', '目前人數', 100)])
        self.room_tree.configure(height=6)
        self.room_tree.bind('<<TreeviewSelect>>', lambda _e: self.update_room_controls())
        self.room_empty = tk.Label(self.room_tree, text='還沒有房間資料\n先請房主建好房間，再讓風夜進房。',
                                   bg=WELL, fg=MUTED, font=(self.face, 13), justify='center')
        self.room_empty.place(relx=.5, rely=.5, anchor='center')
        self.room_status = tk.Label(box, bg=DAMASK, fg=MUTED, anchor='w', justify='left', wraplength=1080)
        self.room_status.pack(fill='x', padx=14, pady=10)
        self.room_channel = tk.Label(box, bg=WELL, fg=INK, anchor='w', justify='left', wraplength=1080,
                                     font=(self.face, 12), padx=14, pady=12)
        self.room_channel.pack(fill='x', padx=12, pady=(0, 10))
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
        state = self.rooms.state
        if not (state.get('fresh') and state.get('connected')):
            return
        if not messagebox.askokcancel('風夜藏身',
                                      '把風夜從名單中藏起來：這樣遊戲開局時不會等風夜，\n'
                                      '風夜可以一直暗中旁聽（名單會出現一行「風夜从游戏中退出了」）。\n'
                                      '請在遊戲按「開始」之前完成；只送一次、失敗不重試。確認執行？', parent=self.root):
            return
        self.room_action({'op': 'd8'})

    # ---- 風雲・本機控制（0.2.15）與實驗室一鍵（新流程） ----

    def _local_async(self, widget, label, func):
        def work():
            try:
                result = func()
            except Exception as error:
                result = {'status': 'error', 'error': '{}: {}'.format(type(error).__name__, error)}
            text = operation_result(label, result)

            def show():
                widget.configure(text=text[:2200])
            self.root.after(0, show)

        widget.configure(text=label + '…執行中（請稍候）')
        threading.Thread(target=work, daemon=True, name='fengyun-local').start()

    def local_login(self):
        self.local_state_label.configure(text='⏳ 登入中……（幾秒後自動顯示結果）', fg=INK)

        def work():
            try:
                result = fengyun_local.login(line=self.local_line.get())
            except Exception as error:
                result = {'status': 'error', 'error': '{}: {}'.format(type(error).__name__, error)}

            def show():
                if result.get('status') == 'already_online':
                    self.local_state_label.configure(text=f'{fengyun_local.DISPLAY_NAME}已在線，不用重複登入。', fg='#2f6a4f')
                    detail = '請切回現有遊戲視窗。'
                    rooms = result.get('rooms') or []
                    if rooms:
                        detail = (detail + '\n' if detail else '') + '房間列表：' + '、'.join(rooms)
                    self.local_status_label.configure(text=detail[:2200])
                else:
                    self.local_status_label.configure(
                        text=operation_result('進入遊戲', result))
                    self.root.after(6000, self.local_state_refresh)
                    self.root.after(15000, self.local_state_refresh)
            self.root.after(0, show)
        threading.Thread(target=work, daemon=True, name='fengyun-login').start()

    def local_exit(self):
        self._local_async(self.local_status_label, f'結束{fengyun_local.DISPLAY_NAME}遊戲', fengyun_local.exit_soft)

    def local_kill(self):
        if not messagebox.askokcancel('強制關閉遊戲',
                                      '只會關閉這台電腦上的玩家遊戲，大廳保持開啟。未儲存的進度會遺失。確定繼續？',
                                      parent=self.root):
            return
        self._local_async(self.local_status_label, '強制關閉遊戲', fengyun_local.force_kill)

    def local_status(self):
        self._local_async(self.local_status_label, '本機狀態', fengyun_local.status)

    def local_state_refresh(self):
        if getattr(self, '_local_state_busy', False):
            return
        self._local_state_busy = True

        def work():
            try:
                result = fengyun_local.live_status()
            except Exception as error:
                result = {'state': 'error', 'headline': '狀態讀取失敗', 'detail': str(error)}

            def show():
                self._local_state_busy = False
                self._render_local_state(result)
            self.root.after(0, show)
        threading.Thread(target=work, daemon=True, name='fengyun-state').start()

    def _render_local_state(self, result):
        title, detail = local_state(result)
        state = result.get('state')
        self.local_state_label.configure(text=title, fg=GOLD if state == 'holding' else INK)
        self.local_status_label.configure(text=detail)

    def local_slots_read(self):
        self._local_slot_async(f'正在查看{fengyun_local.DISPLAY_NAME}對應的玩家',
                               lambda: fengyun_local.setforce('read'))

    def local_slot_set(self, slot):
        self._local_slot_async(f'切換{fengyun_local.DISPLAY_NAME}對應的玩家',
                               lambda: fengyun_local.setforce('switch', slot))

    def local_slot_restore(self):
        self._local_slot_async(f'切回{fengyun_local.DISPLAY_NAME}上一位玩家',
                               lambda: fengyun_local.setforce('restore'))

    def _local_slot_async(self, label, func):
        """本機席位操作：結果用與風夜相同的「名稱＋勢力」格式化顯示。"""
        def work():
            try:
                result = func()
            except Exception as error:
                result = {'status': 'error', 'error': '{}: {}'.format(type(error).__name__, error)}
            text = self._format_force(label, result)

            def show():
                self.local_slot_label.configure(text=text[:2200])
                self._update_slot_buttons(result)
            self.root.after(0, show)

        self.local_slot_label.configure(text=label + '，請稍候。')
        threading.Thread(target=work, daemon=True, name='fengyun-force').start()

    def _fengye_slot_async(self, label, script):
        def work():
            try:
                result = lab_remote(self.source.sources.host, script, timeout=180)
            except Exception as error:
                result = {'rc': -1, 'stderr': str(error)}
            text = self._format_force(label, result)

            def show():
                self.fengye_slot_label.configure(text=text[:2200])
                self._update_slot_buttons(result)
            self.root.after(0, show)

        self.fengye_slot_label.configure(text=label + '，請稍候。')
        threading.Thread(target=work, daemon=True, name='fengye-force').start()

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

    def fengye_slot_read(self):
        self._fengye_slot_async('正在查看風夜對應的玩家',
                                'cd ~/sgi-protocol-lab-20260915/shadow && bash shadow_force.sh read')

    def fengye_slot_set(self, slot):
        self._fengye_slot_async('切換風夜對應的玩家',
                                'cd ~/sgi-protocol-lab-20260915/shadow && bash shadow_force.sh switch {}'.format(slot))

    def fengye_slot_restore(self):
        self._fengye_slot_async('切回風夜上一位玩家',
                                'cd ~/sgi-protocol-lab-20260915/shadow && bash shadow_force.sh restore')

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

    def lab_search_rooms(self):
        """半自動①：借探針登入並搜房；搜完自動收線，把風夜帳號讓給武裝客戶端。"""
        state = self.rooms.state
        if state.get('alive') and state.get('phase') == 'lobby' and not state.get('connected'):
            self.room_action({'op': 'search'})
            self.root.after(1500, self._lab_release_probe)
        else:
            self.room_action({'op': 'start', 'line': self.room_line.get()})
            self.root.after(400, self._lab_search_when_lobby)

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
        env = ''
        if room_name:
            env += 'JOIN_NAME={} '.format(shlex.quote(room_name))
        if nickname:
            env += 'JOIN_NICKNAME={} '.format(shlex.quote(nickname))
        lab = self._lab_root()
        self._lab_async('風夜進房準備',
                        'cd {} && {}bash arm_now.sh'.format(shlex.quote(str(lab)), env))

    def lab_arm(self):
        if not messagebox.askokcancel('讓風夜進房？',
                                      '請先讓房主建好房間。\n'
                                      '這會結束風夜先前的連線，再重新進房並做好開局準備。\n'
                                      '準備期間先別按「開始」，等情報台通知可以開始。確定繼續？',
                                      parent=self.root):
            return
        self._lab_arm()

    def lab_stop(self):
        self._lab_async('讓風夜下線',
                        'cd ~/sgi-protocol-lab-20260915/shadow && bash stop_shadow.sh',
                        timeout=90)

    def lab_force_quit(self):
        if not messagebox.askokcancel('風夜卡住了？',
                                      '這會強制關閉風夜的遊戲與相關連線。\n'
                                      '正常離開請用「風夜下線」；只有卡住、無法正常離開時才使用這個按鈕。確定繼續？',
                                      parent=self.root):
            return
        self._lab_async('強制結束風夜',
                        'cd ~/sgi-protocol-lab-20260915/shadow && bash shadow_force_quit.sh',
                        timeout=120)

    def lab_status(self):
        script = (
            "cd ~/sgi-protocol-lab-20260915/shadow\n"
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

    def _build_lab_page(self):
        # 2026-10-20 使用者要求：把 p63 的自然斷線做成一顆按鈕。破壞性操作，
        # 每次都要在對話框確認；風夜（旁聽端）不在目標清單。
        box = self._box(self.lab_page, '實驗室 · 讓對手掉線（自然斷線）')
        box.pack(fill='x', padx=14, pady=14)
        tk.Label(box, text='選一位本機玩家，送出一次程序內退出。對方會立刻斷線；'
                           '約 30–40 秒主機顯示「無法重新連線／退出」。'
                           '每次執行都要確認，失敗不重試。',
                 bg=DAMASK, fg=MUTED, anchor='w', justify='left',
                 wraplength=1000).pack(fill='x', padx=12, pady=(10, 6))
        bar = tk.Frame(box, bg=DAMASK)
        bar.pack(fill='x', padx=12, pady=6)
        tk.Label(bar, text='目標：', bg=DAMASK, fg=INK).pack(side='left')
        self.drop_target = tk.StringVar(value='丁滿（主機）')
        ttk.Combobox(bar, textvariable=self.drop_target, width=18, state='readonly',
                     values=['丁滿（主機）', '風雲']).pack(side='left', padx=6)
        self.drop_button = tk.Button(bar, text='讓對手掉線', bg='#f7e5e5', fg=WARN,
                                     command=self.drop_client)
        self.drop_button.pack(side='left', padx=10)
        tk.Button(bar, text='檢查本機客戶端', bg=BG, command=self.drop_check).pack(side='right')
        self.drop_label = tk.Label(box, text='', bg=WELL, fg=INK, anchor='w', justify='left',
                                   wraplength=1000, padx=12, pady=10)
        self.drop_label.pack(fill='x', padx=12, pady=(6, 12))
        tk.Label(self.lab_page, text='其他實驗室工具（D8 摘席、回合跟隨）仍在既有頁面與 CLI；'
                                     '這裡只放需要二次確認的破壞性操作。',
                 bg=DAMASK, fg=MUTED, anchor='w', justify='left',
                 wraplength=1000).pack(fill='x', padx=20, pady=(0, 10))

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

    def _build_local_controls(self):
        page = tk.Frame(self.control_book, bg=DAMASK)
        self.control_book.add(page, text='玩家與遊戲')
        box = self._box(page, f'{fengyun_local.DISPLAY_NAME}遊戲 · 這台電腦')
        box.pack(fill='x', padx=10, pady=10)
        bar = tk.Frame(box, bg=DAMASK)
        bar.pack(fill='x', padx=8, pady=6)
        self.local_line = tk.StringVar(value='多线3（备用）')
        ttk.Combobox(bar, textvariable=self.local_line, width=14,
                     values=['多线3（备用）', '多线2（主线）'], state='readonly').pack(side='left')
        tk.Button(bar, text='進入遊戲', bg=BG, command=self.local_login).pack(side='left', padx=6)
        tk.Button(bar, text='結束遊戲', bg=BG, command=self.local_exit).pack(side='left')
        tk.Button(bar, text='強制結束', bg='#ead4c6', fg=WARN, command=self.local_kill).pack(side='left', padx=6)
        tk.Button(bar, text='更新狀態', bg=BG, command=self.local_state_refresh).pack(side='right')
        self.local_state_label = tk.Label(box, bg=WELL, fg=MUTED, anchor='w', justify='left',
                                          wraplength=1080, font=(self.face, 12, 'bold'))
        self.local_state_label.pack(fill='x', padx=8, pady=(6, 0))
        self.local_status_label = tk.Label(box, bg=WELL, fg=INK, anchor='w', justify='left', wraplength=1080)
        self.local_status_label.pack(fill='x', padx=8, pady=(0, 6))
        box2 = self._box(page, f'{fengyun_local.DISPLAY_NAME} · 切換對應的玩家')
        box2.pack(fill='x', padx=10, pady=(0, 10))
        bar2 = tk.Frame(box2, bg=DAMASK)
        bar2.pack(fill='x', padx=8, pady=6)
        tk.Button(bar2, text='更新可選玩家', bg=BG, command=self.local_slots_read).pack(side='left')
        tk.Label(bar2, text='切換到：', bg=DAMASK, fg=INK).pack(side='left', padx=(12, 4))
        self.local_slot_buttons = {}
        local_choices = tk.Frame(box2, bg=DAMASK)
        local_choices.pack(fill='x', padx=8, pady=6)
        for slot in range(8):
            local_choices.columnconfigure(slot % 4, weight=1)
            btn = tk.Button(local_choices, text='等待玩家名單', bg=BG, state='disabled',
                            command=lambda value=slot: self.local_slot_set(value))
            btn.grid(row=slot // 4, column=slot % 4, sticky='ew', padx=3, pady=3)
            btn.grid_remove()
            self.local_slot_buttons[slot] = btn
        tk.Button(bar2, text='切回上一位', bg=BG, command=self.local_slot_restore).pack(side='left', padx=10)
        self.local_slot_label = tk.Label(box2, text='開局後，按「更新可選玩家」即可看到玩家與勢力名稱。', bg=WELL, fg=INK, anchor='w', justify='left', wraplength=1080)
        self.local_slot_label.pack(fill='x', padx=8, pady=(0, 6))
        box3 = self._box(page, '風夜 · 切換對應的玩家')
        box3.pack(fill='x', padx=10, pady=(0, 10))
        bar3 = tk.Frame(box3, bg=DAMASK)
        bar3.pack(fill='x', padx=8, pady=6)
        tk.Button(bar3, text='更新可選玩家', bg=BG, command=self.fengye_slot_read).pack(side='left')
        tk.Label(bar3, text='切換到：', bg=DAMASK, fg=INK).pack(side='left', padx=(12, 4))
        self.fengye_slot_buttons = {}
        fengye_choices = tk.Frame(box3, bg=DAMASK)
        fengye_choices.pack(fill='x', padx=8, pady=6)
        for slot in range(8):
            fengye_choices.columnconfigure(slot % 4, weight=1)
            btn = tk.Button(fengye_choices, text='等待玩家名單', bg=BG, state='disabled',
                            command=lambda value=slot: self.fengye_slot_set(value))
            btn.grid(row=slot // 4, column=slot % 4, sticky='ew', padx=3, pady=3)
            btn.grid_remove()
            self.fengye_slot_buttons[slot] = btn
        tk.Button(bar3, text='切回上一位', bg=BG, command=self.fengye_slot_restore).pack(side='left', padx=10)
        self.fengye_slot_label = tk.Label(box3, text='開局後，按「更新可選玩家」即可看到玩家與勢力名稱。', bg=WELL, fg=INK, anchor='w', justify='left', wraplength=1080)
        self.fengye_slot_label.pack(fill='x', padx=8, pady=(0, 6))
        tk.Label(page, text='先進入對局，再選擇要對應的玩家。切換結果請同時查看遊戲畫面；尚未取得名字時，不提供數字按鈕猜選。',
                 bg=DAMASK, fg=MUTED, anchor='w', justify='left', wraplength=1080).pack(fill='x', padx=14, pady=(0, 10))
        if not FORCE_SWITCH_UI:
            # 暫時關閉席位切換面板（兩行一起收起）；底層工具仍可用 CLI 操作。
            for widget in (box2, box3):
                try:
                    widget.pack_forget()
                except Exception:
                    pass
            for widget in page.winfo_children():
                try:
                    if isinstance(widget, tk.Label) and widget.cget('text').startswith('先進入對局'):
                        widget.pack_forget()
                except Exception:
                    pass
        if not self.source.sources.source_file and FORCE_SWITCH_UI:
            self.local_state_refresh()
            self.fengye_slot_read()

    def room_action(self, payload):
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
        self.room_status.configure(text=text)
        headline, hint = room_summary(state)
        self.room_channel.configure(text=headline + '\n' + hint)
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
        self.retry = {'steps': steps, 'deadline': time.monotonic() + 180, 'start_retries': 0,
                      'label': '一鍵上場'}
        self.retry_next()

    def one_click_retry(self):
        """失敗後一鍵收尾重來：退房→收線→重登→查房→進入（接手自動註冊→摘席）。"""
        if self.source.sources.source_file:
            return
        if self.retry is not None:
            self.retry = None
            self.room_receipt.configure(text='已取消「重新來過」；按鈕恢復正常。')
            return
        state = self.rooms.state
        steps = []
        if state.get('connected'):
            steps.append('leave')
        if state.get('alive') or state.get('fresh'):
            steps.append('stop')
        steps += ['wait_teardown', 'start', 'wait_lobby', 'search', 'wait_rooms']
        self.retry = {'steps': steps, 'deadline': time.monotonic() + 150, 'start_retries': 0,
                      'label': '重新來過'}
        self.room_receipt.configure(text='重新來過：開始收尾（若遊戲裡有等待畫面，請按掉取消）…')
        self.retry_next()

    def retry_next(self):
        """推進「一鍵重來」流程；每步只發一次操作，結果經 _maybe_retry 續行。"""
        tag = (self.retry or {}).get('label', '重新來過')
        if self.retry is None:
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
        self._local_state_n = getattr(self, '_local_state_n', 0) + 1
        if self._local_state_n % 40 == 0 and not self.source.sources.source_file:
            try:
                self.local_state_refresh()
            except Exception:
                pass
        if not self.stop.is_set():
            self.root.after(250, self._tick_fengye)

    def render_status_panel(self, view):
        items = status_items(view)
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

    def render_view(self, view):
        p = view.get('p34') or {}
        session = view.get('session') or {}
        transport = (view.get('transport') or {}).get('status')
        self._render_capture_status()
        self.render_status_panel(view)
        signature = json.dumps({k: view.get(k) for k in ('p34', 'host', 'members', 'events', 'directory', 'room_query', 'chain', 'source', 'ghost', 'collector')}, ensure_ascii=False, sort_keys=True)
        if signature != self.render_signature:
            chats = (p.get('chat') or {}).get('messages') or []
            chat_text = '\n\n'.join('{}　{}\n{}'.format(wall_text(m.get('wall')),
                m.get('sender_name') or '—', str(m.get('text') or '—')) for m in chats) or (
                '本局尚無聊天記錄。' if session else '目前沒有可核實的聊天記錄。')
            self._set_text(self.console_chat, chat_text)
            if getattr(self, 'chat_history', None) is not None:
                self._set_text(self.chat_history, chat_text)
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
            # 但它的進程與局內資料仍在——用外部指令的同一個讀取結果判斷「在局中」。
            cmd = getattr(self, 'cmd_targets_data', None) or {}
            live = any(t.get('alive') for t in (cmd.get('targets') or [])
                       if '風夜' in str(t.get('label')))
            phase = cmd.get('phase')
            if live and isinstance(phase, int) and phase >= 0:
                headline = '✅ 風夜已在局中（監聽中；%s）' % (cmd.get('phase_text') or ('phase=%s' % phase))
            else:
                headline = '風夜尚未進房 · 先請房主建房，再讓風夜進房。'
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

