"""Copy an own-city wild-officer report for manual paste into native chat.

The match's standard Edit supports Control+V when the input has focus.
Copy fills the host and Windows clipboards without entering or sending chat.
"""
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from city_talent import city_wild_officers, lead_war_total, number_floor
from player_view import player_id

ROOT = Path(__file__).resolve().parents[1]

BLADE_MIN = 170
BG = '#f7f4ea'
INK = '#3f3420'
MUTED = '#675937'


def parse_blade_floor(text):
    """Blank means no floor. A bad number is False so the page can say so."""
    raw = str('' if text is None else text).strip()
    if not raw:
        return None
    value = number_floor(raw)
    return value if value is not None else False


def floor_phrase(floor):
    if floor is None:
        return '不限统武'
    shown = int(floor) if abs(floor - round(floor)) < 1e-9 else floor
    return f'统武大于 {shown}'


def qualifying_officers(officers, floor=BLADE_MIN):
    """Wild officers whose 统率＋武力 is strictly above the floor, strongest first."""
    picked = []
    for officer in officers or []:
        blade = lead_war_total(officer)
        if floor is None or (type(blade) is int and blade > floor):
            picked.append(officer)
    picked.sort(key=lambda officer: (
        lead_war_total(officer) or 0,
        officer.get('general_id_raw') or 0,
    ), reverse=True)
    return picked


def report_line(city_name, officers, total):
    names = ' '.join((officer.get('name') or '姓名未解码') for officer in officers)
    return f'{city_name} {names}  {len(officers)}/{total}'


def own_city_reports(state, floor=BLADE_MIN):
    """One line per own city that has a wild officer above the floor.

    The fraction is qualifying count over every wild officer in that city.
    """
    fid = player_id(state)
    if fid is None:
        return None
    entities = (state or {}).get('entities') or {}
    cities = entities.get('cities_and_barriers') or []
    ids = [city.get('city_id') for city in cities]
    unique = {city_id for city_id in ids if city_id is not None and ids.count(city_id) == 1}
    lines = []
    for city in cities:
        city_id = city.get('city_id')
        if city_id not in unique or city.get('type') == 'barrier':
            continue
        if city.get('owner_raw') != fid:
            continue
        wild = city_wild_officers(state, city)
        picked = qualifying_officers(wild, floor)
        if not picked:
            continue
        lines.append(report_line(city.get('name') or '?', picked, len(wild)))
    return lines


def wine_text(script_name, text, timeout):
    """Run one Wine helper with the report on stdin. Returns (ok, note)."""
    from quick_control import wine_argv
    argv, env = wine_argv(ROOT / 'bridge' / script_name)
    try:
        proc = subprocess.run(
            argv, input=text.encode('utf-8'), capture_output=True,
            timeout=timeout, env=env, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, '游戏辅助没有在时限内返回'
    note = (proc.stderr or b'').decode('utf-8', 'replace').strip().splitlines()
    detail = note[-1] if note else ''
    if proc.returncode != 0:
        return False, detail or '游戏辅助没有完成'
    return True, (proc.stdout or b'').decode('utf-8', 'replace').strip()


def put_clipboard(widget, text):
    """Put text on the system clipboard. Tk's clipboard does not stick on macOS."""
    if sys.platform == 'darwin':
        subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=False)
        return
    widget.clipboard_clear()
    widget.clipboard_append(text)
    widget.update_idletasks()


