"""Local RPC entry point on the collector Mac; stdout is one sanitized JSON object."""
import argparse
import json
import sys
import time
import urllib.request


def query(fresh=False, timeout=60):
    started = time.time()
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        with urllib.request.urlopen('http://127.0.0.1:18773/api', timeout=5) as response:
            state = json.load(response)
        observed = state.get('observed_at')
        age = max(0, time.time()-observed) if observed else None
        if state['phase'] == 'error':
            return {'ok': False, 'status': 'query_failed', 'message': state.get('error'),
                    'rooms': [], 'updated_at': observed}
        if observed and age <= 45 and (not fresh or observed >= started):
            return {'ok': True, 'status': state['query_status'], 'account': state['account'],
                'platform_room': '三国对战房 / 多线2（主线）', 'platform_room_id': 1001,
                'rooms': state['rooms'], 'updated_at': observed, 'age_seconds': round(age, 1),
                'refreshing': state['phase'] == 'querying', 'source': 'VKQUANT-COM',
                'capture_method': 'native_login_original_dll_relay',
                'game_start_confirmed': False}
        time.sleep(1)
    return {'ok': False, 'status': 'timeout', 'rooms': [],
            'message': '等待最新查询结果超时，不能判断是否有房间'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--fresh', action='store_true')
    args = p.parse_args()
    try:
        result = query(args.fresh)
    except Exception:
        result = {'ok': False, 'status': 'collector_unavailable', 'rooms': [],
                  'message': '无法连接 Mac 上的列表服务'}
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result['ok'] else 2)
