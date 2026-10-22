"""Collector recovery: classify failures, backoff rediscovery, never mark stale live.

This module is importable on macOS. It must not import probe, collector, or ctypes.
"""
from datetime import datetime, timezone

SERVICE = 'sgi-crossover-bridge-1'
EXPECTED_PATH = r'C:\sgi\run-3.5\3I\SANPK.exe'
FRESH_WINDOW_S = 5.0
MIN_SCAN_INTERVAL_S = 2.0
MAX_BACKOFF_S = 15.0
CAPTURE_INTERVAL_S = 1.0
WAIT_GAME_S = 3.0
ERROR_POLL_S = 5.0
TRANSIENT_WAIT_S = 1.0

PHASE_LIVE = 'live'
PHASE_RECOVERING = 'recovering'
PHASE_WAITING_GAME = 'waiting_for_game'
PHASE_MAP_NOT_READY = 'map_not_ready'
PHASE_ERROR = 'error'


def apply_layout_delta(base, delta):
    return {
        'CORE_VT': base['CORE_VT'] + delta,
        'DOC_VT': base['DOC_VT'] + delta,
        'TYPES': {k + delta: v for k, v in base['TYPES'].items()},
        'UNIT_TYPES': {k + delta: v for k, v in base['UNIT_TYPES'].items()},
    }


def discard_scan_buffers(*holders):
    released = 0
    for holder in holders:
        if holder is None:
            continue
        for name in ('segments', 'regions', 'cache', 'headers', 'failures'):
            buf = getattr(holder, name, None)
            if isinstance(buf, list):
                released += len(buf)
                buf.clear()
            elif isinstance(buf, dict):
                released += len(buf)
                buf.clear()
        inner = getattr(holder, 'm', None)
        if inner is not None and inner is not holder:
            released += discard_scan_buffers(inner)
    return released


def next_backoff(prev, first=2.0, cap=MAX_BACKOFF_S):
    if not prev:
        return first
    return min(cap, float(prev) * 2)


def process_identity(instance):
    return (instance.get('pid'), instance.get('path'), instance.get('creation_filetime'))


def path_matches_expected(path, expected=EXPECTED_PATH):
    if not path:
        return False
    norm = path.replace('/', '\\').rstrip('\\').lower()
    exp = expected.replace('/', '\\').rstrip('\\').lower()
    return norm == exp


def classify_error(exc):
    msg = str(exc)
    if '采样中状态变化' in msg:
        return 'transient_inconsistent', PHASE_RECOVERING, msg, True
    if msg.startswith('Unreadable page') or msg.startswith('no bound GameCore') or msg.startswith('root object invalid'):
        return 'dead_root', PHASE_RECOVERING, msg, True
    if 'Ambiguous/missing GameCore: 0' in msg or '地图尚未出现' in msg:
        return 'map_not_ready', PHASE_MAP_NOT_READY, '地图尚未出现可读根对象，等待就绪', True
    if 'Ambiguous/missing GameCore:' in msg:
        return 'ambiguous_core', PHASE_ERROR, msg, True
    if 'Unsupported executable' in msg or '不支持的SANPK版本' in msg:
        return 'unsupported_version', PHASE_ERROR, msg, False
    if '个SANPK' in msg:
        return 'multiple_instances', PHASE_ERROR, msg, True
    if '游戏路径不符合' in msg or 'instance path mismatch' in msg:
        return 'path_mismatch', PHASE_ERROR, msg, True
    if '无法枚举' in msg or '游戏进程不在线' in msg:
        return 'process_gone', PHASE_WAITING_GAME, msg, True
    name = type(exc).__name__
    if name in ('OSError', 'WinError') or 'WinError' in msg or 'Access is denied' in msg:
        return 'process_gone', PHASE_WAITING_GAME, msg, True
    return 'unknown', PHASE_ERROR, msg, True


