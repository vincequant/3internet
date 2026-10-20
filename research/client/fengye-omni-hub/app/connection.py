"""Machine-local connection settings and an owned SSH tunnel; no game input."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / 'connection.local.json'

def config_path():
    return Path(os.environ.get('SGI_CONNECTION_CONFIG', DEFAULT_CONFIG))

def source_options():
    if os.environ.get('SGI_FENGYE_ONLY') == '1':
        return {}
    path = config_path()
    data = json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    return data.get('sources', {})

def select_source(name):
    if name not in source_options():
        raise ValueError('未知数据源')
    path = config_path().with_name('selected-source.local.json')
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({'selected_source': name}), encoding='utf8')
    temp.replace(path)

def local_config():
    """Local collection remains available while the UI views another host."""
    sources=source_options()
    locals_=[cfg for cfg in sources.values() if cfg.get('mode')=='local']
    if len(locals_)>1:raise ValueError('只能配置一个本机采集源')
    if locals_:return locals_[0]
    cfg=load_config()
    return cfg if cfg['mode']=='local' else None

def load_config():
    if os.environ.get('SGI_FENGYE_ONLY') == '1':
        return {'mode': 'local', 'label': '玩家全知來源已關閉', 'port': 8769, 'disabled': True}
    path = config_path()
    cfg = {'mode': 'local', 'label': socket.gethostname(), 'port': 8769}
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding='utf8')))
    sources = cfg.pop('sources', {})
    if sources:
        selected = cfg.get('selected_source', next(iter(sources)))
        selection = path.with_name('selected-source.local.json')
        if selection.exists():
            selected = json.loads(selection.read_text(encoding='utf8')).get('selected_source', selected)
        if selected not in sources:
            raise ValueError('已保存的数据源不存在，请检查连接配置')
        if sources[selected].get('mode') not in ('local','remote'):
            raise ValueError('数据源模式必须为 local 或 remote')
        cfg.update(sources[selected])
        cfg['selected_source'] = selected
    if cfg['mode'] not in ('local', 'remote'):
        raise ValueError('连接模式必须为 local 或 remote')
    if type(cfg['port']) is not int or not 1024 <= cfg['port'] <= 65535:
        raise ValueError('本地端口无效')
    if cfg['mode'] == 'remote':
        for key, default in (('ssh_port', 22), ('remote_port', 8770)):
            cfg.setdefault(key, default)
            if type(cfg[key]) is not int or not 1 <= cfg[key] <= 65535:
                raise ValueError('无效端口：' + key)
        for key in ('ssh_host', 'ssh_user', 'identity_file', 'known_hosts', 'expected_source'):
            if not isinstance(cfg.get(key), str) or not cfg[key] or cfg[key].startswith('-'):
                raise ValueError('远端连接配置缺少 ' + key)
    return cfg

class Connection:
    def __init__(self, cfg):
        self.cfg = cfg
        self.process = None
        self.last_attempt = 0
        self.failures = 0
        self.log = None
        self.last_error = None
        self.base_url = 'http://127.0.0.1:' + str(0 if cfg.get('disabled') else cfg['port'])

    @property
    def remote(self):
        return self.cfg['mode'] == 'remote'

    def _port_open(self):
        with socket.socket() as sock:
            return sock.connect_ex(('127.0.0.1', self.cfg['port'])) == 0

    def _probe_forward(self):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    self.base_url + '/health', timeout=3) as response:
                return json.load(response)
        except (OSError, ValueError, TimeoutError):
            return None

    def _reuse_healthy_forward(self):
        if not self._port_open():
            return False
        payload = self._probe_forward()
        if payload is None:
            self.last_error = '远端 Hub 本地端口已占用，未连接到其他已有服务'
            raise ConnectionError(self.last_error)
        self.validate(payload)
        return True

    def ensure(self):
        if self.cfg.get('disabled'):
            raise ConnectionError('玩家全知來源已關閉')
        if not self.remote:
            return
        if self.process is not None and self.process.poll() is None:
            return
        if self.process is not None:
            self.process.wait()
            self.process = None
            self.failures += 1
            self.last_error = 'SSH 隧道已退出，请检查源电脑和 Tailscale'
        if self._reuse_healthy_forward():
            return
        if time.monotonic() - self.last_attempt < min(20, 2 ** min(self.failures, 4)):
            raise ConnectionError(self.last_error or '正在重连')
        self.last_attempt = time.monotonic()
        if self._reuse_healthy_forward():
            return
        (ROOT / 'logs').mkdir(exist_ok=True)
        if self.log is None:
            self.log = (ROOT / 'logs/remote-tunnel.log').open('ab')
        # The destination is an IPv6 literal; leave listener address families automatic.
        # macOS ssh -6 otherwise maps 127.0.0.1 to an unbindable IPv6 address.
        args = ['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=10',
                '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
                '-o', 'IdentitiesOnly=yes', '-o', 'UserKnownHostsFile=' + str(Path(self.cfg['known_hosts']).expanduser()),
                '-i', str(Path(self.cfg['identity_file']).expanduser()),
                '-p', str(self.cfg.get('ssh_port', 22)),
                '-L', '127.0.0.1:' + str(self.cfg['port']) + ':127.0.0.1:' + str(self.cfg.get('remote_port', 8770)),
                self.cfg['ssh_user'] + '@' + self.cfg['ssh_host']]
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,**options)

    def validate(self, payload):
        if payload.get('protocol_version') != 1 or payload.get('service') != 'sgi-crossover-bridge-1':
            raise ValueError('采集服务版本不兼容，请同步升级采集源')
        expected = self.cfg.get('expected_source')
        if expected and payload.get('source_id') != expected:
            raise ValueError('连接来源不符：' + str(payload.get('source_id')))
        if self.remote and payload.get('read_only_endpoint') is not True:
            raise ValueError('远端连接不是只读采集接口')
        self.failures = 0

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

CONNECTION = Connection(load_config())
