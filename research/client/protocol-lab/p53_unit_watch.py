"""Modeless Win32 pane. Only the private click mailbox lease is written.

No target UI calls, game messages, world writes or network APIs. Preview edits
only a Python copy. Closing the pane stops acquisition and its click lease.
"""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p53_unit_model import FIELD_NAMES, inspect_click, panel_text, parse_preview, preview, exact, number
from p53_unit_panel import SITE, MAGIC, MAILBOX_SIZE, click_from_mailbox, tick_age


class Pane:
    def __init__(self, c, w, k, owner=0, fields=('identity',), enrich=None, visible=True):
        self.c, self.w, self.k = c, w, k
        self.u = c.WinDLL('user32', use_last_error=True)
        self.fields, self.enrich = fields, enrich
        self.running, self.enabled = True, False
        self.observation, self.rendered = None, None
        self.on_toggle = lambda: None
        proc = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WNDCLASS(c.Structure):
            _fields_ = [('style', w.UINT), ('lpfnWndProc', proc), ('cbClsExtra', c.c_int),
                ('cbWndExtra', c.c_int), ('hInstance', w.HINSTANCE), ('hIcon', w.HICON),
                ('hCursor', w.HANDLE), ('hbrBackground', w.HANDLE),
                ('lpszMenuName', w.LPCWSTR), ('lpszClassName', w.LPCWSTR)]

        u = self.u
        u.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        u.DefWindowProcW.restype = c.c_ssize_t
        u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
            c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
        u.CreateWindowExW.restype = w.HWND
        u.RegisterClassW.argtypes = [c.POINTER(WNDCLASS)]
        u.DestroyWindow.argtypes = [w.HWND]
        u.SetWindowTextW.argtypes = [w.HWND, w.LPCWSTR]; u.SetWindowTextW.restype = w.BOOL
        u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
        u.GetWindowTextLengthW.argtypes = [w.HWND]; u.GetWindowTextLengthW.restype = c.c_int
        u.ShowWindow.argtypes = [w.HWND, c.c_int]
        u.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
        u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]; u.DispatchMessageW.restype = c.c_ssize_t
        self.callback = proc(self.window_proc)
        self.name = 'SGIP53UnitPane_'+str(k.GetCurrentProcessId())
        wc = WNDCLASS(); wc.lpfnWndProc = self.callback
        self.instance = k.GetModuleHandleW(None)
        wc.hInstance = self.instance
        wc.lpszClassName = self.name; wc.hbrBackground = 6
        if not u.RegisterClassW(c.byref(wc)):
            raise OSError('register pane class')
        self.hwnd = u.CreateWindowExW(0x80, self.name, '风夜 · 部队信息（本地只读）',
            0x00ca0000, 40, 60, 570, 610, owner, 0, self.instance, None)
        if not self.hwnd:
            raise OSError(c.get_last_error(), 'create pane')

        def control(kind, text, style, x, y, width, height, identity):
            hwnd = u.CreateWindowExW(0, kind, text, 0x50000000|style,
                x, y, width, height, self.hwnd, identity, self.instance, None)
            if not hwnd:
                raise OSError('create pane control')
            return hwnd

        self.toggle = control('BUTTON', '启用地图点选', 0, 12, 10, 170, 30, 101)
        self.body = control('EDIT', '点选默认关闭。启用后单击原版地图中的部队。',
                            0x00200844, 12, 50, 530, 375, 102)
        control('STATIC', '本地预览（只改面板副本，不改部队内存）', 0, 12, 434, 530, 22, 103)
        self.input = control('EDIT', '', 0x00800080, 12, 460, 530, 26, 104)
        control('STATIC', '例如 soldiers=12000,morale=90,training=60；更新即覆盖',
                0, 12, 490, 530, 22, 105)
        self.apply = control('BUTTON', '预览副本', 0, 12, 520, 150, 30, 106)
        self.reset = control('BUTTON', '恢复只读数值', 0, 174, 520, 150, 30, 107)
        if visible:
            u.ShowWindow(self.hwnd, 4)

    def text(self, hwnd):
        buf = self.c.create_unicode_buffer(self.u.GetWindowTextLengthW(hwnd)+1)
        self.u.GetWindowTextW(hwnd, buf, len(buf))
        return buf.value

    def set_text(self, hwnd, text):
        if not self.u.SetWindowTextW(hwnd, text):
            raise OSError('set pane text')

    def show(self, observation):
        self.observation = copy.deepcopy(observation)
        self.rendered = copy.deepcopy(observation)
        self.set_text(self.body, panel_text(observation, self.fields))

    def error(self, text):
        self.observation = self.rendered = None
        self.set_text(self.body, panel_text({'error': text}, self.fields))

    def window_proc(self, hwnd, msg, wp, lp):
        try:
            if msg == 0x10:
                self.running = False; self.u.DestroyWindow(hwnd); return 0
            if msg == 0x111:
                identity = wp & 0xffff
                if identity == 101:
                    self.on_toggle()
                elif identity == 106:
                    if self.observation is None:
                        raise ValueError('请先取得一支部队的有效观察')
                    self.rendered = preview(self.observation, parse_preview(self.text(self.input)), self.enrich)
                    self.set_text(self.body, panel_text(self.rendered, self.fields))
                elif identity == 107 and self.observation is not None:
                    self.show(self.observation)
                return 0
        except Exception as exc:
            self.set_text(self.body, '操作未完成：'+str(exc)); return 0
        return self.u.DefWindowProcW(hwnd, msg, wp, lp)

    def pump(self):
        msg = self.w.MSG()
        while self.u.PeekMessageW(self.c.byref(msg), 0, 0, 0, 1):
            if msg.message == 0x12:
                self.running = False
            self.u.TranslateMessage(self.c.byref(msg)); self.u.DispatchMessageW(self.c.byref(msg))

    def close(self):
        if self.running:
            self.running = False; self.u.DestroyWindow(self.hwnd)


