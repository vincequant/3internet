"""Single-instance serial monitor loop. Hub UI closing must not stop this process."""
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .collector import collect
from .commands import apply_command, parse_command
from .config import load_config, save_json
from .events import data_events, diff_events, format_list, format_summary, index_rooms, mark_sent, should_emit
from .grokbot import send_text
from .credentials import missing_credentials, status as cred_status
from .logs import setup_logs
from .lobby import click_start_game, ensure_platform, ensure_target_room
from .states import (
    CACHED, DEFAULT_THRESHOLD, LIST_WINDOW_READY, LIVE, MONITORING, NEEDS_USER, PAUSED,
    PENDING_CONFIG, PENDING_LOGIN, REFRESHING, REFRESHING_DATA, ROOM_CONNECTED, SEARCHING,
)
from .store import (
    acquire_lock, append_event, load_dedup, read_cache, read_health, read_live,
    release_lock, save_connection, save_dedup, write_cache, write_health, write_live,
)
from .version import VERSION


class MonitorService:
    def __init__(self, data_dir=None, notify=True):
        self.config = load_config(data_dir)
        self.data_dir = Path(self.config['data_dir'])
        self.notify = notify
        self.running = False
        self.paused = False
        self.refreshing = False
        self.commands = queue.Queue()
        self.state = PENDING_CONFIG
        self.miss_counts = {}
        self.first_summary = True
        self.stats = {'refresh_ok': 0, 'refresh_fail': 0, 'elapsed_ms': [], 'started_at': time.time()}
        self._http = None

    def start(self, http=True):
        setup_logs(self.data_dir)
        acquire_lock(self.data_dir)
        self.running = True
        self.paused = False
        write_health(self.data_dir, self.health())
        if http:
            self._start_http()
        try:
            self._bootstrap()
            self._loop()
        finally:
            self.running = False
            if self._http:
                self._http.shutdown()
            release_lock(self.data_dir)

    def request(self, text):
        command = parse_command(text)
        if not command:
            return {'ok': False, 'message': '无法识别的命令'}
        self.commands.put(command)
        return {'ok': True, 'queued': command}

    def snapshot(self, waiting_only=False):
        live = read_live(self.data_dir)
        return format_list(live, waiting_only=waiting_only)

    def health(self):
        elapsed = self.stats['elapsed_ms']
        total = self.stats['refresh_ok'] + self.stats['refresh_fail']
        return {
            'version': VERSION,
            'state': self.state,
            'paused': self.paused,
            'running': self.running,
            'instance_id': self.config.get('instance_id'),
            'platform_line': self.config.get('platform_line'),
            'platform_room': self.config.get('platform_room'),
            'threshold': self.config.get('alert_threshold', DEFAULT_THRESHOLD),
            'interval': self.config.get('refresh_interval_sec'),
            'refresh_ok': self.stats['refresh_ok'],
            'refresh_fail': self.stats['refresh_fail'],
            'success_rate': (self.stats['refresh_ok'] / total) if total else None,
            'avg_ms': (sum(elapsed) / len(elapsed)) if elapsed else None,
            'uptime_sec': int(time.time() - self.stats['started_at']),
            'match_state': 'unknown',
            'match_state_note': '已开局状态不可观测',
            'installed': True,
            'service_running': self.running,
            'list_live': False,
            'message_reachable': None,
            'pending_config': self.state == PENDING_CONFIG,
        }

    def _bootstrap(self):
        creds = cred_status(self.config)
        if not self.config.get('monitor_prefix') or missing_credentials(self.config):
            self.state = PENDING_CONFIG
            write_health(self.data_dir, self.health())
            self._send('【监控测试/状态】服务已安装，当前是待配置，不是监控中。\n' + creds['entry'])
            return
        platform = ensure_platform(self.config)
        self.state = platform.get('state') or PENDING_LOGIN
        if platform.get('evidence'):
            save_connection(self.data_dir, platform['evidence'])
        if platform.get('needs_user'):
            self._emit_user(platform.get('message'))
        if self.state not in (PENDING_CONFIG, PENDING_LOGIN, NEEDS_USER) and not platform.get('needs_user'):
            entered = ensure_target_room(self.config)
            self.state = entered.get('state') or self.state
            if entered.get('evidence'):
                save_connection(self.data_dir, entered['evidence'])
            if entered.get('needs_user'):
                self._emit_user(entered.get('message'))
            elif self.state in (ROOM_CONNECTED, LIST_WINDOW_READY):
                started = click_start_game(self.config)
                self.state = started.get('state') or self.state
                if started.get('evidence'):
                    save_connection(self.data_dir, started['evidence'])
                if started.get('needs_user'):
                    self._emit_user(started.get('message'))
        if self.state == LIST_WINDOW_READY:
            self._handle({'action': 'start'})
        else:
            write_health(self.data_dir, self.health())

    def _loop(self):
        while self.running:
            self._drain_commands()
            if not self.running:
                break
            if self.paused:
                self.state = PAUSED
                write_health(self.data_dir, self.health())
                time.sleep(0.5)
                continue
            if self.state == PENDING_CONFIG:
                write_health(self.data_dir, self.health())
                time.sleep(1)
                continue
            interval = max(5, int(self.config.get('refresh_interval_sec') or 15))
            started = time.monotonic()
            self._refresh_once()
            leftover = interval - (time.monotonic() - started)
            deadline = time.monotonic() + max(0, leftover)
            while self.running and time.monotonic() < deadline:
                self._drain_commands()
                if self.paused or not self.running:
                    break
                time.sleep(0.2)

    def _drain_commands(self):
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                return
            self._handle(command)

    def _handle(self, command):
        action = command.get('action')
        if action == 'stop':
            self.running = False
            self._send('小号房间监控已停止。只停止本服务，未动主号、Hub 或游戏。')
            return
        if action == 'pause':
            self.paused = True
            self.state = PAUSED
            self._send('监控已暂停。回复「恢复监控」继续。')
            return
        if action == 'resume':
            self.paused = False
            if missing_credentials(self.config) or not self.config.get('monitor_prefix'):
                self.state = PENDING_CONFIG
                self._send('仍是待配置，不是监控中。请先 sgi-room-monitor creds-set。')
                return
            self.state = MONITORING
            self._send('监控已恢复。')
            return
        if action == 'start':
            self.paused = False
            self.running = True
            if missing_credentials(self.config) or not self.config.get('monitor_prefix'):
                self.state = PENDING_CONFIG
                self._send('仍是待配置，未开始刷新。请先完成凭据：sgi-room-monitor creds-set')
                return
            self._refresh_once(force_summary=True)
            return
        if action in ('list', 'waiting', 'health', 'threshold', 'interval'):
            try:
                self.config = apply_command(command, self.config)
                save_json(self.data_dir / 'config.json', {k: v for k, v in self.config.items() if k != 'data_dir'})
            except ValueError as error:
                self._send(str(error))
                return
            if action == 'health':
                self._send(self._health_text())
                return
            if action == 'threshold':
                self._send(self.config.get('threshold_note'))
            if action == 'interval':
                self._send(self.config.get('interval_note'))
            self._send(format_list(read_live(self.data_dir), waiting_only=action == 'waiting' or self.config.get('waiting_only_default')))

    def _refresh_once(self, force_summary=False):
        if self.refreshing:
            return
        self.refreshing = True
        self.state = SEARCHING
        previous_live = read_live(self.data_dir)
        previous_rooms = index_rooms(previous_live.get('rooms') or [])
        previous_status = previous_live.get('data_status')
        write_live(self.data_dir, {**previous_live, 'data_status': REFRESHING_DATA})
        try:
            snapshot = collect(self.config, refresh=True, previous=previous_live)
        except Exception as error:
            snapshot = collect(self.config, refresh=False, previous=previous_live)
            snapshot['message'] = str(error)
        self.refreshing = False
        if snapshot.get('data_status') == LIVE:
            self.stats['refresh_ok'] += 1
            self.state = MONITORING
        else:
            self.stats['refresh_fail'] += 1
            self.state = CACHED if snapshot.get('rooms') else snapshot.get('data_status') or CACHED
        if snapshot.get('elapsed_ms') is not None:
            self.stats['elapsed_ms'].append(snapshot['elapsed_ms'])
            self.stats['elapsed_ms'] = self.stats['elapsed_ms'][-200:]
        write_live(self.data_dir, snapshot)
        write_cache(self.data_dir, snapshot)
        write_health(self.data_dir, self.health())
        current_rooms = index_rooms(snapshot.get('rooms') or [])
        events, self.miss_counts = diff_events(
            previous_rooms, current_rooms,
            missing_cycles=int(self.config.get('missing_cycles') or 2),
            threshold=int(self.config.get('alert_threshold') or DEFAULT_THRESHOLD),
            miss_counts=self.miss_counts,
        )
        events.extend(data_events(previous_status, snapshot.get('data_status')))
        if snapshot.get('needs_user'):
            events.append({'type': 'needs_user', 'key': 'needs_user:' + (snapshot.get('message') or ''),
                           'message': snapshot.get('message')})
            self.state = NEEDS_USER
        for event in events:
            append_event(self.data_dir, event)
        outgoing = []
        dedup = load_dedup(self.data_dir)
        for event in events:
            if should_emit(event, dedup, cooldown=int(self.config.get('alert_cooldown_sec') or 180)):
                outgoing.append(event)
                mark_sent(dedup, event)
        save_dedup(self.data_dir, dedup)
        if force_summary or self.first_summary:
            self._send(format_summary(snapshot, events=outgoing, threshold=int(self.config.get('alert_threshold') or DEFAULT_THRESHOLD),
                                      first=self.first_summary))
            self.first_summary = False
        elif outgoing:
            self._send(format_summary(snapshot, events=outgoing,
                                      threshold=int(self.config.get('alert_threshold') or DEFAULT_THRESHOLD)))

    def _emit_user(self, message):
        if message:
            self._send(f'需要本人处理：{message}')

    def _send(self, text):
        if not text or not self.notify:
            return
        try:
            send_text(text, self.config)
        except Exception as error:
            write_health(self.data_dir, {**self.health(), 'last_send_error': str(error)})

    def _health_text(self):
        value = self.health()
        rate = value['success_rate']
        rate_text = f'{rate:.0%}' if rate is not None else '尚无'
        avg = value['avg_ms']
        avg_text = f'{avg:.0f}ms' if avg is not None else '尚无'
        return (f"监控健康：状态 {value['state']}，版本 {value['version']}，"
                f"刷新成功 {value['refresh_ok']} / 失败 {value['refresh_fail']}（成功率 {rate_text}），"
                f"平均耗时 {avg_text}，阈值 > {value['threshold']}，间隔 {value['interval']}s。"
                f"已开局状态不可观测。")

    def _start_http(self):
        service = self
        token = _control_token(self.data_dir)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if not _auth(self, token):
                    return
                path = urlparse(self.path).path
                if path == '/health':
                    return _json(self, service.health())
                if path == '/snapshot':
                    return _json(self, read_live(service.data_dir))
                if path == '/list':
                    return _json(self, {'text': service.snapshot()})
                self.send_error(404)

            def do_POST(self):
                if not _auth(self, token):
                    return
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length) or b'{}') if length else {}
                if urlparse(self.path).path != '/command':
                    self.send_error(404)
                    return
                _json(self, service.request(body.get('text') or body.get('command') or ''))

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer((self.config.get('bind') or '127.0.0.1', int(self.config.get('port') or 18771)), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._http = server


def _control_token(data_dir):
    path = Path(data_dir) / 'control.token'
    if path.is_file():
        return path.read_text(encoding='utf-8').strip()
    token = __import__('secrets').token_hex(16)
    path.write_text(token + '\n', encoding='utf-8')
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def _auth(handler, token):
    got = handler.headers.get('Authorization') or ''
    if got != f'Bearer {token}':
        handler.send_error(401)
        return False
    return True


def _json(handler, value):
    body = json.dumps(value, ensure_ascii=False).encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
