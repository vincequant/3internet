"""Resident Win32/Wine helper. Native inputs and opted-in timer/recruit patches.

No remote endpoint, remote thread creation, arbitrary address/command interface,
authentication changes, save writes, game launch, or automatic input retries.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import ntpath
import os
from pathlib import Path
import queue
import struct
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from quick_control_model import SUPPORTED_BUILDS, KEYS, VIRTUAL_KEYS, extension_plan, extension_basis, require_menu, timer_value, require_available_action


class Native:
    def __init__(self, bound, exclusive=True):
        self.bound = bound
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.u = C.WinDLL('user32', use_last_error=True)
        specs = {
            'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            'CloseHandle': ([W.HANDLE], W.BOOL),
            'GetProcessTimes': ([W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL),
            'QueryFullProcessImageNameW': ([W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL),
            'ReadProcessMemory': ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
            'WriteProcessMemory': ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
            'GetTickCount': ([], W.DWORD),
            'CreateMutexW':([C.c_void_p,W.BOOL,W.LPCWSTR],W.HANDLE),
            'ReleaseMutex':([W.HANDLE],W.BOOL),
        }
        for name, (args, ret) in specs.items():
            fn = getattr(self.k, name); fn.argtypes = args; fn.restype = ret
        self.callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        specs = {
            'EnumWindows': ([self.callback, W.LPARAM], W.BOOL),
            'EnumChildWindows': ([W.HWND, self.callback, W.LPARAM], W.BOOL),
            'GetWindowThreadProcessId': ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            'GetWindowTextW': ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
            'GetClassNameW': ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
            'GetDlgCtrlID': ([W.HWND], C.c_int), 'IsWindowVisible': ([W.HWND], W.BOOL),
            'GetParent':([W.HWND],W.HWND),
            'PostMessageW': ([W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
            'GetForegroundWindow': ([], W.HWND), 'SetForegroundWindow': ([W.HWND], W.BOOL),
            'RegisterHotKey': ([W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL),
            'UnregisterHotKey': ([W.HWND, C.c_int], W.BOOL),
            'PeekMessageW': ([C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL),
        }
        for name, (args, ret) in specs.items():
            fn = getattr(self.u, name); fn.argtypes = args; fn.restype = ret
        self.mutex=None
        self.handle = self.k.OpenProcess(0x410, False, bound['pid'])
        if not self.handle:
            raise C.WinError(C.get_last_error())
        try:
            self.check_identity(self.handle)
            image_sha = hashlib.sha256(Path(bound['image']).read_bytes()).hexdigest()
            if image_sha not in SUPPORTED_BUILDS or image_sha != bound['build']:
                raise ValueError('游戏文件 SHA256 不匹配')
            if exclusive:
                mutex=self.k.CreateMutexW(None,True,f'Local\\SGIQuickControl-{bound["pid"]}-{bound["created"]}')
                error=C.get_last_error()
                if not mutex:raise C.WinError(error)
                if error==183:
                    self.k.CloseHandle(mutex)
                    raise ValueError('该游戏已有快捷面板／验证程序连接，请先关闭它')
                self.mutex=mutex
            self.last_input = 0
        except Exception:
            self.close(); raise

    def close(self):
        if getattr(self,'mutex',None):
            self.k.ReleaseMutex(self.mutex);self.k.CloseHandle(self.mutex);self.mutex=None
        if self.handle:
            self.k.CloseHandle(self.handle); self.handle = None

    def check_identity(self, handle):
        times = [W.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(handle, *(C.byref(t) for t in times)):
            raise C.WinError(C.get_last_error())
        created = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
        path = C.create_unicode_buffer(32768); size = W.DWORD(len(path))
        if not self.k.QueryFullProcessImageNameW(handle, 0, path, C.byref(size)):
            raise C.WinError(C.get_last_error())
        if created != self.bound['created'] or ntpath.normcase(path.value) != ntpath.normcase(self.bound['image']):
            raise ValueError('游戏实例已改变，请重新连接')

    def read(self, address, size):
        if not 0x10000 <= address < 0x7fff0000 or not 0 < size <= 0x1000:
            raise ValueError('超出读取范围')
        data = C.create_string_buffer(size); got = C.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, address, data, size, C.byref(got)) or got.value != size:
            raise C.WinError(C.get_last_error())
        return data.raw

    def number(self, address, fmt='<I'):
        return struct.unpack(fmt, self.read(address, struct.calcsize(fmt)))[0]

    def owner(self, hwnd):
        pid = W.DWORD(); self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return pid.value

    def windows(self):
        rows = []
        @self.callback
        def callback(hwnd, unused):
            if self.owner(hwnd) == self.bound['pid'] and self.u.IsWindowVisible(hwnd):
                title = C.create_unicode_buffer(512); cls = C.create_unicode_buffer(128)
                self.u.GetWindowTextW(hwnd, title, 512); self.u.GetClassNameW(hwnd, cls, 128)
                rows.append(dict(hwnd=int(hwnd), title=title.value, cls=cls.value))
            return True
        if not self.u.EnumWindows(callback, 0):
            raise C.WinError(C.get_last_error())
        return rows

    def capture(self):
        self.check_identity(self.handle)
        windows = self.windows()
        mains = [r for r in windows if r['title'] == '三国志Internet联机版3.5']
        if len(mains) != 1:
            raise ValueError('找不到唯一的游戏主窗口')
        main = mains[0]['hwnd']; children = []
        @self.callback
        def callback(hwnd, unused):
            if self.owner(hwnd) == self.bound['pid'] and self.u.GetDlgCtrlID(hwnd) == 59648 and self.u.IsWindowVisible(hwnd):
                children.append(int(hwnd))
            return True
        self.u.EnumChildWindows(main, callback, 0)
        if len(children) != 1:
            raise ValueError('找不到唯一游戏视图')
        hwnd = children[0]; core = self.bound['core']; doc = core - 0x912
        if self.number(core) != 0x5053c0 or self.number(doc) != 0x504d40:
            raise ValueError('当前游戏对象类型不匹配')
        header = self.read(doc + 0x28, 28); head, tail, count = struct.unpack_from('<III', header, 4)
        if not 1 <= count <= 4:
            raise ValueError('游戏视图列表不受支持')
        candidates = []; node = head; previous = 0; seen = set()
        for _ in range(count):
            if node in seen or node < 0x10000:
                raise ValueError('游戏视图链不完整')
            seen.add(node); nxt, back, obj = struct.unpack('<III', self.read(node, 12))
            if back != previous:
                raise ValueError('游戏视图链已改变')
            raw = self.read(obj, 64)
            if struct.unpack_from('<I', raw, 0x3c)[0] == doc and struct.unpack_from('<I', raw, 0x1c)[0] == hwnd:
                if struct.unpack_from('<I', raw)[0] != 0x50b730:
                    raise ValueError('当前尚未进入游戏')
                candidates.append(obj)
            previous, node = node, nxt
        if node or previous != tail or len(candidates) != 1 or self.read(doc + 0x28, 28) != header:
            raise ValueError('游戏视图关系不稳定')
        view = candidates[0]
        clock = self.read(core+0x4cc,18)
        slot = self.number(core+0x6c0)
        force = self.number(core+slot*0x87+0x4a) if 0 <= slot < 8 else None
        s = dict(document=doc, view=view, hwnd=hwnd, main_hwnd=main,
                 round_clock=clock.hex(), player_slot_raw=slot, player_force_raw=force,
                 mode=self.number(doc + 0x68), phase=self.number(doc + 0xdea, '<h'),
                 start_tick=self.number(doc + 0x6c), tick=int(self.k.GetTickCount()),
                 unit_count=self.number(doc + 0x701),
                 native_dialogs=any(r['cls'] == '#32770' and r['title'] != '小地图' for r in windows))
        rule_offset = 0xd62 if s['phase'] <= 2 else 0xd6a
        s['time_setting'] = self.number(doc + rule_offset)
        for name, offset, fmt in [('ending',0x8a6,'<I'), ('modal',0x8da,'<I'),
                ('allowance',0x896,'<I'), ('orders_used',0x944,'<I'),
                ('map_mode',0x948,'<I'), ('map_widget',0x950,'<I'),
                ('selected_unit',0x958,'<I'), ('selected_order',0x97c,'<i'),
                ('strategy_dialog',0x9b8,'<I'), ('recruit_dialog',0x9d0,'<I'),
                ('widget_count',0x806,'<I')]:
            s[name] = self.number(view + offset, fmt)
        s['recruit_visible'] = False
        if s['recruit_dialog']:
            pointer = s['recruit_dialog']
            if self.number(pointer) != 0x4fbd90 or self.number(pointer+0x204) != doc:
                raise ValueError('录用窗口对象类型／来源不匹配')
            recruit_hwnd = self.number(pointer+0x1c)
            s['recruit_visible'] = any(r['hwnd']==recruit_hwnd and r['title']=='录用'
                                      and (r['cls']=='#32770' or r['cls'].startswith('Afx:')) for r in windows)
        s['confirmation_typed'] = False
        if s['modal'] == 1 and s['widget_count'] == 1:
            header = self.read(view+0x7fa,28)
            head,tail,count=struct.unpack_from('<III',header,4)
            if head == tail and count == 1:
                nxt,back,obj = struct.unpack('<III',self.read(head,12))
                s['confirmation_typed'] = not nxt and not back and self.number(obj) == 0x5059d0
        if (self.number(doc) != 0x504d40 or self.number(view) != 0x50b730
                or self.number(view+0x3c) != doc or self.number(view+0x1c) != hwnd
                or self.number(doc+0x68) != s['mode'] or self.number(doc+0xdea,'<h') != s['phase']
                or self.read(core+0x4cc,18) != clock
                or self.number(core+0x6c0) != slot
                or (force is not None and self.number(core+slot*0x87+0x4a) != force)):
            raise ValueError('读取过程中游戏阶段改变')
        self.check_identity(self.handle)
        try:s['remaining_ms'] = timer_value(s);s['timer_known']=True
        except ValueError:s['remaining_ms']=None;s['timer_known']=False
        s['effect_pending']=bool(getattr(self,'effects_pending',False))
        s['training_pending']=list(getattr(self,'training_pending',[]))
        s['viewport'] = [self.number(view+0x64, '<i'), self.number(view+0x68, '<i')]
        return s

    def extend(self, state, test_enabled, allow_write, intent, added_ms=10000):
        plan = extension_plan(state, test_enabled, allow_write, added_ms)
        # One fixed 4-byte field only. Open write access only for this operation.
        handle = self.k.OpenProcess(0x438, False, self.bound['pid'])
        if not handle:
            raise C.WinError(C.get_last_error())
        try:
            self.check_identity(handle)
            fresh = self.capture()
            extension_plan(fresh, test_enabled, allow_write, added_ms)
            if extension_basis(fresh) != extension_basis(state):
                raise ValueError('回合或倒计时基准改变，本次未写入')
            intent(dict(kind='timer_write_intent', plan=plan, state=fresh))
            # Intent attribution may read the collector over HTTP. Recheck
            # immediately afterwards so a phase change cannot reuse an origin.
            current = self.capture()
            extension_plan(current, test_enabled, allow_write, added_ms)
            if extension_basis(current) != extension_basis(state):
                raise ValueError('记录期间回合已改变，本次未写入')
            data = C.create_string_buffer(struct.pack('<I', plan['after'])); got = C.c_size_t()
            ok = self.k.WriteProcessMemory(handle, plan['address'], data, 4, C.byref(got))
            receipt = dict(kind='timer_write_receipt', attempted=True, api_ok=bool(ok), bytes_written=got.value, plan=plan)
            intent(receipt)  # preserve receipt before any following observation fails
            if not ok or got.value != 4:
                return dict(status='unknown', receipt=receipt, note='加时写入结果未知，未重试')
            try:after = self.capture()
            except Exception as error:
                return dict(status='unknown',receipt=receipt,game_timer_expiry_verified=False,
                            note='加时已尝试，读回失败；未重试：'+str(error))
            verified = extension_basis(after) == extension_basis(dict(state,start_tick=plan['after']))
            return dict(status='timer_field_verified' if verified else 'unknown', receipt=receipt,
                        after=after, game_timer_expiry_verified=False,
                        note=('军事回合' if state['phase'] in (3,4,5) else '内政回合')+f'已加 {added_ms//1000} 秒（本机计时）' if verified else '写入后状态改变，请核对游戏；未重试')
        finally:
            self.k.CloseHandle(handle)

    def execute(self, action, test_enabled, allow_write, intent, hotkey=False):
        require_available_action(action)
        if action == 'recruit_probability':
            raise ValueError('概率录将须经专用入口核对当前候选')
        if action == 'inspect':
            return dict(status='observed', state=self.capture())
        if action == 'focus_unit':
            from quick_unit_focus import UnitFocus
            return UnitFocus(self, intent).execute(test_enabled, hotkey)
        if time.monotonic() - self.last_input < .35:
            raise ValueError('操作太快，请稍候再按一次')
        if hotkey and self.owner(self.u.GetForegroundWindow()) != self.bound['pid']:
            return dict(status='ignored', note='快捷键仅在游戏置前时生效')
        state = self.capture()
        if action == 'extend':
            self.last_input = time.monotonic()
            return self.extend(state, test_enabled, allow_write, intent)
        command = require_menu(state, action, test_enabled)
        if self.owner(state['hwnd']) != self.bound['pid']:
            raise ValueError('输入前游戏窗口已改变')
        intent(dict(kind='menu_input_intent', action=action, command=command, state=state))
        self.last_input = time.monotonic()
        ok = self.u.PostMessageW(state['hwnd'], 0x111, command, 0)
        receipt = dict(kind='menu_input_receipt', command=command, posted=bool(ok), hwnd=state['hwnd'])
        intent(receipt)
        if not ok:
            raise C.WinError(C.get_last_error())
        self.u.SetForegroundWindow(state['main_hwnd'])
        # Observe normal opening without accepting YES or retransmitting input.
        for _ in range(15):
            time.sleep(.1)
            try:
                after = self.capture()
            except (ValueError, OSError):
                continue
            opened = after['recruit_visible'] if action == 'recruit' else after['confirmation_typed']
            if opened:
                return dict(status='dialog_observed', receipt=receipt, after=after,
                            note='已打开游戏指令，请在游戏内选择／确认', command_committed=False)
        return dict(status='unknown', receipt=receipt, note='指令已发送，未核准弹窗；未重试', command_committed=False)


def output_event(event,bound):
    """Closing the UI pipe must not interrupt restoration of native code."""
    line=json.dumps(event,ensure_ascii=False)
    try:print(line,flush=True)
    except (OSError,ValueError):
        folder=Path(__file__).resolve().parents[1]/'quick-control-records'
        try:
            folder.mkdir(exist_ok=True)
            path=folder/f'native-recovery-{bound["pid"]}-{bound["created"]}-{os.getpid()}.jsonl'
            with path.open('a',encoding='utf8') as log:
                log.write(json.dumps(dict(bound=bound,event=event),ensure_ascii=False)+'\n')
        except OSError:
            # Restoration must still run if the UI exited and disk is full.
            pass


def dispatch_request(native, effects, request, enabled, allow_write, emit, recruiter=None, allow_target=False, automatic=None):
    action = request.get('action')
    require_available_action(action)
    if automatic is not None and (automatic.enabled or automatic.hooks) and action in ('alms','infantry','cavalry','bow'):
        raise ValueError('自动×3已开启，请直接在游戏内选令；关闭自动模式后可用面板按钮')
    if effects.active and action != 'inspect':
        raise ValueError('请先完成或取消游戏内的训练／施舍确认')
    if action in ('recruit_probability','recruit_roster'):
        if not enabled or recruiter is None:raise ValueError('普通择将招揽未启用')
        from quick_control_model import validate_probability_request,validate_roster_request
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:8769/api/state',timeout=8) as response:payload=json.load(response)
        validate=validate_roster_request if action=='recruit_roster' else validate_probability_request
        row=validate(payload,native.bound,request,recruiter.pending)
        return recruiter.submit_ordinary(row,enabled,lambda:native.execute('recruit',enabled,False,emit))
    if action in ('alms', 'infantry', 'cavalry', 'bow'):
        return effects.execute(action, enabled, allow_write, emit, request.get('hotkey', False))
    return native.execute(action, enabled, allow_write, emit, request.get('hotkey', False))


def serve(bound):
    native = Native(bound); pending = queue.Queue(); enabled = False; allow_write = False
    def mark_modification(action, state):
        import urllib.request
        from replay_modifications import record_intent
        # Re-read verified player context from the bound native game as well as
        # the fresh collector. A selected/viewed enemy force is not attribution.
        slot = native.number(bound['core'] + 0x6c0)
        if not 0 <= slot < 8: raise ValueError('无法确认本机玩家槽位，未执行修改')
        fid = native.number(bound['core'] + slot * 0x87 + 0x4a)
        with urllib.request.urlopen('http://127.0.0.1:8769/api/state', timeout=8) as response:
            payload = json.load(response)
        event = record_intent(bound, state, action, payload, fid)
        output_event(event, bound)
    def emit(event):
        if event.get('kind') == 'timer_write_intent':
            mark_modification('extend', event['state'])
        output_event(event,bound)
    from quick_plain_training import PlainTraining
    from quick_plain_recruit import PlainRecruit
    from quick_view_pan import ViewPan, HOTKEY_IDS
    effects=PlainTraining(native,emit)
    effects.before_modify = mark_modification
    from quick_auto_effects import AutoEffects
    automatic=AutoEffects(native,emit,effects,mark_modification)
    from quick_auto_timer import AutoTimer
    def prepare_auto_time(state):
        # Fetch/validate while the normal timer is still running. Only the
        # durable intent and final native guards run inside the last second.
        import urllib.request
        from quick_control_model import binding, extension_basis
        from replay_modifications import context, record_intent
        with urllib.request.urlopen('http://127.0.0.1:8769/api/state',timeout=1) as response:
            payload=json.load(response)
        if payload.get('fresh') is not True or payload.get('error') or binding(payload)!=bound:
            raise ValueError('修改来源与当前游戏实例不符，未执行修改')
        ctx=context(payload)
        if ctx['force_id']!=state['player_force_raw']:
            raise ValueError('修改目标势力改变，未执行修改')
        basis=extension_basis(state)
        def prepared_emit(event):
            if event.get('kind')=='timer_write_intent':
                current=event['state']
                if extension_basis(current)!=basis:
                    raise ValueError('来源核对后回合已改变，未执行修改')
                recorded=record_intent(bound,current,'extend',payload,current['player_force_raw'],
                                       attach_archives=False)
                output_event(recorded,bound)
            output_event(event,bound)
        return prepared_emit
    auto_timer=AutoTimer(native,emit,prepare=prepare_auto_time)
    recruiter=PlainRecruit(native,emit);allow_target=False
    view_pan=ViewPan(native,emit)
    from quick_automation import QuickAutomation
    automation=QuickAutomation(auto_timer,automatic,view_pan,emit)
    def read_requests():
        for line in sys.stdin:
            try:
                pending.put(json.loads(line))
            except ValueError:
                pending.put(dict(action='invalid'))
        pending.put(dict(action='quit'))
    threading.Thread(target=read_requests, daemon=True).start()
    keys = [action for action in KEYS if action != 'recruit']; registered = []; supported = []
    try:
        for i, action in enumerate(keys, 1):
            # MOD_NOREPEAT prevents a held key from extending repeatedly.
            if native.u.RegisterHotKey(None, i, 0x4003, VIRTUAL_KEYS[action]):
                supported.append(i)
                native.u.UnregisterHotKey(None, i)
        emit(dict(kind='ready', bound=bound, hotkeys=[keys[i-1] for i in supported], state=native.capture()))
        msg = W.MSG()
        while True:
            automation.poll()
            try:effects.poll()
            except Exception as error:emit(dict(kind='effect_observation_error',note=str(error)))
            try:recruiter.poll()
            except Exception as error:emit(dict(kind='recruit_observation_error',note=str(error)))
            # Do not consume another app's shortcuts while SANPK is background.
            foreground = enabled and native.owner(native.u.GetForegroundWindow()) == bound['pid']
            if foreground and not registered:
                for i in supported:
                    if native.u.RegisterHotKey(None, i, 0x4003, VIRTUAL_KEYS[keys[i-1]]):
                        registered.append(i)
            elif not foreground and registered:
                for i in registered:
                    native.u.UnregisterHotKey(None, i)
                registered.clear()
            try:
                request = pending.get(timeout=.03)
            except queue.Empty:
                request = None
            if request and request.get('action') == 'quit':
                break
            if request and request.get('action') == 'settings':
                enabled = request.get('test_enabled') is True
                allow_write = request.get('allow_timer_write') is True
                allow_target = request.get('allow_target_recruit') is True
                automation.set_enabled(request.get('automation_enabled'),enabled and allow_write)
                if recruiter.pending and not enabled:
                    recruiter.restore();recruiter.pending.clear()
                    emit(dict(kind='target_recruit_disarmed',note='已恢复政治录将判定；入队指令按原版结算。'))
                if not enabled and effects.active:
                    effects.restore();effects.active=None;native.effects_pending=False
                emit(dict(kind='settings', test_enabled=enabled, allow_timer_write=allow_write,allow_target_recruit=allow_target)); continue
            if request is None and native.u.PeekMessageW(C.byref(msg), None, 0x312, 0x312, 1):
                if msg.wParam in registered:
                    request = dict(action=keys[msg.wParam-1], hotkey=True)
                elif msg.wParam in view_pan.registered:
                    # Camera events do not enter the order/patch execution path.
                    try:view_pan.execute(HOTKEY_IDS[msg.wParam])
                    except Exception as error:emit(dict(kind='view_pan_ignored',note=str(error)))
            if request:
                action = request.get('action')
                try:
                    result = dispatch_request(native, effects, request, enabled, allow_write, emit, recruiter, allow_target, automatic)
                except Exception as error:
                    result = dict(status='error', note=str(error))
                emit(dict(kind='result', action=action, request_id=request.get('request_id'), result=result))
    finally:
        view_pan.close()
        for i in registered:
            native.u.UnregisterHotKey(None, i)
        try:automatic.close()
        except Exception as error:emit(dict(kind='auto_x3_restore_error',note=str(error),hooks_may_remain=True))
        try:recruiter.restore()
        except Exception as error:emit(dict(kind='recruit_restore_error',note=str(error),hooks_may_remain=True))
        try:effects.close()
        except Exception as error:emit(dict(kind='effect_restore_error',note=str(error),hooks_may_remain=True))
        native.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--binding', required=True, type=json.loads)
    args = parser.parse_args()
    try:
        serve(args.binding)
    except Exception as error:
        print(json.dumps(dict(kind='fatal', note=str(error)), ensure_ascii=False), flush=True)
        raise SystemExit(2)