def watch(args, c, w, k, pid, created, read, write, mailbox, after):
    from p51_shadow_inject import process_creation
    fields = tuple(FIELD_NAMES) if args.panel_fields == 'all' else tuple(args.panel_fields.split(','))
    if set(fields)-set(FIELD_NAMES) or len(fields) != len(set(fields)):
        raise SystemExit('unsupported/duplicate panel fields')
    if not 1 <= args.panel_seconds <= 86400:
        raise SystemExit('panel-seconds must be 1..86400')
    enrich = None
    if 'combat' in fields:
        rules = Path(args.bridge) if args.bridge else Path(__file__).resolve().parent/'unit-panel-rules'
        manifest = json.loads((Path(__file__).resolve().parent/'unit-panel-rules/manifest.json').read_text())
        for name, digest in manifest['sha256'].items():
            if hashlib.sha256((rules/name).read_bytes()).hexdigest() != digest:
                raise SystemExit('combat rule source mismatch: '+name)
        sys.path.insert(0, str(rules))
        from unit_combat import enrich_unit_combat
        enrich = enrich_unit_combat
    k.GetTickCount.restype = w.DWORD
    k.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]; k.CreateMutexW.restype = w.HANDLE
    c.set_last_error(0)
    mutex = k.CreateMutexW(None, False, 'Local\\SGIP53UnitPane_%s_%s' % (pid, created))
    if not mutex or c.get_last_error() == 183:
        if mutex: k.CloseHandle(mutex)
        raise SystemExit('a unit-pane watcher already exists for this process')
    log_path = Path(args.panel_log or (str(args.state)+'.watch.jsonl'))
    pane = None

    def emit(kind, **row):
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(kind=kind, wall=time.time(), pid=pid, creation=created,
                                        **row), ensure_ascii=False)+'\n')

    def lease(enabled):
        deadline = ((k.GetTickCount()+2000) & 0xffffffff) if enabled else 0
        if not write(mailbox+8, struct.pack('<I', deadline)) or not write(mailbox+4, struct.pack('<I', int(enabled))):
            raise OSError('write private inspection lease')

    try:
        view = number(read, 0x53b930)
        if number(read, view) != 0x50b730:
            raise ValueError('need the live shadow map view')
        hwnd = number(read, view+0x1c)
        u = c.WinDLL('user32', use_last_error=True)
        u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        u.GetAncestor.argtypes = [w.HWND, w.UINT]; u.GetAncestor.restype = w.HWND
        u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
        actual = w.DWORD()
        if not u.GetWindowThreadProcessId(hwnd, c.byref(actual)) or actual.value != pid:
            raise ValueError('map window owner mismatch')
        pane = Pane(c, w, k, owner=u.GetAncestor(hwnd, 2), fields=fields, enrich=enrich)

        def toggle():
            if read(SITE, len(after)) != after:
                raise ValueError('click site was reverted')
            pane.enabled = not pane.enabled
            lease(pane.enabled)
            pane.set_text(pane.toggle, '停用地图点选' if pane.enabled else '启用地图点选')
            if not pane.enabled:
                pane.error('点选已停用，已清除旧数值')
            emit('lease_toggle', enabled=pane.enabled)

        pane.on_toggle = toggle
        lease(False)
        emit('watch_started', fields=list(fields), enabled=False, game_world_writes=False)
        previous_version, selected, last_raw = 0, None, None
        deadline, next_poll = time.monotonic()+args.panel_seconds, 0
        while pane.running and time.monotonic() < deadline:
            pane.pump()
            if time.monotonic() < next_poll:
                time.sleep(.02); continue
            next_poll = time.monotonic()+.25
            if (process_creation(pid) != created or read(SITE, len(after)) != after
                    or read(mailbox, 4) != struct.pack('<I', MAGIC)):
                raise ValueError('target ended/changed or click site reverted')
            lease(pane.enabled)
            if not pane.enabled:
                selected = None; continue
            raw = exact(read, mailbox, MAILBOX_SIZE)
            click = click_from_mailbox(raw)
            if click is None or exact(read, mailbox+0xc, 0x44) != raw[0xc:0x50]:
                continue
            new_click = click['version'] != previous_version
            if new_click:
                previous_version = click['version']; selected = None
                if tick_age(k.GetTickCount(), click['tick']) > 1500:
                    pane.error('点击已过期，未沿用旧数据'); continue
                rect = w.RECT(); actual = w.DWORD()
                if (not u.GetWindowThreadProcessId(click['hwnd'], c.byref(actual)) or actual.value != pid
                        or not u.GetClientRect(click['hwnd'], c.byref(rect)) or rect.left or rect.top):
                    raise ValueError('clicked map HWND mismatch')
                click['client_size'] = [rect.right, rect.bottom]
            elif selected is None:
                continue
            else:
                click = copy.deepcopy(selected['click'])
                click['clock_hex'] = exact(read, click['core']+0x4d0, 12).hex()
            try:
                observation = inspect_click(read, click, enrich)
                pairs = lambda o: [(r['address'],r['unit_id'],r['vtable'],r['owner_raw']) for r in o['units']]
                if not new_click and pairs(observation) != pairs(selected):
                    raise ValueError('所选部队移动/消失/换身份；请重新点击')
                current_raw = json.dumps([observation['units'], observation['generals']], sort_keys=True)
                if new_click or current_raw != last_raw:
                    pane.show(observation)
                    emit('unit_observation', observation=observation, new_click=new_click)
                    last_raw = current_raw
                selected = observation
            except (ValueError, OSError, struct.error) as exc:
                selected = None; pane.error(str(exc)); emit('observation_unavailable', reason=str(exc))
    except BaseException as exc:
        if pane: pane.error(str(exc))
        emit('watch_error', reason=str(exc)); raise
    finally:
        try:
            lease(False)
        finally:
            if pane: pane.close()
            k.CloseHandle(mutex)
            emit('watch_stopped', lease_seconds_max=2, game_world_writes=False)


