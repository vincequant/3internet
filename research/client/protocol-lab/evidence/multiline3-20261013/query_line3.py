"""Bounded line-3 search; isolated evidence, no changes to /tk or main game."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[1]
sys.path.insert(0, str(LAB))
import resident_session as rs
from login_protocol import room_directory


class DirectoryTransport(rs.SocketTransport):
    def __init__(self):
        super().__init__()
        self.directory = []

    def recv_frames(self, deadline):
        frames = super().recv_frames(deadline)
        for cmd, seq, body in frames:
            if cmd == rs.CMD_ROOM_DIR:
                row, _ = room_directory(body)
                if row['game_id'] == 1001:
                    self.directory.append(row)
        return frames


class BoundSession(rs.ResidentSession):
    def _apply_grant(self, user, token, target, ack_room):
        if target is None or target['id'] != 1002 or ack_room != 1002:
            raise RuntimeError('line3_ack_mismatch')
        super()._apply_grant(user, token, target, ack_room)


def main():
    lock = (LAB / 'resident.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.environ['SGI_TK_RESIDENT_ALLOW_PROD_LOGIN'] = '1'
    os.environ['SGI_TK_RESIDENT_ACCOUNT'] = '风夜'
    os.environ['SGI_TK_RESIDENT_CREDENTIALS'] = str(LAB / 'query-credentials.fengye.json')
    spec = importlib.util.spec_from_file_location('resident_runner', LAB / 'bin/sgi_tk_resident.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    creds, paths, make_env = runner.load_live_credentials()
    rs.TARGET_ROOM_SUBSTR = '多线3'  # This disposable process only.
    transport = DirectoryTransport()
    session = BoundSession(transport, lambda cfg: {}, account=creds['username'],
                           allow_live_login=True, leave_hall_after_grant=True)
    result = {'started_at': time.time(), 'line': '多线3（备用）',
              'room_id': 1002, 'opensession_join': False, 'attempts': 1}
    try:
        result['establish'] = session.establish(creds['username'], creds['password'])
        del creds
        result['directory'] = transport.directory
        result['relay_endpoint'] = {k: session.relay_config[k] for k in ('server', 'port', 'game_id', 'room_id')}
        # Preserve production scripts; exact scoped copy accepts line 1002 only.
        original = (LAB / 'loader_resident.py').read_text()
        needle = 'assert cfg["game_id"] == 1001 and cfg["room_id"] == 1001'
        assert original.count(needle) == 1
        loader = HERE / 'loader_line3.py'
        loader.write_text(original.replace(needle, 'assert cfg["game_id"] == 1001 and cfg["room_id"] == 1002'))
        (HERE / 'koeinm_probe.py').write_bytes((LAB / 'koeinm_probe.py').read_bytes())
        result['loader_sha256'] = hashlib.sha256(loader.read_bytes()).hexdigest()
        payload = json.dumps(session.relay_config) + '\n'
        payload += ''.join(json.dumps({'cmd': 'search'}) + '\n' for _ in range(3))
        payload += json.dumps({'cmd': 'quit'}) + '\n'
        wine = Path(paths['wine'])
        env = make_env(wine, paths['monitor_prefix'])
        proc = subprocess.run([str(wine), str(LAB / 'python32/sgi-protocol-probe.exe'),
                               '-X', 'utf8', str(loader)], input=payload, text=True,
                              capture_output=True, env=env, timeout=45)
        del payload
        result['relay_exit'] = proc.returncode
        result['relay_events'] = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')]
        rooms = {}
        for event in result['relay_events']:
            for room in event.get('rooms', []):
                row = dict(room)
                row['network_address_from_room_id'] = socket.inet_ntoa(struct.pack('!I', int(row['id'])))
                rooms[(row['id'], row['name'], row['host'])] = row
        result['rooms'] = list(rooms.values())
        result['query_status'] = 'replies_received' if rooms else 'unconfirmed_empty'
        result['stderr_bytes'] = len(proc.stderr.encode())
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        result['directory'] = transport.directory
    finally:
        session.close(send_logout=True)
        result['opcode_counts'] = {hex(k): v for k, v in session.ledger.counts().items()}
        result['finished_at'] = time.time()
        (HERE / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        lock.close()


if __name__ == '__main__':
    main()
