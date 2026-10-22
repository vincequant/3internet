#!/usr/bin/env python3
"""Local Fengye hub. Data collection runs only on browser/API requests."""
import argparse
import base64
import copy
import ipaddress
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import cmd_intel  # noqa: E402 - hub-local decoder facade (same source as protocol-lab)


def load_json(path, fallback):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return copy.deepcopy(fallback)


def timestamp(value):
    return value if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else None


def age(value, now):
    value = timestamp(value)
    return max(0, now - value) if value is not None else None


def public_rooms(query):
    rooms = []
    for raw in query.get('rooms', []) if isinstance(query.get('rooms'), list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            number = int(raw.get('id'))
            if not 0 < number < 2 ** 32:
                raise ValueError()
            virtual_ip = str(ipaddress.IPv4Address(number))
        except (TypeError, ValueError, ipaddress.AddressValueError):
            virtual_ip = None
        rooms.append({k: raw.get(k) for k in ('id', 'name', 'host', 'current', 'maximum', 'version')})
        rooms[-1].update(virtual_ip=virtual_ip,
                         ip_source='room_id_big_endian' if virtual_ip else 'unknown',
                         match_state='unknown')
    return rooms


def fields(value, keys):
    return {k: value[k] for k in keys if k in value} if isinstance(value, dict) else {}


def faction_snapshot(value, target, source_stale, now):
    value = value if isinstance(value, dict) else {}
    observed = timestamp(value.get('observed_at'))
    binding = value.get('binding46')
    valid = (value.get('source') == 'cmd7_snapshot' and observed is not None
             and isinstance(binding, int) and not isinstance(binding, bool)
             and -1 <= binding < 0xffffffff and value.get('member_id') is not None)
    if not valid:
        return {'status': 'unknown', 'assignment': 'unknown', 'source': 'cmd7_snapshot',
                'observed_at': None, 'identity_match': False, 'realtime': False}
    match = bool(target and str(target.get('id')) == str(value['member_id']))
    historic = source_stale or not match or observed > now + 5 or age(observed, now) > 20
    label = value.get('faction_name')
    return {'status': 'historical' if historic else 'matched',
            'assignment': 'unbound' if binding == -1 else 'bound',
            'binding46': binding, 'faction_name': label if isinstance(label, str) else None,
            'member_id': value['member_id'], 'observed_at': observed,
            'identity_match': match, 'source': 'cmd7_snapshot', 'realtime': False}


P34_FRAME_LIMIT = 80


def p34_view(raw):
    """Whitelist the p34 intel block for browsers; never pass raw objects through."""
    intel = raw.get('p34') if isinstance(raw, dict) else None
    if not isinstance(intel, dict):
        return None

    def block(value):
        if not isinstance(value, dict):
            return None
        return {'observed_at': timestamp(value.get('observed_at')), 'cmd': value.get('cmd'),
                'rows': [fields(row, ('i', 'id', 'w4', 'name', 'state42', 'binding46', 'faction'))
                         for row in (value.get('rows') or []) if isinstance(row, dict)][:8]}

    frames = [fields(f, ('wall', 'type', 'cmd', 'cls', 'len', 'sha8'))
              for f in (intel.get('frames') or []) if isinstance(f, dict)]
    sync = intel.get('sync') if isinstance(intel.get('sync'), dict) else {}
    nonempty = []
    for batch in (sync.get('nonempty') or []):
        if not isinstance(batch, dict):
            continue
        records = []
        for record in (batch.get('records') or []):
            if not isinstance(record, dict):
                continue
            decoded = cmd_intel.decode_record(record.get('sender'), record.get('raw'))
            row = fields(record, ('sender', 'len', 'sha8', 'raw'))
            row.update(decoded=bool(decoded.get('decoded')), action=decoded.get('action'),
                       detail=decoded.get('detail'), kind=decoded.get('kind'))
            records.append(row)
        nonempty.append({'wall': batch.get('wall'), 'round': batch.get('round'),
                         'records': records[:8]})
    names = {str(key): value for key, value in (raw.get('member_names') or {}).items()
             if isinstance(value, str)}
    for member in ((raw.get('host_watch') or {}).get('members') or []):
        if isinstance(member, dict) and member.get('id') and member.get('name'):
            names[str(member['id'])] = member['name']
    command_rows, command_totals = [], {}
    for batch in nonempty:
        for row in batch['records']:
            key = row.get('action') if row.get('decoded') else '未編目 kind=%s' % row.get('kind')
            command_totals[key] = command_totals.get(key, 0) + 1
            command_rows.append({'wall': batch.get('wall'), 'round': batch.get('round'),
                                 'sender': row.get('sender'),
                                 'name': names.get(str(row.get('sender'))),
                                 'decoded': row.get('decoded'), 'action': row.get('action'),
                                 'detail': row.get('detail'), 'kind': row.get('kind')})
    snapshots = intel.get('snapshots') if isinstance(intel.get('snapshots'), dict) else {}
    d8 = intel.get('d8') if isinstance(intel.get('d8'), dict) else {}
    return {
        'run_name': intel.get('run_name'),
        'pointer_state': intel.get('pointer_state'),
        'pointer_source': intel.get('pointer_source'),
        'registration_verified': bool(intel.get('registration_verified')),
        'registered': fields(intel.get('registered'),
                             ('own_id', 'machine_name', 'w4', 'row_state', 'pending_2723')),
        'fakeexit': fields(intel.get('fakeexit'), ('P_state', 'observed_wall')),
        'd8': {'sent_once': bool(d8.get('sent_once')), 'sent_wall': timestamp(d8.get('sent_wall')),
               'body_hex': d8.get('body_hex'), 'raw_rc': d8.get('raw_rc'),
               'mapped_rc': d8.get('mapped_rc'), 'target': d8.get('target'),
               'fast': bool(d8.get('fast')),
               'effect': fields(d8.get('effect'), ('row_present', 'unknown', 'observed_wall')),
               'withdrawn': fields(d8.get('withdrawn'), ('observed_wall', 'consecutive_absent_samples'))},
        'window': fields(intel.get('window'), ('anchor_wall', 'observe_seconds', 'end_wall', 'anchored_by')),
        'longrun': {
            'long_run': bool((intel.get('longrun') or {}).get('long_run')),
            'health_seconds': (intel.get('longrun') or {}).get('health_seconds'),
            'tail_seconds': (intel.get('longrun') or {}).get('tail_seconds'),
            'listen_started_wall': timestamp((intel.get('longrun') or {}).get('listen_started_wall')),
            'health': fields((intel.get('longrun') or {}).get('health'),
                             ('wall', 'connected', 'packets', 'release_calls', 'receiver_errors',
                              'tx_seq', 'native_state', 'd8_seconds', 'last_activity_age',
                              'observe_remaining', 'log_bytes')),
            'end_reason': (intel.get('longrun') or {}).get('end_reason'),
            'tail_recorded': bool((intel.get('longrun') or {}).get('tail_recorded')),
        },
        'counters': fields(intel.get('counters'),
                           ('received', 'released', 'errors', 'rounds', 'received_after_d8',
                            'last_packet_wall', 'last_packet_cmd')),
        'snapshots': {'initial': block(snapshots.get('initial')), 'start': block(snapshots.get('start'))},
        'frames': frames[-P34_FRAME_LIMIT:],
        'sync': {'rounds': sync.get('rounds'), 'nonempty': nonempty[-40:]},
        'commands': {'available': cmd_intel.decoder_available(),
                     'decoder': cmd_intel.DECODER_SOURCE,
                     'totals': dict(sorted(command_totals.items(), key=lambda kv: -kv[1])[:10]),
                     'rows': command_rows[-200:],
                     'note': '解碼自 control5 廣播記錄（幽靈外部採集）；未編目類別保留 kind；結果態不在廣播內。'},
        'notifications': fields(intel.get('notifications'), ('wm_event', 'wm_data', 'wm_chat')),
        'control': {
            'last_result': fields(((intel.get('control') or {}).get('last_result') or {}),
                                  ('id', 'op', 'rc', 'wall', 'chars')) or None,
            'pending': fields(((intel.get('control') or {}).get('pending') or {}), ('id', 'op')) or None,
            'events': [fields(e, ('ev', 'wall', 'request_id', 'text', 'rc', 'reason'))
                       for e in ((intel.get('control') or {}).get('events') or [])
                       if isinstance(e, dict)][-8:],
        },
        'chat': {'wm_chat_count': (intel.get('chat') or {}).get('wm_chat_count'),
                 'type3_frames': (intel.get('chat') or {}).get('type3_frames'),
                 'messages': [fields(m, ('wall', 'text'))
                              for m in ((intel.get('chat') or {}).get('messages') or [])
                              if isinstance(m, dict)][-10:]},
        'live_probe': bool(intel.get('live_probe')),
    }


def present(raw, transport, room_query, directory, now=None):
    now = time.time() if now is None else now
    raw = raw if isinstance(raw, dict) else {}
    watch = raw.get('host_watch') or {}
    observed = timestamp(watch.get('wall'))
    chain = raw.get('chain', [])
    watch_present = any(p.get('role') == 'watch' for p in chain)
    ghost_present = any(p.get('role') in ('ghost', 'session') for p in chain)
    session_raw = raw.get('session') if isinstance(raw.get('session'), dict) else None
    session = None
    if session_raw is not None:
        session = {'alive': bool(session_raw.get('alive')),
                   'fresh': bool(session_raw.get('fresh')),
                   'phase': session_raw.get('phase') if isinstance(session_raw.get('phase'), str) else 'unknown',
                   'connected': bool(session_raw.get('connected')),
                   'nickname': session_raw.get('nickname') if isinstance(session_raw.get('nickname'), str) else None,
                   'room_name': session_raw.get('room_name') if isinstance(session_raw.get('room_name'), str) else None,
                   'virtual_ip': session_raw.get('virtual_ip') if isinstance(session_raw.get('virtual_ip'), str) else None,
                   'room_id': session_raw.get('room_id') if isinstance(session_raw.get('room_id'), str) else None,
                   'ghost_registered': bool(session_raw.get('ghost_registered')),
                   'ghost_withdrawn': bool(session_raw.get('ghost_withdrawn')),
                   'host_init_wait': bool(session_raw.get('host_init_wait')),
                   'exit_seen_wall': timestamp(session_raw.get('exit_seen_wall')),
                   'observed_at': timestamp(session_raw.get('observed_at')),
                   'started_at': timestamp(session_raw.get('started_at')),
                   'line': session_raw.get('line') if isinstance(session_raw.get('line'), str) else None,
                   'error': session_raw.get('error') if isinstance(session_raw.get('error'), str) else None}
    if transport.get('status') == 'file' or raw.get('source_kind') == 'file_snapshot':
        reason = 'file_replay'
    elif transport.get('status') == 'offline':
        reason = 'remote_offline'
    elif transport.get('status') != 'online':
        reason = 'not_checked'
    elif raw and raw.get('source_kind') != 'remote_readonly':
        reason = 'historical_observation'
    elif session is not None:
        # 2026-10-17：只呈現當前加入的那局；會話一旦停止或過期即非即時，
        # 絕不以其他 run 的資料填充。
        if not session['alive']:
            reason = 'session_stopped'
        elif session['observed_at'] is None or session['observed_at'] > now + 5:
            reason = 'session_unknown'
        elif age(session['observed_at'], now) > 20:
            reason = 'session_expired'
        else:
            reason = 'live'
    else:
        reason = 'no_session'
    stale = reason != 'live'
    members = []
    for row in watch.get('members', []):
        if not isinstance(row, dict) or not row.get('id') or str(row.get('id')) == '0':
            continue
        members.append({k: row.get(k) for k in ('id', 'name', 'seq_24', 'seq_28', 'reconnecting', 'failed', 'active')})
    target = next((m for m in members if m.get('name') == '风夜'), None)
    # 本局會話沒有主機成員表；開局快照的身份核對回退到本會話自己的 own_id。
    session_own_id = ((raw.get('p34') or {}).get('registered') or {}).get('own_id')
    faction_target = target if target is not None else (
        {'id': session_own_id} if session_own_id is not None else None)
    state = 'unknown' if (stale or observed is None) else ('absent' if target is None else
            'failed' if target.get('failed') else 'reconnecting' if target.get('reconnecting') else 'seated')
    log = raw.get('ghost_log') or {}
    log_at = timestamp(log.get('last_log_at'))
    log_fresh = (transport.get('status') == 'online' and raw.get('source_kind') == 'remote_readonly'
                 and ghost_present and log_at is not None and log_at <= now + 5 and age(log_at, now) <= 20)
    host = fields(raw.get('host'), ('virtual_ip', 'session', 'source', 'observed_at'))
    host_at = timestamp(host.get('observed_at'))
    host['stale'] = not (transport.get('status') == 'online' and raw.get('source_kind') == 'remote_readonly'
                         and host.get('source') in ('current_driver', 'hub_session') and host_at is not None
                         and host_at <= now + 5 and age(host_at, now) <= 20)
    activity_at = (raw.get('activity') or {}).get(str(target.get('id'))) if target else None
    room_query = room_query if isinstance(room_query, dict) else {}
    query_age = age(room_query.get('observed_at'), now)
    query_fresh = (transport.get('status') == 'online' and query_age is not None and query_age <= 60
                   and room_query.get('line_verified') is True)
    query_status = room_query.get('query_status', 'not_queried')
    status_raw = raw.get('status') if isinstance(raw.get('status'), dict) else None
    status = None
    if status_raw is not None:
        # 0.2.24：風夜自己的即時狀態（影子端只讀採集）。值原樣帶出，
        # 由呈現層翻成玩家說法；缺的鍵保持 None，不補造。
        status = {key: status_raw.get(key) for key in (
            'wall', 'age', 'present', 'link', 'scene', 'seat', 'hide', 'godview',
            'driver', 'rx', 'world', 'disk_free_gb', 'pid', 'patches', 'hall')}
        status['line'] = status_raw.get('line') or raw.get('line')
    return {'now': now, 'transport': transport,
            'session': session, 'status': status,
            'source': {'kind': raw.get('source_kind'),
                       'observed_at': observed if observed is not None else (session or {}).get('observed_at'),
                       'age_seconds': age(observed if observed is not None else (session or {}).get('observed_at'), now), 'stale': stale,
                       'status': reason,
                       'run_name': raw.get('run_name')},
            'ghost': {'name': '风夜', 'state': state, 'last_known_state':
                      ('unknown' if observed is None else 'absent' if target is None else 'failed' if target.get('failed') else
                       'reconnecting' if target.get('reconnecting') else 'seated'),
                      'member': target, 'activity_at': activity_at,
                      'activity_age_seconds': age(activity_at, now),
                      'watchdog_started_at': log.get('watchdog_started_at'),
                      'watchdog_process_present': ghost_present and log_fresh,
                      'registration': log.get('registration', 'unknown'),
                      'cmd23_attempts': log.get('cmd23_attempts'), 'cmd23_returns': log.get('cmd23_returns'),
                      'start_snapshot': faction_snapshot(log.get('start_snapshot'), faction_target, stale, now),
                      'game_started': 'unknown'},
            'collector': {'mode': log.get('mode') if log.get('mode') in ('capture_only', 'ready_on_valid_cmd7', 'p34_spectator', 'p42_spectator', 'hub_room_session') else 'cmd23_watchdog',
                          'process_present': ghost_present, 'observed_at': log_at, 'fresh': log_fresh,
                          **fields(log, ('packet_count', 'release_calls', 'receiver_errors', 'last_packet_at', 'last_cmd', 'automatic_ready',
                                         'cmd9_attempts', 'cmd9_returns', 'start_command_received_at'))},
            'host': host, 'line': raw.get('line') or '多线3',
            'members': members,
            'chain': [fields(p, ('role', 'pid', 'wine_pid', 'parent_pid', 'line')) for p in raw.get('chain', [])],
            'events': [fields(e, ('ev', 'wall', 'label', 'fire', 'n', 'rc', 'dt', 'attempts', 'cmd')) for e in raw.get('events', [])],
            'room_query': {'status': query_status, 'observed_at': room_query.get('observed_at'),
                           'fresh': query_fresh, 'age_seconds': query_age,
                           'error': room_query.get('error'), 'rooms': public_rooms(room_query),
                           'source': room_query.get('source'), 'empty_confirmed': False},
            'directory': {'observed_at': directory.get('observed_at'),
                          'source': directory.get('source'),
                          'lines': [fields(r, ('id', 'name', 'server', 'port')) for r in directory.get('lines', [])]},
            'p34': p34_view(raw),
            'limits': ['成员来自主机 DLL 表；应用 L/P 行与开局成功未自动确认。',
                       '未收到房间回复不代表线路没有房间；未推断对局是否已经开始。']}


class Sources:
    def __init__(self, host=None, data_dir=None, source_file=None, runner=None):
        self.data_dir = Path(data_dir or ROOT / 'data')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.host = host or load_json(self.data_dir / 'config.json', {}).get('ssh_target')
        self.source_file = Path(source_file) if source_file else None
        self.runner = runner or subprocess.run
        self.raw = load_json(self.data_dir / 'last-observation.json', {})
        # 2026-10-17：舊版快取可能來自其他 run；沒有 session 鍵的舊格式一律
        # 不再呈現（只顯示當前加入的那局）。
        if isinstance(self.raw, dict) and self.raw and 'session' not in self.raw:
            self.raw = {}
        self.rooms = load_json(self.data_dir / 'last-rooms.json', {})
        if not isinstance(self.raw.get('session'), dict):
            # 沒有當前會話快取（舊格式或無會話）：房間列表也不再呈現舊觀測。
            self.rooms = {}
        self.directory = load_json(self.data_dir / 'line-directory.json', {})
        self.transport = {'status': 'not_checked', 'checked_at': None, 'error': None}
        self.lock = threading.Lock()
        self.next_check = 0
        self.last_search = 0
        self.last_control = 0

    def save(self, name, payload):
        path = self.data_dir / name
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2))
        tmp.replace(path)

    def _local_snapshot(self, search=False):
        """This Mac's own lab, when config names it. The panel otherwise SSHs
        to an old remote session and shows that session's stale room."""
        cfg = load_json(self.data_dir / 'config.json', {})
        lab = cfg.get('local_lab')
        if not isinstance(lab, str) or not lab:
            return None
        root = Path(lab).expanduser()
        if not (root / 'fengye-hub-session' / 'active.json').is_file():
            return None
        import remote_snapshot
        data = remote_snapshot.snapshot(root, search=search)
        if not isinstance(data, dict) or data.get('error'):
            return None
        data['source_kind'] = 'local_lab'
        return data

    def read_remote(self, search=False):
        if self.source_file:
            data = load_json(self.source_file, {'error': '本地源文件不可用'})
            if not isinstance(data, dict) or data.get('error'):
                raise RuntimeError('本地快照源不可用')
            data['source_kind'] = 'file_snapshot'
            return data
        local = self._local_snapshot(search)
        if local is not None:
            return local
        if not self.host:
            raise RuntimeError('尚未配置 vkquant Mac 的 SSH 地址')
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectionAttempts=1',
                   '-o', 'ConnectTimeout=4', '-o', 'ServerAliveInterval=3',
                   '-o', 'ServerAliveCountMax=1', self.host,
                   'python3 -' + (' --search' if search else '')]
        try:
            result = self.runner(command, input=(ROOT / 'remote_snapshot.py').read_text(),
                                 capture_output=True, text=True, timeout=24 if search else 10)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('无法连接 vkquant Mac；请确认网络与 SSH') from None
        if result.returncode:
            raise RuntimeError('vkquant Mac 未响应或读取失败')
        try:
            data = json.loads(result.stdout)
            if not isinstance(data, dict) or data.get('error'):
                raise ValueError()
            return data
        except (ValueError, TypeError):
            raise RuntimeError('远端没有返回有效状态') from None

    def refresh(self, search=False):
        # One SSH invocation per refresh, even with multiple browser tabs.
        with self.lock:
            now = time.time()
            if not search and now < self.next_check:
                return self.view()
            if search and now - self.last_search < 15:
                return self.view()
            if search:
                self.last_search = now
            try:
                data = self.read_remote(search)
                self.raw = data
                self.save('last-observation.json', data)
                if 'room_query' in data:
                    result = data['room_query']
                    if isinstance(result, dict) and result.get('query_status') in ('replies_received', 'unconfirmed_empty'):
                        self.rooms = result
                        self.save('last-rooms.json', result)
                    elif isinstance(result, dict):
                        # Keep last actual room reply and its timestamp on failure.
                        self.rooms = dict(self.rooms, error=result.get('error') or '房间搜索不可用')
                    else:
                        # 無當前會話：房間列表不保留其他局或歷史快取。
                        self.rooms = {}
                self.transport = {'status': 'file' if self.source_file else 'online', 'checked_at': time.time(), 'error': None}
                self.next_check = time.time() + 5
            except RuntimeError as exc:
                self.transport = {'status': 'offline', 'checked_at': time.time(), 'error': str(exc)}
                self.next_check = time.time() + 30
            return self.view()

    def view(self):
        return present(self.raw, copy.deepcopy(self.transport), self.rooms, self.directory)

    def control(self, payload):
        """Send one validated control request to a running remote probe.

        A fresh id is minted per request; the remote writer refuses when no p34
        probe is running. Execution happens only inside the probe (once-only by
        id); results surface through the next status refresh.
        """
        with self.lock:
            now = time.time()
            if now - self.last_control < 2:
                return {'status': 'rate_limited', 'error': '操作過於頻繁（最少間隔 2 秒）'}
            self.last_control = now
            if not self.source_file and not self.host:
                return {'status': 'error', 'error': '尚未配置 SSH 地址'}
            if not isinstance(payload, dict) or payload.get('op') not in ('chat', 'stop'):
                return {'status': 'error', 'error': '未知操作'}
            request = {'id': uuid.uuid4().hex[:16], 'op': payload['op']}
            if isinstance(payload.get('text'), str):
                request['text'] = payload['text']
            arg = '--control=' + base64.urlsafe_b64encode(
                json.dumps(request, ensure_ascii=False).encode('utf-8')).decode('ascii')
            command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectionAttempts=1',
                       '-o', 'ConnectTimeout=4', '-o', 'ServerAliveInterval=3',
                       '-o', 'ServerAliveCountMax=1', self.host, 'python3 - ' + arg]
            try:
                result = self.runner(command, input=(ROOT / 'remote_snapshot.py').read_text(),
                                     capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                return {'status': 'error', 'error': '无法连接 vkquant Mac'}
            if result.returncode:
                return {'status': 'error', 'error': 'vkquant Mac 未响应或写入失败'}
            try:
                data = json.loads(result.stdout)
            except (ValueError, TypeError):
                return {'status': 'error', 'error': '远端没有返回有效结果'}
            if isinstance(data, dict) and data.get('status') == 'sent':
                return {'status': 'sent', 'id': data.get('id'), 'op': data.get('op'),
                        'run': data.get('run')}
            return {'status': 'error', 'error': str((data or {}).get('error') or '已拒絕')}


def make_server(sources, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/status':
                self.respond(json.dumps(sources.refresh(), ensure_ascii=False, allow_nan=False).encode(), 'application/json; charset=utf-8')
            elif path in ('/', '/app.js', '/style.css'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
                mime = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[path]
                self.respond((ROOT / 'static' / name).read_bytes(), mime + '; charset=utf-8')
            else:
                self.respond(b'Not found', 'text/plain', 404)

        def do_POST(self):
            path = urlsplit(self.path).path
            if path not in ('/api/rooms/refresh', '/api/control'):
                self.respond(b'Not found', 'text/plain', 404)
                return
            # Browser-originated writes must be same-origin. Room search is
            # read-only; /api/control writes one validated request file for a
            # running probe (chat or normal exit). No endpoint launches,
            # joins, fires or kills.
            origin = self.headers.get('Origin')
            expected = 'http://' + self.headers.get('Host', '')
            if origin and origin != expected:
                self.respond(b'Forbidden origin', 'text/plain', 403)
                return
            if path == '/api/rooms/refresh':
                self.respond(json.dumps(sources.refresh(search=True), ensure_ascii=False, allow_nan=False).encode(), 'application/json; charset=utf-8')
                return
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                length = 0
            if not 0 < length <= 4096:
                self.respond(b'Invalid body', 'text/plain', 400)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                self.respond(b'Invalid JSON', 'text/plain', 400)
                return
            self.respond(json.dumps(sources.control(payload if isinstance(payload, dict) else {}),
                                    ensure_ascii=False, allow_nan=False).encode(),
                         'application/json; charset=utf-8')

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', help='SSH target; otherwise read local data/config.json')
    ap.add_argument('--data-dir')
    ap.add_argument('--source-file', help='Explicit snapshot input; never presented as live unless source timestamps prove it')
    args = ap.parse_args()
    httpd = make_server(Sources(args.host, args.data_dir, args.source_file), args.port)
    print('风夜状态 Hub · http://127.0.0.1:{}/'.format(httpd.server_port), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
