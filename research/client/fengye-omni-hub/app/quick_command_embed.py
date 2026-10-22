"""把「快速軍令」面板嵌進 Hub 的「指令」頁（不再另開獨立視窗）。

面板本體只有一份：``research/client/SGI-Hub-CrossOver-M4-0.2/app/quick_control.py``
（同一支程式仍可以用 ``啟動快捷修改面板.command`` 當獨立視窗開）。

這個模組只負責三件事：

1. 依**檔案路徑**載入那個面板模組。Hub 的 ``app/`` 底下另有一份舊的
   ``quick_control.py``（1.8.7），直接 ``import quick_control`` 會拿到錯的那份。
2. 提供 ``QuickPanelHost``：內容比頁面高時可以捲動的容器（面板展開
   「修改功能」時會變高）。
3. ``mount_quick_panel()`` 建立 ``Panel(embedded=True)`` 並回傳，讓 Hub 在
   關閉時呼叫 ``close()``（順便請 Wine 輔助程式退出）。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

HUB_APP = Path(__file__).resolve().parent          # .../fengye-omni-hub/app
HUB_ROOT = HUB_APP.parent                          # .../fengye-omni-hub
DEFAULT_PANEL_APP = HUB_ROOT.parent / 'SGI-Hub-CrossOver-M4-0.2' / 'app'
PANEL_MODULE = 'sgi_quick_control_panel'
PANEL_SCRIPT = 'quick_control.py'


def panel_app_dir(path=None):
    """面板所在的 app 目錄；可用環境變數 SGI_QUICK_PANEL_APP 覆寫（測試／換機器）。"""
    if path:
        return Path(path).expanduser()
    override = os.environ.get('SGI_QUICK_PANEL_APP')
    if override:
        return Path(override).expanduser()
    return DEFAULT_PANEL_APP


def panel_script(path=None):
    return panel_app_dir(path) / PANEL_SCRIPT


def load_panel_module(path=None):
    """載入真正的快速軍令面板模組（重複呼叫回同一個模組物件）。"""
    app = panel_app_dir(path)
    script = app / PANEL_SCRIPT
    if not script.is_file():
        raise FileNotFoundError('找不到快速軍令面板：%s' % script)
    loaded = sys.modules.get(PANEL_MODULE)
    if loaded is not None and Path(getattr(loaded, '__file__', '')) == script:
        return loaded
    # 面板本身會把 ROOT/bridge 插進 sys.path；這裡先補它自己的 app 目錄，
    # 讓 quick_control_model／quick_control_instance 等兄弟模組找得到。
    for folder in (app, app.parent / 'bridge'):
        entry = str(folder)
        if folder.is_dir() and entry not in sys.path:
            sys.path.append(entry)
    spec = importlib.util.spec_from_file_location(PANEL_MODULE, script)
    if spec is None or spec.loader is None:
        raise ImportError('快速軍令面板無法載入：%s' % script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[PANEL_MODULE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(PANEL_MODULE, None)
        raise
    module.PANEL_APP_DIR = app
    # quick_control.py 會在匯入時把 ROOT/bridge 插到 sys.path[0]。把它移到最後：
    # 面板需要的獨有模組（replay_modifications／quick_unit_focus）照樣找得到，
    # 但 Hub 後續的 import 仍然優先拿到 Hub 自己的模組，不會被同名的舊檔蓋掉。
    bridge = str(app.parent / 'bridge')
    if bridge in sys.path:
        sys.path[:] = [entry for entry in sys.path if entry != bridge] + [bridge]
    return module


def autoconnect_enabled():
    """預設自動連上本機對局；驗收時可設 SGI_QUICK_EMBED_AUTOCONNECT=0 只看畫面。"""
    value = os.environ.get('SGI_QUICK_EMBED_AUTOCONNECT', '1')
    return str(value).strip().lower() not in ('0', 'false', 'no', 'off')


class QuickPanelHost(tk.Frame):
    """頁面內的容器：面板比頁面高時出現右側捲軸，否則完全不留白邊。"""

    def __init__(self, master, bg):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', self._content_changed, add='+')
        self.canvas.bind('<Configure>', self._canvas_changed, add='+')
        self._scroll_shown = False
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>', '<TouchpadScroll>'):
            for widget in (self.canvas, self.inner):
                try:
                    widget.bind(sequence, self._wheel, add='+')
                except tk.TclError:      # 這個 Tk 沒有該事件（例如舊版沒有 TouchpadScroll）
                    pass

    # ------------------------------------------------------------ 捲動
    def _content_changed(self, _event=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        except tk.TclError:
            return
        self._sync_scrollbar()

    def _canvas_changed(self, event):
        try:
            self.canvas.itemconfigure(self.window, width=event.width)
        except tk.TclError:
            return
        self._sync_scrollbar()

    def _sync_scrollbar(self):
        try:
            needed = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2
        except tk.TclError:
            return
        if needed and not self._scroll_shown:
            self._scroll_shown = True
            self.scroll.pack(side='right', fill='y')
        elif not needed and self._scroll_shown:
            self._scroll_shown = False
            self.scroll.pack_forget()
            self.canvas.yview_moveto(0)

    def _wheel(self, event):
        if not self._scroll_shown:
            return None
        number = getattr(event, 'num', None)
        if number in (4, 5):
            step = -1 if number == 4 else 1
        else:
            delta = getattr(event, 'delta', 0) or 0
            if not delta:
                return None
            step = -1 if delta > 0 else 1
        self.canvas.yview_scroll(step * 2, 'units')
        return 'break'

    def scroll_to_top(self):
        try:
            self.canvas.yview_moveto(0)
        except tk.TclError:
            pass


def mount_quick_panel(parent, bg='#f3f6fa', autoconnect=None, module=None, smoke=False,
                      palette=None):
    """在 parent 裡建立可捲動的快速軍令面板，回傳 panel 物件。

    smoke=True 只給畫面驗收／單元測試：面板照樣建好，但不會啟動 Wine 輔助程式。
    palette 由呼叫端給（Hub 的淺藍白／墨綠）；不給就用面板內建的 HUB 配色。
    """
    if autoconnect is None:
        autoconnect = autoconnect_enabled()
    module = module or load_panel_module()
    host = QuickPanelHost(parent, bg=bg)
    host.pack(fill='both', expand=True)
    panel = module.Panel(host.inner, embedded=True, smoke=smoke, autoconnect=autoconnect,
                         palette=palette)
    panel.scroll_host = host
    return panel
