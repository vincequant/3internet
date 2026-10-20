"""風夜 probe 指令橋（Hub → P34 probe 控制檔 → P40 D5 → 主機）。

P40 靜態結論：主機的批次收集「不驗證成員上傳的 sender」，所以 probe
以自己 member id 上傳的 D5（control 5 + CSanInetDomesticCmd）會被直接
併入批次，等同 P58 UI 的遊戲自家送出路徑；p60 的 SendObject standalone
則會被 sender/sync 檢查丟棄。

probe 端（p34_d8_probe.py）已內建：
  --control-file            讀 Hub 寫的 {"id","op":"d5","record":{...}}
  --control-result          寫回 {"id","op","rc","raw_rc","target",...}
  --d5-authorization-file   P40 receipt（own/host/observed_wall/600s）

本模組只負責 Hub 這一側：組 record、寫授權、寫 request、等 result。
"""
import json
import time
import uuid
from pathlib import Path

PRESET_SUBTYPE = {'train': 0, 'alms': 2, 'rice': 3, 'build': 4}
FIELD_ORDER = ('actor', 'parameter', 'value', 'extra', 'subtype', 'operand')


def build_record(job):
    """把 Hub job 轉成 P40 domestic_record 的欄位（54B 同構）。

    p60 54B 佈局：kind=18, subtype, operand(座標 packed), text_len=0,
    actor, parameter(建設種類), value(城池), extra(花費)。
    """
    job = dict(job, **(job.get('params') or {}))
    preset = job.get('preset')
    if preset not in PRESET_SUBTYPE:
        raise ValueError('probe_sender_only_supports_domestic_presets')
    actor = int(job['actor'])
    if preset == 'build':
        x, y = int(job.get('x', 0)), int(job.get('y', 0))
        return {'actor': actor, 'parameter': int(job.get('build_type', 8)),
                'value': int(job.get('city', 0)), 'extra': int(job.get('extra', 2000)),
                'subtype': PRESET_SUBTYPE[preset], 'operand': (y << 16) | x}
    if preset == 'train':
        return {'actor': actor, 'parameter': int(job.get('troop', 0)),
                'value': int(job.get('value', 100)), 'extra': int(job.get('extra', 0)),
                'subtype': PRESET_SUBTYPE[preset], 'operand': 0}
    if preset == 'alms':
        return {'actor': actor, 'parameter': 0, 'value': int(job.get('value', 0)),
                'extra': int(job.get('extra', 4)), 'subtype': PRESET_SUBTYPE[preset],
                'operand': 0}
    return {'actor': actor, 'parameter': int(job.get('buy', 1)),
            'value': int(job.get('value', 100)), 'extra': int(job.get('extra', 0)),
            'subtype': PRESET_SUBTYPE[preset], 'operand': 0}


class ProbeSender:
    """控制檔讀寫；probe 端仍是最終授權者（d5_authorized + D5Gate）。"""

    def __init__(self, lab, z, run, *, host_prefix='prefix-dingman-local',
                 ghost_name=None, host_name='丁满', poll=0.4, timeout=20.0):
        self.lab = Path(lab)
        self.z = z                # Windows Z: path of the shadow lab
        self.run = run            # CommandService._py(prefix, script, args)
        self.host_prefix = host_prefix
        self.ghost_name, self.host_name = ghost_name, host_name
        self.poll, self.timeout = poll, timeout
        self.control = self.lab / 'hub_control.json'
        self.result = self.lab / 'hub_control_result.json'
        self.auth = self.lab / 'hub_d5_auth.json'

    # ---------------------------------------------------------------- ids
    def ids(self, host_pid):
        """主機 member table：回 (own_id=風夜, host_id=房主)。"""
        out = self.run(self.host_prefix,
                       self.z + '\\tools\\member_table.py', [str(host_pid)])
        entries = []
        for line in (out or '').splitlines():
            parts = line.split()
            if len(parts) >= 8 and parts[0].isdigit():
                entries.append({'name': parts[7], 'id': int(parts[4])})
        own = next((e['id'] for e in entries
                    if self.ghost_name and e['name'] == self.ghost_name), None)
        if own is None:
            own = next((e['id'] for e in entries
                        if e['name'] not in (self.host_name, '风云')), None)
        host = next((e['id'] for e in entries if e['name'] == self.host_name), None)
        if own is None or host is None or own == host:
            raise ValueError('probe_sender_member_ids_not_found')
        return own, host

    # ------------------------------------------------------------- control
    def arm(self, own, host, now=None):
        now = time.time() if now is None else now
        self.auth.write_text(json.dumps({
            'contract': 'P40', 'enable_d5': True, 'test_game_confirmed': True,
            'own_id': int(own), 'host_id': int(host), 'observed_wall': now},
            ensure_ascii=False), encoding='utf-8')
        return now

    def send(self, record, request_id=None):
        rid = request_id or uuid.uuid4().hex
        try:
            self.result.unlink()
        except FileNotFoundError:
            pass
        self.control.write_text(json.dumps(
            {'id': rid, 'op': 'd5', 'record': record}, ensure_ascii=False),
            encoding='utf-8')
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.result.exists():
                try:
                    data = json.loads(self.result.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    time.sleep(self.poll)
                    continue
                if data.get('id') != rid:
                    time.sleep(self.poll)
                    continue
                return {'request_id': rid, 'result': data,
                        'ok': bool(data.get('rc')), 'raw_rc': data.get('raw_rc'),
                        'target': data.get('target')}
            time.sleep(self.poll)
        return {'request_id': rid, 'ok': False, 'error': 'probe_control_timeout'}


def receipt_record(job):
    """Job → 單筆 record 的穩定序列化（測試與 log 用）。"""
    record = build_record(job)
    return {k: int(record[k]) for k in FIELD_ORDER}
