"""Windows/Mac native client for the explicitly owned collector session."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
from backend.room_protocol import request

ROOT = Path(__file__).resolve().parent


class RoomClient:
    def __init__(self, host=None, replay=False, runner=None):
        self.host = host
        self.replay = replay
        self.runner = runner or subprocess.run
        self.state = {'phase': 'idle', 'fresh': False, 'connected': False}

    def call(self, payload):
        payload = request(payload)
        if self.replay:
            return {'status': 'error', 'error': '回放模式不啟動或操作大廳會話'}
        if not self.host:
            return {'status': 'error', 'error': '尚未配置採集端 SSH 地址'}
        payload['session_id'] = self.state.get('session_id')
        if payload['op'] == 'start':
            for field, name in (('probe', 'room_probe.py'), ('protocol', 'room_protocol.py')):
                raw = (ROOT / 'backend' / name).read_bytes()
                payload[field + '_source'] = base64.b64encode(raw).decode('ascii')
                payload[field + '_sha256'] = hashlib.sha256(raw).hexdigest()
        encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode('utf-8')).decode('ascii')
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=4',
                   '-o', 'ServerAliveInterval=3', '-o', 'ServerAliveCountMax=1', self.host,
                   'python3 - ' + encoded]
        try:
            result = self.runner(command, input=(ROOT / 'backend/room_remote.py').read_text(encoding='utf-8'),
                                 capture_output=True, text=True, timeout=25)
            if result.returncode:
                raise ValueError('採集端未回應')
            data = json.loads(result.stdout)
            if not isinstance(data, dict):
                raise ValueError('採集端回覆格式無效')
            if isinstance(data.get('session'), dict):
                self.state = data['session']
            return data
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            self.state = dict(self.state, fresh=False)
            return {'status': 'unknown', 'error': '連接結果未知，未重試：' + str(error)[:100]}