def gui_smoke(fixture, output):
    """Synthetic fixture only; never discovers/opens a SANPK process."""
    from p51_shadow_inject import _win
    c, w, k = _win()
    observation = json.loads(Path(fixture).read_text(encoding='utf-8'))
    pane = Pane(c, w, k, fields=FIELD_NAMES, visible=False)
    try:
        pane.show(observation); original = pane.text(pane.body)
        assert '兵力：' in original and '士气：' in original
        pane.set_text(pane.input, 'soldiers=12345,morale=40')
        pane.window_proc(pane.hwnd, 0x111, 106, 0)
        changed = pane.text(pane.body)
        assert '本地预览' in changed and '12345' in changed and '士气：40' in changed
        assert observation['units'][0]['values']['soldiers'] != 12345
        pane.window_proc(pane.hwnd, 0x111, 107, 0)
        assert pane.text(pane.body) == original
        pane.window_proc(pane.hwnd, 0x111, 106, 0)
        pane.show(observation)  # a fresh authoritative read removes the preview
        assert pane.text(pane.body) == original and not pane.rendered['local_preview']
        pane.error('合成过期样本')
        assert '12345' not in pane.text(pane.body) and '观察不可用' in pane.text(pane.body)
        Path(output).write_text(json.dumps(dict(schema='p53-native-gui-smoke-1',
            synthetic=True, game_attached=False, runtime_patch_installed=False,
            unicode_controls=True, readonly_display=True, preview_copy=True,
            reset=True, authoritative_refresh_drops_preview=True,
            stale_values_cleared=True, default_enabled=pane.enabled),
            ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    finally:
        pane.close()


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--gui-smoke-fixture', required=True); ap.add_argument('--out', required=True)
    args = ap.parse_args(); gui_smoke(args.gui_smoke_fixture, args.out)