def snapshot_age_s(snapshot, now=None):
    if not snapshot or not snapshot.get('capture_end'):
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        end = datetime.fromisoformat(snapshot['capture_end'])
    except (TypeError, ValueError):
        return None
    return (now - end).total_seconds()


def compute_fresh(fresh_flag, error, snapshot, now=None, window=FRESH_WINDOW_S):
    if error or not fresh_flag:
        return False
    age = snapshot_age_s(snapshot, now)
    return age is not None and 0 <= age < window


def slim_snapshot(doc):
    slim = dict(doc)
    entities = doc.get('entities') or {}
    slim['entities'] = {
        key: [{a: b for a, b in row.items() if a not in ('raw_hex', 'address')} for row in rows]
        for key, rows in entities.items()
    }
    return slim


class RecoveryController:
    def __init__(self, find_game, configure, new_collector, now=None, expected_path=EXPECTED_PATH):
        self.expected_path = expected_path
        self.find_game = find_game
        self.configure = configure
        self.new_collector = new_collector
        self.now = now or (lambda: datetime.now(timezone.utc).timestamp())
        self.collector = None
        self.bound_identity = None
        self.configured_identity = None
        self.unsupported_identity = None
        self.released_count = 0
        self.last_released = None
        self.phase = PHASE_WAITING_GAME
        self.error = 'starting'
        self.error_class = 'starting'
        self.fresh = False
        self.last_ok = None
        self.backoff_s = 0.0
        self.last_scan_at = None

    def public_state(self, now_utc=None):
        age = snapshot_age_s(self.last_ok, now_utc)
        ident = None
        if self.bound_identity:
            ident = {'pid': self.bound_identity[0], 'path': self.bound_identity[1], 'creation_filetime': self.bound_identity[2]}
        core = None
        if self.collector is not None and getattr(self.collector, 'core', None) is not None:
            core = hex(self.collector.core)
        elif self.last_ok:
            core = self.last_ok.get('core_address')
        fresh = compute_fresh(self.fresh, self.error, self.last_ok, now_utc)
        return {
            'service': SERVICE,
            'fresh': fresh,
            'error': self.error,
            'phase': self.phase,
            'error_class': self.error_class,
            'snapshot_age_s': age,
            'last_snapshot_id': None if not self.last_ok else self.last_ok.get('snapshot_id'),
            'backoff_s': self.backoff_s,
            'pid': None if not ident else ident['pid'],
            'path': None if not ident else ident['path'],
            'core_address': core,
            'identity': ident,
            'state': self.last_ok,
        }

    def release(self, forget_configure=True):
        collector = self.collector
        self.collector = None
        self.bound_identity = None
        if forget_configure:
            self.configured_identity = None
        if collector is None:
            return
        discard_scan_buffers(collector)
        close = getattr(collector, 'close', None)
        if close:
            close()
        self.released_count += 1
        self.last_released = {
            'pid': getattr(collector, 'pid', None),
            'core': getattr(collector, 'core', None),
            'at': self.now(),
        }

    def step(self):
        try:
            lookup = self.find_game()
        except Exception as exc:
            error_class, phase, message, retryable = classify_error(exc)
            wait = WAIT_GAME_S if error_class == 'process_gone' else ERROR_POLL_S
            return self._fail_open(error_class, phase, message, wait, True)
        status = lookup.get('status')
        instances = lookup.get('instances') or []
        if status == 'none' or not instances:
            return self._fail_open('process_gone', PHASE_WAITING_GAME, '游戏进程不在线，等待重新进入', WAIT_GAME_S, True)
        if status == 'multiple' or len(instances) != 1:
            return self._fail_open(
                'multiple_instances',
                PHASE_ERROR,
                f'本Bottle中找到 {len(instances)} 个SANPK。请只保留一个目标游戏实例。',
                ERROR_POLL_S,
                True,
            )
        inst = instances[0]
        if not path_matches_expected(inst.get('path'),self.expected_path):
            return self._fail_open(
                'path_mismatch',
                PHASE_ERROR,
                '游戏路径不符合本机配置：' + str(inst.get('path')),
                ERROR_POLL_S,
                True,
            )
        ident = process_identity(inst)
        if self.unsupported_identity == ident:
            self.fresh = False
            self.phase = PHASE_ERROR
            self.error_class = 'unsupported_version'
            self.error = self.error or '不支持的SANPK版本；停止，不套用结构偏移'
            return ERROR_POLL_S
        if self.collector is not None and self.bound_identity != ident:
            self.release(forget_configure=True)
            self.fresh = False
            self.phase = PHASE_RECOVERING
            self.error_class = 'process_identity_changed'
            self.error = f'游戏进程身份变化，重新绑定 PID {inst.get("pid")}'
        if self.collector is not None and self.bound_identity == ident:
            return self._capture_or_rebind()
        return self._attach(inst, ident)

    def _fail_open(self, error_class, phase, message, wait, forget_configure):
        self.release(forget_configure=forget_configure)
        self.fresh = False
        self.phase = phase
        self.error_class = error_class
        self.error = message
        self.backoff_s = wait
        return wait

    def _mark(self, error_class, phase, message, fresh=False):
        self.fresh = fresh
        self.phase = phase
        self.error_class = error_class
        self.error = message

    def _scan_wait(self):
        if self.last_scan_at is None:
            return 0.0
        elapsed = self.now() - self.last_scan_at
        need = max(self.backoff_s, MIN_SCAN_INTERVAL_S)
        if elapsed < need:
            return need - elapsed
        return 0.0

    def _attach(self, inst, ident):
        wait = self._scan_wait()
        if wait > 0:
            self.fresh = False
            if self.phase == PHASE_LIVE:
                self.phase = PHASE_RECOVERING
            return wait
        self.last_scan_at = self.now()
        if self.phase not in (PHASE_MAP_NOT_READY, PHASE_WAITING_GAME, PHASE_ERROR):
            self.phase = PHASE_RECOVERING
        try:
            if self.configured_identity != ident:
                self.configure(inst['pid'], inst['path'])
                self.configured_identity = ident
            self.collector = self.new_collector(inst['pid'])
            self.collector.bind(discover=True)
            self.bound_identity = ident
            self.backoff_s = 0.0
            self.unsupported_identity = None
            return self._capture_or_rebind()
        except Exception as exc:
            self.release(forget_configure=False)
            error_class, phase, message, retryable = classify_error(exc)
            if error_class == 'unsupported_version':
                self.unsupported_identity = ident
                self.configured_identity = None
                self.release(forget_configure=True)
                wait = ERROR_POLL_S
            else:
                self.backoff_s = next_backoff(self.backoff_s)
                wait = self.backoff_s
                if not retryable:
                    wait = ERROR_POLL_S
            self._mark(error_class, phase, message)
            return wait

    def _capture_or_rebind(self):
        try:
            doc = self.collector.capture()
            if not (doc.get('consistency') or {}).get('root_headers_and_clock_unchanged'):
                self._mark('transient_inconsistent', PHASE_RECOVERING, '采样中状态变化，等待下一次')
                return TRANSIENT_WAIT_S
            self.last_ok = slim_snapshot(doc)
            self._mark(None, PHASE_LIVE, None, fresh=True)
            self.backoff_s = 0.0
            return CAPTURE_INTERVAL_S
        except Exception as exc:
            error_class, phase, message, retryable = classify_error(exc)
            self._mark(error_class, phase, message)
            if error_class == 'transient_inconsistent':
                return TRANSIENT_WAIT_S
            if error_class == 'dead_root':
                self.release(forget_configure=False)
                self.backoff_s = next_backoff(self.backoff_s) if self.last_scan_at is not None else 0.0
                return 0.0
            if error_class == 'process_gone':
                return self._fail_open(error_class, phase, message, WAIT_GAME_S, True)
            self.release(forget_configure=False)
            self.backoff_s = next_backoff(self.backoff_s)
            return self.backoff_s if retryable else ERROR_POLL_S