class OfficerReport(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self._body = None
        self._buttons = []
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill='x', padx=8, pady=6)
        tk.Label(bar, text='统武＞', bg=BG, fg=INK).pack(side='left')
        self.blade_floor = tk.StringVar(value=str(BLADE_MIN))
        tk.Entry(bar, textvariable=self.blade_floor, width=6).pack(side='left', padx=(2, 8))
        self.blade_floor.trace_add('write', lambda *_: self.refresh())
        self.copy_btn = tk.Button(bar, text='复制全部', command=self.copy_report, state='disabled')
        self.copy_btn.pack(side='right')
        self.note = tk.Label(self, bg=BG, fg=MUTED, anchor='w', justify='left', wraplength=980)
        self.note.pack(fill='x', padx=8, pady=(0, 4))
        self.bind('<Configure>', lambda event: self.note.configure(wraplength=max(240, event.width - 20)), add='+')
        box = tk.Frame(self, bg=BG)
        box.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.canvas = tk.Canvas(box, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(box, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.rows = tk.Frame(self.canvas, bg=BG)
        self.canvas.create_window((0, 0), window=self.rows, anchor='nw')
        self.rows.bind('<Configure>', lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.refresh()

    def copy_line(self, text, button):
        put_clipboard(self, text)
        for other in self._buttons:
            other.configure(text='复制')
        button.configure(text='已复制')
        floor = self._sig[0] if getattr(self, '_sig', None) else BLADE_MIN
        self.note.configure(text='已复制这座城。点游戏的白色聊天输入条，再按 Control+V。' + self._hint(floor))
        self._copy_to_game(text, '已复制。大厅／对局聊天：点白色输入条后按 Control+V；Mac 的 Command+V 未支持。')

    def copy_report(self):
        body = self._body or ''
        if not body:
            return
        put_clipboard(self, body)
        for other in self._buttons:
            other.configure(text='复制')
        floor = self._sig[0] if getattr(self, '_sig', None) else BLADE_MIN
        self.note.configure(text='已复制全部城。对局聊天请逐城复制、点白色输入条后按 Control+V。' + self._hint(floor))
        self._copy_to_game(body, '全部城已复制。大厅用 Control+V；对局聊天请逐城复制后粘贴。')

    def _copy_to_game(self, text, done):
        def worker():
            ok, detail = wine_text('win_clipboard_once.py', text, 15)
            note = done if ok else '本机已复制。游戏剪贴板没写上：' + detail
            self.after(0, lambda: self.note.configure(text=note + self._hint(self._floor())))
        threading.Thread(target=worker, daemon=True).start()

    def _floor(self):
        return self._sig[0] if getattr(self, '_sig', None) else BLADE_MIN

    def _hint(self, floor):
        return f'只报我方城池的在野。统武＝统率＋武力，{floor_phrase(floor)}才列名。留空不限。一行一座城：城名 将名  达标人数/本城在野人数。关隘、他方城、已仕将不计入。'

    def refresh(self):
        floor = parse_blade_floor(self.blade_floor.get()) if getattr(self, 'blade_floor', None) is not None else BLADE_MIN
        state = getattr(self.app, 'doc', None)
        if floor is False:
            lines, body, note = [], '', '统武下限请填数字。留空表示不限。'
        elif not state:
            lines, body, note = None, '', f'我方未确认。确认后只报我方城池里{floor_phrase(floor)}的在野。'
        else:
            lines = own_city_reports(state, floor)
            if lines is None:
                body, note = '', f'我方未确认。确认后只报我方城池里{floor_phrase(floor)}的在野。'
            elif not lines:
                body, note = '', f'我方城池里没有{floor_phrase(floor)}的在野。' + self._hint(floor)
            else:
                body = '\n'.join(lines)
                note = f'可报 {len(lines)} 城。' + self._hint(floor)
        changed = (floor, body) != getattr(self, '_sig', None)
        if changed:
            self._sig = (floor, body)
            self._body = body
            self._show_lines(lines or [])
            self.note.configure(text=note)
        self.copy_btn.configure(state='normal' if body else 'disabled')

    def _show_lines(self, lines):
        for child in self.rows.winfo_children():
            child.destroy()
        self._buttons = []
        for line in lines:
            row = tk.Frame(self.rows, bg='#f4efe0')
            row.pack(fill='x', pady=3)
            button = tk.Button(row, text='复制', width=6)
            button.configure(command=lambda text=line, btn=button: self.copy_line(text, btn))
            button.pack(side='right', padx=(0, 6), pady=4)
            tk.Label(row, text=line, bg='#f4efe0', fg=INK, anchor='w', font=('Menlo', 13)).pack(side='left', fill='x', expand=True, padx=8, pady=6)
            self._buttons.append(button)
