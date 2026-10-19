"""P60 command panel backend for the Fengye status Hub.

Issues *synthetic* faction commands (the ones verified on 2026-10-19) through the
lab's one-shot agent, from a local client, without touching the game UI.

Everything here is local: the Hub runs on the same Mac as the three Wine
clients, so the panel shells out to the lab tools:

    <lab>/tools/p60_generic_cmd_inject.py   arm one agent (per target prefix)
    <lab>/p60_go_*.flag                      trigger file (touch = "fire when the
                                              agent's phase gate is satisfied")
    <lab>/p60_receipt_*.bin                 64-byte receipt written by the agent

Smart routing: the agent is always armed with `--require-phase 1`, so a command
sent while the game is *not* in the domestic phase waits (inside the game
process, 250 ms polling) and fires as soon as phase 1 begins. `send()` reports
the phase at submit time and whether the job is queued.

Only read-only probes are used for discovery (phase, forces, cities) and each
send is exactly one command, once-only, never retried.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import threading
import time
import uuid
from pathlib import Path

RECEIPT_KEYS = ('magic2 rc core own gate_before gate_after phase tick '
                'vtable kind subtype operand f14 f18 f1c f20').split()
RECEIPT_MAGIC2 = 0x53365243
PRESETS = ('train', 'alms', 'rice', 'build', 'personnel', 'phaseend')
BUILD_TYPES = {4: '火計', 5: '落石', 6: '陷阱', 7: '練兵所', 8: '牧場', 9: '弓工坊'}
TROOPS = {0: '步兵', 1: '騎兵', 2: '弓兵'}

# client prefix -> label shown in the panel
TARGETS = (
    ('prefix-dingman-local', '丁滿（主機）'),
    ('prefix-sikarugir10', '風雲'),
    ('prefix-fengye-shadow', '風夜（藏身）'),
)


def _default_lab():
    env = os.environ.get('SGI_LAB')
    if env:
        return Path(env).expanduser()
    return Path.home() / 'sgi-fengye-lab' / 'shadow'


class CommandService:
    def __init__(self, lab=None, runner=None, wine=None, p32=None):
        self.lab = Path(lab).expanduser() if lab else _default_lab()
        self.runner = runner or subprocess.run
        self.wine = wine or str(Path.home() / 'Library/Application Support/SGI-Wine'
                                / 'runtime-sikarugir10/wswine.bundle/bin/wine')
        self.p32 = p32 or str(Path.home() / 'sgi-fengye-lab/python32/python.exe')
        self.dyld = str(Path.home() / 'Library/Application Support/SGI-Wine/dependency-lib')
        self.z = 'Z:\\Users\\vk\\sgi-fengye-lab\\shadow'
        self.jobs = []
        self.queue = []
        self.flush_state = {'running': False, 'phase': 'idle', 'note': ''}
        self.lock = threading.Lock()
        self._cache = {}
        self._cache_at = 0.0

    # ------------------------------------------------------------------ utils
    def _env(self, prefix):
        env = dict(os.environ)
        env.update({'WINEPREFIX': str(Path.home() / 'Library/Application Support/SGI-Wine' / prefix),
                    'WINEDEBUG': '-all', 'PYTHONIOENCODING': 'utf-8',
                    'DYLD_FALLBACK_LIBRARY_PATH': self.dyld,
                    'SGI_GAME_EXE': r'C:\sgi\run-3.5\3I\SANPK.exe'})
        return env

    def _run(self, prefix, args, timeout=30):
        cmd = [self.wine, self.p32] + args
        res = self.runner(cmd, capture_output=True, text=True,
                          env=self._env(prefix), timeout=timeout)
        return res

    def _py(self, prefix, script_zpath, extra=(), timeout=30):
        res = self._run(prefix, [script_zpath] + list(extra), timeout=timeout)
        out = (res.stdout or '').strip().splitlines()
        for line in reversed(out):
            line = line.strip()
            if line.startswith('{'):
                try:
                    return json.loads(line)
                except ValueError:
                    continue
        return {'error': 'no json output', 'stderr': (res.stderr or '')[-400:]}

    def pid(self, prefix):
        res = self._run(prefix, [self.z + '\\tools\\find_sanpk_pid.py'], timeout=25)
        for line in reversed((res.stdout or '').strip().splitlines()):
            line = line.strip()
            if line.isdigit():
                return int(line)
        return None

    def phase(self, prefix='prefix-dingman-local'):
        res = self._run(prefix, [self.z + '\\tools\\roundprobe.py', '--bridge',
                                 self.z + '\\bridge', '--samples', '1'], timeout=25)
        for line in reversed((res.stdout or '').strip().splitlines()):
            line = line.strip()
            if line.startswith('{'):
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                return data.get('phase_4d8'), data
        return None, None

    # --------------------------------------------------------------- discovery
    def targets(self, refresh=False):
        now = time.time()
        if not refresh and self._cache and now - self._cache_at < 8:
            return self._cache
        out = {'ok': True, 'at': now, 'targets': [], 'phase': None, 'phase_text': '',
               'forces': [], 'cities': [], 'build_types': BUILD_TYPES, 'troops': TROOPS,
               'presets': PRESETS}
        phase, raw = self.phase()
        out['phase'] = phase
        out['phase_text'] = {0: '回合開始', 1: '內政（可送）', 2: '?2', 3: '結算中',
                             4: '結算中', 5: '結算中'}.get(phase, '未知')
        for prefix, label in TARGETS:
            pid = self.pid(prefix)
            out['targets'].append({'prefix': prefix, 'label': label, 'pid': pid,
                                   'alive': bool(pid)})
        # forces + cities come from whichever client is alive (prefer the host)
        for prefix, label in TARGETS:
            if not any(t['pid'] for t in out['targets'] if t['prefix'] == prefix):
                continue
            pid = next(t['pid'] for t in out['targets'] if t['prefix'] == prefix)
            lords = self._py(prefix, self.z + '\\tools\\lord_read_any.py', [str(pid)])
            if lords.get('ok'):
                out['forces'] = [{'force_id': r['force_id'], 'name': r['name'],
                                  'gold': r.get('gold'), 'rice': r.get('rice'),
                                  'troop_stock': r.get('troop_stock'),
                                  'armament': r.get('armament')} for r in lords.get('lords') or []]
                break
        for prefix, label in TARGETS:
            alive = next((t['pid'] for t in out['targets'] if t['prefix'] == prefix), None)
            if not alive:
                continue
            slots = self._py(prefix, self.z + '\\tools\\_p60_slots.py', [str(alive)])
            if slots.get('ok'):
                out['player_slots'] = [{'slot': r.get('slot'), 'nickname': r.get('nickname'),
                                        'force_id': r.get('force_id')} for r in slots.get('slots') or []]
                break
        for prefix, label in TARGETS:
            alive = next((t['pid'] for t in out['targets'] if t['prefix'] == prefix), None)
            if not alive:
                continue
            cities = self._py(prefix, self.z + '\\tools\\_p60_cities_lite.py', [str(alive)])
            if cities.get('ok'):
                out['cities'] = cities.get('cities') or []
                break
        self._cache, self._cache_at = out, now
        return out

    def battlefield(self):
        """2026-10-19：把「各勢力基礎情報／城池／部隊」給情報台用（單次採集）。"""
        for prefix, _label in TARGETS:
            pid = self.pid(prefix)
            if not pid:
                continue
            data = self._py(prefix, self.z + '\\tools\\_p60_battle.py', [str(pid)])
            if data.get('ok'):
                data['source_prefix'] = prefix
                return data
        return {'ok': False, 'error': '沒有可讀的客戶端'}

    def free_cells(self, prefix, city_xy, force):
        pid = self.pid(prefix)
        if not pid:
            return []
        data = self._py(prefix, self.z + '\\tools\\_p60_pick_cell_wide.py',
                        [str(pid), str(city_xy[0]), str(city_xy[1]), str(force)])
        return [c['xy'] for c in data.get('candidates') or []]

    # ----------------------------------------------------------------- sending
    def _ghost_home_slot(self, default=5):
        """風夜的家=無勢力席位；以現行 slotkeep 的 --slot 為準，讀不到就回 5。"""
        try:
            res = self.runner(['pgrep', '-fl', 'shadow_slotkeep'], capture_output=True, text=True, timeout=5)
            text = res.stdout or ''
            for token in text.split():
                if token.startswith('--slot'):
                    pass
            import re as _re
            match = _re.search(r'--slot\s+(\d+)', text)
            if match:
                return int(match.group(1))
        except Exception:  # noqa: BLE001
            pass
        return default

    def _switch_slot(self, slot, timeout=60):
        """2026-10-19：風夜下指令前要臨時把席位切到目標勢力，送完再切回。"""
        script = self.lab / 'shadow_force.sh'
        if not script.exists():
            return False, 'shadow_force.sh 不在 lab'
        try:
            res = self.runner(['bash', str(script), 'switch', str(slot)], capture_output=True,
                              text=True, timeout=timeout, cwd=str(self.lab))
        except Exception as exc:  # noqa: BLE001
            return False, '%s: %s' % (type(exc).__name__, exc)
        text = ((res.stdout or '') + (res.stderr or '')).strip().splitlines()
        return res.returncode == 0, (text[-1] if text else '')

    def build_args(self, job):
        preset = job.get('preset')
        job = dict(job, **(job.get('params') or {}))   # params live one level down
        prefix = job['prefix']
        tag = job['tag']
        flag = self.z + '\\p60_ui_%s.flag' % tag
        receipt = self.z + '\\p60_ui_%s.bin' % tag
        state = self.z + '\\p60_ui_%s.json' % tag
        args = [self.z + '\\tools\\p60_generic_cmd_inject.py', '--force',
                '--preset', preset, '--actor', str(int(job.get('actor', 0))),
                '--agent-bin', self.z + '\\tools\\agent_generic.bin',
                '--koeinm', r'C:\sgi\run-3.5\3I\Koeinm.dll',
                '--flag', flag, '--receipt', receipt, '--state', state,
                '--require-phase', '1']
        if preset == 'train':
            args += ['--troop', str(int(job.get('troop', 0))),
                     '--value', str(int(job.get('value', 100))),
                     '--extra', str(int(job.get('extra', 0)))]
        elif preset == 'alms':
            args += ['--value', str(int(job.get('value', 0))),
                     '--extra', str(int(job.get('extra', 4)))]
        elif preset == 'rice':
            args += ['--buy', str(int(job.get('buy', 1))),
                     '--value', str(int(job.get('value', 100))),
                     '--extra', str(int(job.get('extra', 0)))]
        elif preset == 'build':
            args += ['--build-type', str(int(job.get('build_type', 8))),
                     '--x', str(int(job.get('x', 0))), '--y', str(int(job.get('y', 0))),
                     '--value', str(int(job.get('city', 0))),
                     '--extra', str(int(job.get('extra', 2000)))]
        elif preset == 'personnel':
            args += ['--subtype', str(int(job.get('subtype', 0))),
                     '--target', str(int(job.get('target_id', -1)))]
        return args, flag, receipt

    def validate(self, payload, info):
        """Refuse commands that are known to be invalid (and have crashed clients).

        2026-10-19 22:17: one build with actor=0/city=0/xy=(0,0) produced an AV at
        0x44C156 in all three clients at the round settlement. The panel must
        never send that shape again.
        """
        preset = payload.get('preset')
        forces = {f['force_id'] for f in info.get('forces') or []}
        actor = payload.get('actor')
        try:
            actor = int(actor)
        except (TypeError, ValueError):
            return '勢力未選擇'
        if actor not in forces:
            return '勢力不在本局（force=%s）' % actor
        if preset == 'build':
            cities = {c['city_id']: c for c in info.get('cities') or []}
            try:
                cid = int(payload.get('city'))
                x = int(payload.get('x')); y = int(payload.get('y'))
            except (TypeError, ValueError):
                return '建設參數不完整'
            city = cities.get(cid)
            if not city:
                return '城池 %s 不在本局' % cid
            if city.get('owner') != actor:
                return '城池 %s（%s）不屬於該勢力（owner=%s）' % (
                    cid, city.get('name'), city.get('owner'))
            bx, by = city.get('xy') or [0, 0]
            if abs(x - bx) > 5 or abs(y - by) > 5:
                return '座標 (%s,%s) 離城太遠（城在 %s,%s）' % (x, y, bx, by)
            if (x, y) == (bx, by):
                return '不能蓋在城池格上'
        if preset == 'personnel':
            if int(payload.get('target_id') or -1) < 0:
                return '人事命令需要武將 id'
        return None

    def queue_add(self, payload):
        info = self.targets()
        reason = self.validate(payload, info)
        if reason:
            return {'ok': False, 'error': reason}
        item = dict(payload)
        item['queued_at'] = time.time()
        item['id'] = uuid.uuid4().hex[:8]
        with self.lock:
            self.queue.append(item)
        return {'ok': True, 'queue': self.queue_view()['queue']}

    def queue_clear(self):
        with self.lock:
            self.queue = []
        return {'ok': True, 'queue': []}

    def queue_view(self):
        with self.lock:
            items = list(self.queue)
        return {'ok': True, 'queue': [{k: v for k, v in it.items()} for it in items],
                'flush': dict(self.flush_state)}

    def flush_queue(self):
        """把佇列裡同一勢力的命令，在『下一個內政階段』一次全部送出。

        流程（2026-10-19 實測條件）：
          1. 等到非內政階段（結算期）；
          2. 風夜的話先把席位借到該勢力（切換必須早於指令階段）；
          3. 逐條 arm（agent 會自己等到內政階段）；
          4. 全部收到回執後把席位切回。
        佇列裡若有多個勢力，只處理第一個勢力，其餘留到下一回合。
        """
        with self.lock:
            if self.flush_state.get('running'):
                return {'ok': False, 'error': '上一批還在跑'}
            if not self.queue:
                return {'ok': False, 'error': '佇列是空的'}
            batch = []
            force = self.queue[0].get('actor')
            for item in self.queue:
                if item.get('actor') == force:
                    batch.append(item)
            self.queue = [it for it in self.queue if it.get('actor') != force]
            self.flush_state = {'running': True, 'phase': 'waiting',
                                'note': '等結算期（%d 條，force %s）' % (len(batch), force)}
        thread = threading.Thread(target=self._flush_worker, args=(batch, force), daemon=True,
                                  name='cmd-flush')
        thread.start()
        return {'ok': True, 'batch': len(batch), 'force': force}

    def _flush_worker(self, batch, force):
        info = self.targets(refresh=True)
        prefix = batch[0].get('prefix')
        home = None
        try:
            # 1) 等到非內政階段
            deadline = time.time() + 200
            while time.time() < deadline:
                phase, _ = self.phase()
                if phase != 1:
                    break
                time.sleep(2)
            # 2) 借席（風夜專用）
            if prefix == 'prefix-fengye-shadow':
                row = next((r for r in info.get('player_slots') or []
                            if r.get('force_id') == force and isinstance(r.get('slot'), int)), None)
                if row is None:
                    self.flush_state = {'running': False, 'phase': 'error',
                                        'note': '找不到 force %s 的席位' % force}
                    return
                home = self._ghost_home_slot()
                ok_switch, note = self._switch_slot(row['slot'])
                if not ok_switch:
                    self.flush_state = {'running': False, 'phase': 'error',
                                        'note': '切席位失敗：' + note}
                    return
            # 3) 逐條送出（agent 自己等內政階段）
            jobs = []
            for item in batch:
                payload = dict(item)
                payload['auto_slot'] = False
                res = self.send(payload)
                jobs.append((res.get('ok'), res.get('job') or {}, res.get('error')))
                self.flush_state = {'running': True, 'phase': 'armed',
                                    'note': '已 arm %d/%d' % (len(jobs), len(batch))}
            # 4) 等回執
            self.flush_state = {'running': True, 'phase': 'firing',
                                'note': '等 %d 條回執（內政階段觸發）' % len(batch)}
            deadline = time.time() + 240
            while time.time() < deadline:
                done = 0
                for _ok, job, _err in jobs:
                    view = next((j for j in self.jobs_view()['jobs'] if j.get('id') == job.get('id')), None)
                    if view and view.get('receipt'):
                        done += 1
                if done >= len(batch):
                    break
                time.sleep(2)
            # 5) 還席
            if home is not None:
                self._switch_slot(home)
            fired = sum(1 for ok, job, err in jobs if ok)
            self.flush_state = {'running': False, 'phase': 'done',
                                'note': '完成：%d/%d 條已送出%s' % (
                                    fired, len(batch), '，席位已切回 %s' % home if home is not None else '')}
        except Exception as exc:  # noqa: BLE001
            self.flush_state = {'running': False, 'phase': 'error',
                                'note': '%s: %s' % (type(exc).__name__, exc)}

    def send(self, payload):
        if not isinstance(payload, dict):
            return {'ok': False, 'error': 'bad payload'}
        preset = payload.get('preset')
        if preset not in PRESETS:
            return {'ok': False, 'error': 'unknown preset'}
        prefix = payload.get('prefix')
        if prefix not in [p for p, _ in TARGETS]:
            return {'ok': False, 'error': 'unknown target'}
        pid = self.pid(prefix)
        if not pid:
            return {'ok': False, 'error': '目標客戶端不在線'}
        info = self.targets()
        reason = self.validate(payload, info)
        if reason:
            return {'ok': False, 'error': reason}
        phase, _ = self.phase()
        job = {'id': uuid.uuid4().hex[:10], 'tag': uuid.uuid4().hex[:8], 'prefix': prefix,
               'preset': preset, 'phase_at_submit': phase, 'status': 'arming',
               'created': time.time(), 'receipt': None, 'error': None,
               'params': {k: payload.get(k) for k in
                          ('actor', 'troop', 'value', 'extra', 'buy', 'build_type', 'x', 'y',
                           'city', 'subtype', 'target_id')},
               'auto_slot': bool(payload.get('auto_slot'))}
        args, flag, receipt = self.build_args(job)
        job['flag'] = flag
        job['receipt_path'] = receipt
        auto_slot = bool(payload.get('auto_slot')) and prefix == 'prefix-fengye-shadow'
        target_slot = None
        original_slot = None
        if auto_slot:
            slots = info.get('player_slots') or []
            row = next((r for r in slots if r.get('force_id') == job['params'].get('actor')
                        and isinstance(r.get('slot'), int)), None)
            if row is None:
                return {'ok': False, 'error': '找不到該勢力的席位，無法臨時切換'}
            target_slot = row['slot']
            original_slot = self._ghost_home_slot()
            if original_slot == target_slot:
                original_slot = 5
            # 2026-10-19 實測：席位必須在「指令階段開始之前」切好；
            # 若現在正是內政階段，先等它結束（最多 150s），在結算期切換。
            if phase == 1:
                deadline = time.time() + 150
                while time.time() < deadline:
                    p2, _ = self.phase()
                    if p2 != 1:
                        break
                    time.sleep(2)
                phase, _ = self.phase()
            ok_switch, note = self._switch_slot(target_slot)
            job['slot_switch'] = {'to': target_slot, 'ok': ok_switch, 'note': note}
            if not ok_switch:
                return {'ok': False, 'error': '切席位失敗：' + note}
        try:
            res = self._run(prefix, args, timeout=40)
        except Exception as exc:  # noqa: BLE001
            job['status'] = 'error'
            job['error'] = '%s: %s' % (type(exc).__name__, exc)
            self._push(job)
            return {'ok': False, 'error': job['error']}
        text = (res.stdout or '') + (res.stderr or '')
        if '"thread_id"' not in text:
            job['status'] = 'error'
            job['error'] = (text.strip().splitlines() or ['injector failed'])[-1][:300]
            self._push(job)
            return {'ok': False, 'error': job['error'], 'detail': text[-500:]}
        job['status'] = 'queued' if phase != 1 else 'firing'
        # touch the trigger: the agent decides *when* (phase gate)
        try:
            Path(flag.replace(self.z, str(self.lab)).replace('\\', '/')).write_text('')
        except OSError as exc:
            job['status'] = 'error'
            job['error'] = 'cannot touch flag: %s' % exc
            self._push(job)
            return {'ok': False, 'error': job['error']}
        self._push(job)
        if auto_slot:
            job['slot_home'] = original_slot
        threading.Thread(target=self._wait_receipt, args=(job,), daemon=True).start()
        return {'ok': True, 'job': self._public(job)}

    def _push(self, job):
        with self.lock:
            self.jobs = ([job] + self.jobs)[:20]

    def _wait_receipt(self, job):
        path = Path(job['receipt_path'].replace(self.z, str(self.lab)).replace('\\', '/'))
        deadline = time.time() + 300
        while time.time() < deadline:
            if path.exists() and path.stat().st_size >= 64:
                try:
                    raw = path.read_bytes()[:64]
                    data = dict(zip(RECEIPT_KEYS, struct.unpack('<16I', raw)))
                    job['receipt'] = {
                        'rc': data['rc'], 'kind': data['kind'], 'subtype': data['subtype'],
                        'operand': data['operand'], 'actor': data['f14'], 'f18': data['f18'],
                        'f1c': data['f1c'], 'f20': data['f20'],
                        'phase_at_send': data['phase'], 'own': data['own'],
                        'gate_before': data['gate_before'], 'gate_after': data['gate_after'],
                        'tick': data['tick'], 'vtable': data['vtable'],
                        'magic_ok': data['magic2'] == RECEIPT_MAGIC2}
                    job['status'] = 'fired' if data['rc'] else 'send_failed'
                except Exception as exc:  # noqa: BLE001
                    job['status'] = 'error'
                    job['error'] = 'receipt parse: %s' % exc
                job['finished'] = time.time()
                home = job.get('slot_home')
                if home is not None:
                    ok_restore, note = self._switch_slot(home)
                    job['slot_restore'] = {'to': home, 'ok': ok_restore, 'note': note}
                return
            time.sleep(0.5)
        job['status'] = 'armed_waiting'
        job['error'] = ('300s 內沒有等到內政階段（agent 仍在客戶端裡等待，席位維持在 %s，'
                        '需要時用 shadow_force.sh switch 5 還原）' % job.get('slot_switch'))

    def _public(self, job):
        out = {k: v for k, v in job.items() if k not in ('flag', 'receipt_path')}
        out['waited'] = round((job.get('finished') or time.time()) - job['created'], 1)
        return out

    def jobs_view(self):
        with self.lock:
            return {'ok': True, 'jobs': [self._public(j) for j in self.jobs]}
