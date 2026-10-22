"""CLI: start/stop/status/list and Grokbot command entry."""
import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import config_path, default_data_dir, example_config, load_config, save_json
from .credentials import credential_path, status as cred_status, store_interactive
from .grokbot import send_text
from .provision import provision
from .service import MonitorService, _control_token
from .store import paths, read_health, read_live, release_lock
from .version import VERSION


def main(argv=None):
    parser = argparse.ArgumentParser(description='SGI 小号房间监控')
    parser.add_argument('action', nargs='?', default='help',
                        choices=['help', 'start', 'stop', 'status', 'health', 'list', 'waiting',
                                 'pause', 'resume', 'cmd', 'install-config', 'version',
                                 'provision', 'creds', 'creds-set', 'creds-status', 'send-test', 'diag',
                                 'ensure', 'once', 'query', 'brief'])
    parser.add_argument('text', nargs='*', help='发给监控的命令原文')
    parser.add_argument('--home', dest='home')
    parser.add_argument('--no-notify', action='store_true')
    parser.add_argument('--no-http', action='store_true')
    args = parser.parse_args(argv)
    if args.home:
        os.environ['SGI_ROOM_MONITOR_HOME'] = args.home
    data_dir = default_data_dir()
    if args.action == 'help':
        print(__doc__)
        print('用法: sgi-room-monitor start|stop|status|list|pause|resume|cmd <原文>')
        print('      provision | creds-set | creds-status | ensure | once | query | brief | send-test | diag')
        print('Grok Bot.app 只复述 brief/query，不要用 IBGateway 上的空白游戏选择截图判断有没有房。')
        return 0
    if args.action == 'version':
        print(VERSION)
        return 0
    if args.action == 'install-config':
        path = config_path(data_dir)
        if not path.is_file():
            save_json(path, example_config())
        cred = credential_path({'data_dir': str(data_dir)})
        if not cred.is_file():
            cred.write_text('{\n  "username": "",\n  "password": ""\n}\n', encoding='utf-8')
            try:
                cred.chmod(0o600)
            except OSError:
                pass
        print(path)
        return 0
    if args.action == 'provision':
        print(json.dumps(provision(load_config(data_dir), start_lobby=False), ensure_ascii=False, indent=2))
        return 0
    if args.action in ('creds', 'creds-status'):
        info = cred_status(load_config(data_dir))
        safe = {key: info[key] for key in info if key != 'username' or True}
        safe['username'] = info['username'] or ''
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        print(info['entry'])
        return 0 if info['ready'] else 2
    if args.action == 'creds-set':
        print(json.dumps(store_interactive(load_config(data_dir)), ensure_ascii=False))
        return 0
    if args.action == 'send-test':
        cfg = load_config(data_dir)
        record = send_text(
            '【监控测试】SGI 房间监控 0.1.1 通道验证。这不是房间人数报告。\n'
            '仅发往你本人的 OpenClaw Telegram 私聊。',
            cfg)
        print(json.dumps({key: record[key] for key in record if key != 'result'}, ensure_ascii=False))
        return 0 if record.get('ok') else 1
    if args.action == 'diag':
        print(json.dumps(_diag(data_dir), ensure_ascii=False, indent=2))
        return 0
    if args.action == 'ensure':
        from .lobby import click_start_game, ensure_platform, ensure_target_room
        from .store import save_connection
        cfg = load_config(data_dir)
        steps = [ensure_platform(cfg), ensure_target_room(cfg), click_start_game(cfg)]
        result = steps[-1]
        for step in steps:
            if step.get('evidence'):
                save_connection(data_dir, step['evidence'])
            if step.get('needs_user') or step.get('ok') is False:
                result = step
                break
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get('ok') or result.get('state') == 'list_window_ready' else 2
    if args.action in ('once', 'query', 'brief'):
        from .collector import collect
        from .events import format_brief
        from .store import write_live
        cfg = load_config(data_dir)
        snapshot = collect(cfg, refresh=True)
        write_live(data_dir, snapshot)
        if args.action == 'brief':
            print(format_brief(snapshot))
        else:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
        if snapshot.get('data_status') == 'live':
            return 0
        return 2
    if args.action == 'start':
        service = MonitorService(data_dir, notify=not args.no_notify)
        return _run_service(service, http=not args.no_http)
    if args.action == 'stop':
        result = _api(data_dir, '/command', {'text': '停止监控'})
        if result is not None:
            time.sleep(0.4)
            release_lock(data_dir, force=True)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        return _kill_lock(data_dir)
    mapping = {
        'status': '/health', 'health': '/health',
        'list': '/list', 'waiting': '/list',
    }
    if args.action in mapping and args.action != 'waiting':
        value = _api(data_dir, mapping[args.action])
        if value is not None:
            print(json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, dict) else value)
            return 0
        print(json.dumps(read_health(data_dir) if args.action != 'list' else read_live(data_dir),
                         ensure_ascii=False, indent=2))
        return 0
    text = {
        'pause': '暂停监控',
        'resume': '恢复监控',
        'waiting': '只看等待中的房间',
        'cmd': ' '.join(args.text),
    }.get(args.action)
    if args.action == 'cmd' and not text:
        print('缺少命令原文', file=sys.stderr)
        return 2
    result = _api(data_dir, '/command', {'text': text})
    if result is None:
        print('服务未运行', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _run_service(service, http=True):
    def handle(signum, frame):
        service.running = False
    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)
    service.start(http=http)
    return 0


def _api(data_dir, path, body=None):
    token = _control_token(data_dir)
    config = load_config(data_dir)
    url = f"http://{config.get('bind') or '127.0.0.1'}:{int(config.get('port') or 18771)}{path}"
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = urllib.request.Request(url, data=data, method='GET' if body is None else 'POST')
    request.add_header('Authorization', f'Bearer {token}')
    if data is not None:
        request.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _kill_lock(data_dir):
    lock = paths(data_dir)['lock']
    if not lock.is_file():
        print('服务未运行')
        return 0
    try:
        pid = int((json.loads(lock.read_text(encoding='utf-8')) or {}).get('pid') or 0)
    except Exception:
        pid = 0
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as error:
            print(error)
            return 1
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                break
    release_lock(data_dir, force=True)
    print('已请求停止')
    return 0


def _diag(data_dir):
    from .provision import default_paths, prefix_owned_pids
    cfg = load_config(data_dir)
    paths_wine = default_paths()
    last = {}
    send_path = Path(data_dir) / 'last-send.json'
    if send_path.is_file():
        raw = json.loads(send_path.read_text(encoding='utf-8'))
        last = {key: raw[key] for key in raw if key in ('ok', 'at', 'backend', 'target_kind', 'error')}
    return {
        'version': VERSION,
        'installed': True,
        'data_dir': str(data_dir),
        'monitor_prefix': cfg.get('monitor_prefix') or '',
        'monitor_prefix_ready': bool(cfg.get('monitor_prefix') and Path(cfg['monitor_prefix']).joinpath('system.reg').is_file()),
        'main_owned': prefix_owned_pids(paths_wine['main_prefix']),
        'monitor_owned': prefix_owned_pids(cfg.get('monitor_prefix') or paths_wine['monitor_prefix']),
        'creds': cred_status(cfg),
        'health': read_health(data_dir),
        'last_send': last,
        'states': {
            'installed': True,
            'service_running': bool((paths(data_dir)['lock']).is_file()),
            'list_live': (read_live(data_dir) or {}).get('data_status') == 'live',
            'message_reachable': last.get('ok'),
            'pending_config': not cred_status(cfg)['ready'] or not cfg.get('monitor_prefix'),
        },
    }


if __name__ == '__main__':
    sys.exit(main())
