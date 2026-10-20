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
import math
import os
import struct
import subprocess
import threading
import time
import uuid
from hashlib import sha256
from pathlib import Path

RECEIPT_KEYS = ('magic2 rc core own gate_before gate_after phase tick '
                'vtable kind subtype operand f14 f18 f1c f20').split()
RECEIPT_MAGIC2 = 0x53365243
PRESETS = ('train', 'alms', 'rice', 'build', 'personnel', 'phaseend')
BUILD_TYPES = {6: '陷阱', 7: '兵營', 8: '馬房', 9: '弓房'}
TROOPS = {0: '步兵', 1: '騎兵', 2: '弓兵'}
# 佔用格子的說法（去重用；同一格只能有一個物件）
OCCUPIED_TEXT = {'building': '建築', 'trap': '陷阱', 'city': '城池/關卡'}
BUSY_STATUS = ('held', 'pending', 'validating', 'waiting_phase_exit', 'switching_slot',
               'arming', 'queued', 'firing', 'waiting_phase', 'awaiting_receipt',
               'armed_waiting', 'unknown', 'restoring', 'restore_failed',
               'waiting_effect', 'fired', 'verifying')
CANCELLABLE = ('held', 'pending', 'validating', 'waiting_phase_exit', 'waiting_effect')
UNRESOLVED = ('unknown', 'restore_failed')
TERMINAL = ('cancelled', 'error', 'send_failed', 'completed')
_DISPATCH_LOCK = threading.Lock()

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
    def __init__(self, lab=None, runner=None, wine=None, p32=None, history_path=None):
        self.lab = Path(lab).expanduser() if lab else _default_lab()
        self.runner = runner or subprocess.run
        self.wine = wine or str(Path.home() / 'Library/Application Support/SGI-Wine'
                                / 'runtime-sikarugir10/wswine.bundle/bin/wine')
        self.p32 = p32 or str(Path.home() / 'sgi-fengye-lab/python32/python.exe')
        self.dyld = str(Path.home() / 'Library/Application Support/SGI-Wine/dependency-lib')
        self.z = 'Z:\\Users\\vk\\sgi-fengye-lab\\shadow'
        self.jobs = []
        self.pre_seat = None
        # 2026-10-21 使用者定案：改為「開局綁定某個玩家」，不再開局自動切回無勢力。
        self.auto_restore_after_start = False
        self.auto_restore_delay = 8.0
        self._restored_games = set()
        self._game_seen_at = {}
        self.queue = []
        self.flush_state = {'running': False, 'phase': 'idle', 'note': ''}
        self.lock = threading.RLock()
        self.history_path = Path(history_path) if history_path else None
        self.pre_seat = self._load_pre_seat()
        self._worker_running = False
        self._worker_generation = 0
        self._verify_running = False
        self._verification_jobs = {}
        self.phase_wait_timeout = 600
        self.reference_check_interval = 20.0
        self.reference_prefixes = ('prefix-sikarugir10', 'prefix-dingman-local')
        self.receipt_timeout = 300
        self.verification_timeout = 120
        self.poll_interval = 0.5
        self._cache = {}
        self._cache_at = 0.0
        self._targets_lock = threading.Lock()
        self._targets_at = 0.0
        self._occupied = {}          # prefix -> (at, {(x,y): kind})
        self._battle_lock = threading.Lock()
        self._battle_cache = {}
        self._battle_at = 0.0
        self.current_game_key = None
        self.current_game_token = None
        self._game_identity_key = None
        self._game_identity = None
        self._observation_game_key = None
        self.game_identity_limitation = ('原始獨立局 ID 未知；這是本輪觀測識別，'
                                        '同進程／核心重用不保證可辨認新局')
        self._load_history()

    # ------------------------------------------------------------------ utils
    def _env(self, prefix):
        env = dict(os.environ)
        env.update({'WINEPREFIX': str(Path.home() / 'Library/Application Support/SGI-Wine' / prefix),
                    'WINEDEBUG': '-all', 'PYTHONIOENCODING': 'utf-8',
                    'DYLD_FALLBACK_LIBRARY_PATH': self.dyld,
                    'SGI_GAME_EXE': r'C:\sgi\run-3.5\3I\SANPK.exe',
                    'SGI_BRIDGE_Z': self.z + '\\bridge'})
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

    def phase(self, prefix='prefix-fengye-shadow'):
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

    @staticmethod
    def _round_state(phase, data):
        """One comparable round tuple from roundprobe output (read-only)."""
        if not isinstance(phase, int) or phase not in range(6):
            return None
        data = data if isinstance(data, dict) else {}
        season = data.get('f_4d6')
        year = data.get('f_4d0')
        roster = data.get('rows_f4a')
        return {'phase': phase,
                'season': season if isinstance(season, int) else None,
                'year': year if isinstance(year, int) else None,
                'roster': tuple(roster) if isinstance(roster, list) else None}

    def reference_state(self, prefix=None):
        """Read a local real player's round tuple as a staleness reference.

        The hidden observer can miss a round boundary and keep an old season
        while the real clients move on. Comparing with the player (or host)
        client locally distinguishes "still waiting" from "already stale"
        without asking the remote host.
        """
        for candidate in self.reference_prefixes:
            if prefix and candidate == prefix:
                continue
            # Skip a prefix that is not installed on this Mac (e.g. the host
            # runs remotely) without paying a Wine start-up timeout.
            if not (Path.home() / 'Library/Application Support/SGI-Wine' / candidate).is_dir():
                continue
            try:
                phase, data = self.phase(candidate)
            except Exception:  # noqa: BLE001 - a missing local client is normal
                continue
            state = self._round_state(phase, data)
            if state and state.get('season') is not None:
                return state
        return None

    @staticmethod
    def _staleness_error(shadow, reference):
        """Return a user-facing explanation when the shadow missed a round."""
        if not shadow or not reference:
            return None
        shadow_season, reference_season = shadow.get('season'), reference.get('season')
        if not (isinstance(shadow_season, int) and isinstance(reference_season, int)):
            return None
        if shadow_season >= reference_season:
            return None
        # Different rosters mean the two clients are not in the same match;
        # their season counters are not comparable.
        shadow_roster, reference_roster = shadow.get('roster'), reference.get('roster')
        if shadow_roster and reference_roster and shadow_roster != reference_roster:
            return None
        return ('代送客戶端（風夜）停在 season %d（phase %d），'
                '玩家端已在 season %d（phase %d）；請重啟風夜或改用玩家端代送'
                % (shadow_season, shadow.get('phase'),
                   reference_season, reference.get('phase')))

    @staticmethod
    def eta_text(phase, year, season):
        """Game-time estimate for the next domestic phase (not a promise).

        0.2.34 fires in the current phase when it is already phase 1.  When
        waiting, the next domestic phase is the current season's (phase 0) or
        the following season's (phase 2 and later); seasons are 0..3.
        """
        if not (isinstance(phase, int) and phase in range(6) and
                isinstance(year, int) and isinstance(season, int) and 0 <= season <= 3):
            return None
        names = '春夏秋冬'
        if phase == 1:
            return '%d年%s內政階段（現在）' % (year, names[season])
        step = 1 if phase >= 2 else 0
        next_season = season + step
        next_year = year + next_season // 4
        next_season %= 4
        return '%d年%s內政階段結束後' % (next_year, names[next_season])

    # --------------------------------------------------------------- discovery
    @staticmethod
    def _identity_facts(binding):
        """Only observed stable identity facts, never timestamps or player slot."""
        keys = ('identity', 'core_address', 'build_sha256', 'schema', 'scenario_map',
                'roster', 'run_id', 'game_id', 'session_id', 'run_identity', 'game_identity')
        result = {key: binding[key] for key in keys if key in binding}
        # _binding deliberately keeps only these three process identity fields.
        # Exclude observer player_context/slot even if a future collector adds it.
        result['identity'] = {key: (binding.get('identity') or {}).get(key)
                              for key in ('pid', 'path', 'creation_filetime')}
        for key in ('run_id', 'game_id', 'session_id', 'run_identity', 'game_identity'):
            if 'identity.' + key in binding:
                result['identity.' + key] = binding['identity.' + key]
        return result

    @staticmethod
    def _identity_digest(facts):
        return sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False,
                                 separators=(',', ':')).encode('utf-8')).hexdigest()

    def _adopt_game(self, state):
        """Bind the display to observed process/core/roster facts, never a UUID.

        The same proven facts survive a panel restart. No independent game ID
        is invented; exact same-process/core/scenario/roster reuse remains an
        explicit limitation, and never clears an unknown live-agent gate.
        """
        try:
            if not isinstance(state, dict) or state.get('readonly') is not True:
                raise ValueError('missing readonly state')
            if (state.get('consistency') or {}).get('root_headers_and_clock_unchanged') is not True:
                raise ValueError('unstable state')
            from fengye_command_effects import _binding
            facts = self._identity_facts(_binding(state))
            identity_key = self._identity_digest(facts)
        except (ValueError, TypeError, KeyError):
            with self.lock:
                self.current_game_key = None
            return None
        with self.lock:
            if identity_key != self._game_identity_key:
                self._game_identity_key, self._game_identity = identity_key, facts
                self.current_game_token = 'observed-' + identity_key[:20]
                self._observation_game_key = identity_key
                self._cache = {}
                self._targets_at = 0.0
                self._occupied.clear()
                for job in self.jobs:
                    if job.get('status') in CANCELLABLE and job.get('game_key') != self._observation_game_key:
                        job['finished'] = time.time()
                        self._update(job, 'cancelled', '觀測到不同局面身分；舊局未發送請求已取消')
                self.queue = [q for q in self.queue
                              if q.get('game_key') == self._observation_game_key]
                self._verification_jobs = {
                    key: item for key, item in self._verification_jobs.items()
                    if item['job'].get('game_key') == self._observation_game_key}
            self.current_game_key = self._observation_game_key
            return self.current_game_key

    def _current_game_fields(self):
        return {'game_key': self.current_game_key,
                'game_token': self.current_game_token if self.current_game_key else None,
                'game_identity_key': self._game_identity_key if self.current_game_key else None,
                'game_identity': self._game_identity if self.current_game_key else None,
                'game_identity_limitation': self.game_identity_limitation}

    def targets(self, refresh=False):
        requested = time.monotonic()
        with self._targets_lock:
            if self._cache and ((not refresh and requested - self._targets_at < 3) or
                                self._targets_at >= requested):
                return self._cache
            result = self._read_targets(refresh=True)
            self._targets_at = time.monotonic()
            return result

    def _read_targets(self, refresh=False):
        now = time.time()
        if not refresh and self._cache and now - self._cache_at < 3:
            return self._cache
        prefix = 'prefix-fengye-shadow'
        battle = self.battlefield(refresh=refresh)
        self._adopt_game(battle.get('state') if battle.get('ok') else None)
        pid = battle.get('source_pid')
        captured = battle.get('captured_at')
        try:
            if isinstance(captured, str):
                from datetime import datetime
                captured = datetime.fromisoformat(captured.replace('Z', '+00:00')).timestamp()
            elif captured is not None:
                captured = float(captured)
        except (ValueError, TypeError):
            captured = None
        raw_lords = {r.get('force_id'): r for r in
                     ((battle.get('state') or {}).get('entities') or {}).get('lords') or []}
        forces = []
        for lord in battle.get('lords') or []:
            row = dict(lord)
            raw = raw_lords.get(row.get('force_id')) or {}
            row['armament_raw'] = dict(raw.get('armament_raw') or {})
            forces.append(row)
        out = {'ok': bool(battle.get('ok')), 'at': captured,
               'targets': [{'prefix': prefix, 'label': '風夜（藏身）', 'pid': pid, 'alive': bool(pid)}],
               'phase': None, 'phase_text': '未知', 'forces': forces,
               'cities': battle.get('cities') or [], 'build_types': BUILD_TYPES,
               'troops': TROOPS, 'presets': PRESETS}
        out.update(self._current_game_fields())
        if not battle.get('ok'):
            out['error'] = battle.get('error') or '風夜資料尚未讀到'
            self._cache, self._cache_at = out, now
            return out
        phase, phase_data = self.phase(prefix)
        out['phase'] = phase
        out['phase_text'] = {0: '回合開始', 1: '內政', 2: '軍事', 3: '結算中',
                             4: '結算中', 5: '結算中'}.get(phase, '未知')
        if isinstance(phase_data, dict):
            # Year/season of the delivery client, used for the game-time ETA.
            out['year'] = (phase_data.get('f_4d0')
                           if isinstance(phase_data.get('f_4d0'), int) else None)
            out['season'] = (phase_data.get('f_4d6')
                             if isinstance(phase_data.get('f_4d6'), int) else None)
        slots = self._py(prefix, self.z + '\\tools\\_p60_slots.py', [str(pid)])
        if slots.get('ok'):
            out['player_slots'] = [{'slot': r.get('slot'), 'nickname': r.get('nickname'),
                                    'force_id': r.get('force_id')} for r in slots.get('slots') or []]
            # 風夜自己的 force：藏身/旁聽時為 None；入座後才有，且只有這個
            # 勢力的指令是「用自己的席位」送出（主機才會認 sender id）。
            out['local'] = slots.get('local') if isinstance(slots.get('local'), dict) else None
        # 看到「這一局」而風夜已經坐在有勢力的席位上 → 認定為這局的開局前上身。
        # 2026-10-21 00:2x：大廳階段（phase 0）還沒有 game_key，舊條件寫成 phase==0
        # 反而永遠記不到（使用者按了套用、進局後卻被閘門擋）。改成只要有 key 且
        # 風夜正坐在有勢力的席位就記一次；真正的驗收仍看主機收集陣列。
        if out.get('game_key'):
            self._game_seen_at.setdefault(out['game_key'], time.time())
        local = out.get('local') or {}
        if (out.get('game_key') and isinstance(local.get('force_id'), int)
                and local.get('force_id') >= 0):
            have = self.pre_seat or {}
            if have.get('game_key') != out.get('game_key'):
                self.record_pre_seat(local.get('slot'), out.get('game_key'))
        seat = self.pre_seat or {}
        out['pre_seat'] = {'ok': bool(seat and out.get('game_key')
                                      and seat.get('game_key') == out.get('game_key')),
                           'slot': seat.get('slot')}
        try:
            self._expire_stale_jobs(out.get('season'))
        except Exception:  # noqa: BLE001
            pass
        try:
            self._maybe_auto_restore(out)
        except Exception:  # noqa: BLE001
            pass
        self._cache, self._cache_at = out, now
        return out

    def room_players(self, prefix='prefix-fengye-shadow'):
        """讀房間玩家名單（給「開局綁定」下拉用名字而不是編號）。"""
        try:
            pid = self.pid(prefix)
            if not pid:
                return {'ok': False, 'players': []}
            data = self._py(prefix, self.z + '\\tools\\p32_app_rows_read.py', [str(pid)])
            rows = []
            for table in data.get('tables') or []:
                rows.extend(table.get('rows') or [])
            if not rows:
                rows = data.get('rows') or []
        except Exception as error:  # noqa: BLE001
            return {'ok': False, 'players': [], 'error': str(error)}
        players = []
        for row in rows:
            name = (row.get('name') or '').strip()
            slot = row.get('i', row.get('index'))
            if name and isinstance(slot, int) and row.get('id'):
                players.append({'slot': slot, 'name': name})
        return {'ok': bool(players), 'players': players}

    def battlefield(self, refresh=False):
        """One shared, read-only shadow snapshot; never fall back to players."""
        requested = time.monotonic()
        with self._battle_lock:
            if self._battle_cache and ((not refresh and requested - self._battle_at < 1) or
                                      self._battle_at >= requested):
                return self._battle_cache
            prefix = 'prefix-fengye-shadow'
            pid = self.pid(prefix)
            if not pid:
                self._adopt_game(None)
                return {'ok': False, 'error': '風夜客戶端不在線；保留上次畫面'}
            data = self._py(prefix, self.z + '\\tools\\_p60_battle.py', [str(pid)])
            if data.get('ok'):
                data.update(source_prefix=prefix, source_pid=pid)
                data.setdefault('captured_at', time.time())
                state = dict(data.get('state') or {})
                state.update(source_pid=pid, source_prefix=prefix)
                self._adopt_game(state)
                data.update(self._current_game_fields())
                self._battle_cache, self._battle_at = data, time.monotonic()
            else:
                self._adopt_game(None)
            return data

    def general_ids(self, prefix, limit=24):
        """2026-10-20: 在野武將 id 清單（人事指令用下拉選，不讓使用者填數字）。"""
        pid = self.pid(prefix)
        if not pid:
            return []
        data = self._py(prefix, self.z + '\\tools\\_p60_generals.py', [str(pid)])
        rows = data.get('wild_sample') or []
        out = []
        for row in rows:
            gid = row.get('id')
            if isinstance(gid, int) and gid > 0:
                out.append(gid)
        return out[:limit]

    def free_cells(self, prefix, city_xy, force, exclude_id=None, build_type=7):
        return self.build_sites(prefix, city_xy, force, exclude_id=exclude_id,
                                with_state=False, build_type=build_type).get('cells') or []

    def build_sites(self, prefix, city_xy, force, exclude_id=None, with_state=True, build_type=7):
        """Strict read result for the picker: empty is distinct from unreadable."""
        pid = self.pid(prefix)
        if not pid:
            return {'ok': False, 'error': '風夜客戶端不在線'}
        data = self._py(prefix, self.z + '\\tools\\_p60_pick_cell_wide.py',
                        [str(pid), str(city_xy[0]), str(city_xy[1]), str(force), str(build_type)])
        if not data.get('ok'):
            return {'ok': False, 'error': data.get('error') or '無法讀取城周邊地形'}
        busy = self.busy_build_cells(exclude_id)
        occupied = ({tuple(r['xy']): r.get('kind', 'building') for r in data['occupied']}
                    if isinstance(data.get('occupied'), list) else self.occupied_cells(prefix))
        self._occupied[prefix] = (time.time(), occupied)
        result = {'ok': True, 'cells': [c['xy'] for c in data.get('candidates') or []
                                     if tuple(c['xy']) not in busy],
                'occupied': occupied, 'busy': busy,
                'captured_at': time.time()}
        if with_state:
            battle = self.battlefield()
            if not battle.get('ok') or battle.get('source_pid') != pid:
                return {'ok': False, 'error': '原地圖未讀到或客戶端已更換，請稍候再選址'}
            result.update(state=battle.get('state'), source_prefix=battle.get('source_prefix'),
                          source_pid=pid)
        return result

    # ------------------------------------------------------- 佔用格（去重複用）
    def occupied_cells(self, prefix, ttl=6.0, refresh=False):
        """客戶端上已經有東西的格子：{(x,y): 'building'|'trap'|'city'}。

        2026-10-20：遊戲的建造函式（0x4515a8 的 4/5/6 分支）建物件前**不查**
        目標格是否已被佔用，所以同一格重複下指令會疊出兩個陷阱（畫面上就是
        疊起來的兩三條血條）。這裡先讀一次佔用表，指令就不會再疊上去。
        """
        now = time.time()
        cached = self._occupied.get(prefix)
        if cached and not refresh and now - cached[0] < ttl:
            return cached[1]
        pid = self.pid(prefix)
        if not pid:
            return dict(cached[1]) if cached else {}
        data = self._py(prefix, self.z + '\\tools\\_p60_occupied.py', [str(pid)])
        if not data.get('ok'):
            # 讀不到就沿用舊表（寧可保守），完全沒有就回空
            return dict(cached[1]) if cached else {}
        cells = {}
        for row in data.get('occupied') or []:
            xy = row.get('xy') or []
            if len(xy) == 2:
                cells[(int(xy[0]), int(xy[1]))] = row.get('kind') or 'building'
        self._occupied[prefix] = (now, cells)
        return dict(cells)

    def busy_build_cells(self, exclude_id=None):
        """已經排進佇列或剛送出、還沒看到結果的建設格：{(x,y): 說明}。

        陷阱要等下一個回合結算才真的出現在記憶體裡，光看佔用表擋不住
        「連點兩下」——所以佇列與進行中的 job 也要算進去。
        """
        busy = {}
        with self.lock:
            queue = list(self.queue)
            jobs = list(self.jobs)
        for item in queue:
            if self.current_game_key and item.get('game_key') != self.current_game_key:
                continue
            if item.get('id') == exclude_id:
                continue
            if item.get('preset') != 'build':
                continue
            xy = self._job_xy(item)
            if xy:
                busy[xy] = '已在佇列（#%s）' % item.get('id')
        for job in jobs:
            if self.current_game_key and job.get('game_key') != self.current_game_key:
                continue
            if job.get('id') == exclude_id:
                continue
            if job.get('preset') != 'build' or job.get('status') not in BUSY_STATUS:
                continue
            xy = self._job_xy(job.get('params') or {})
            if xy and xy not in busy:
                busy[xy] = '剛送出（#%s，%s）' % (job.get('id'), job.get('status'))
        return busy

    @staticmethod
    def _job_xy(item):
        try:
            return (int(item.get('x')), int(item.get('y')))
        except (TypeError, ValueError):
            return None

    def build_blocker(self, payload):
        """這一格為什麼不能再蓋：回傳說明字串，可以蓋就回 None。"""
        xy = self._job_xy(payload)
        if xy is None:
            return '建設座標不完整'
        busy = self.busy_build_cells().get(xy)
        if busy:
            return '(%s,%s) %s，不重複疊加' % (xy[0], xy[1], busy)
        prefix = payload.get('prefix')
        kind = self.occupied_cells(prefix).get(xy) if prefix else None
        if kind:
            return '(%s,%s) 已經有%s，不再疊加' % (
                xy[0], xy[1], OCCUPIED_TEXT.get(kind, '物件'))
        return None

    # ----------------------------------------------------------------- sending
    def _ghost_home_slot(self, default=5):
        """風夜的家=無勢力席位；先沿用尚未還席 job 記錄的家，再看 slotkeep。

        2026-10-20：一次回執逾時會把 slotkeep 留在目標玩家的 --slot；若只讀
        pgrep，下一次就會把「玩家席」當成家。先讀未還席 job 的 slot_home。
        """
        with self.lock:
            for job in reversed(self.jobs):
                if (job.get('slot_pending_restore') and
                        isinstance(job.get('slot_home'), int)):
                    return job['slot_home']
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

    def switch_ghost_seat(self, slot, timeout=60):
        """開局前把風夜的席位切到 slot（只動席位，不武裝、不送任何指令）。

        2026-10-20 使用者要求：把「開局前上身」做成 Hub 按鈕。順序很重要——
        主機在按「開始」那一刻就決定了各席位的勢力，開局後才切只有本機視角改變。
        回傳值附上切換後讀到的 slot→force 對照，讓面板能顯示「上了哪一家」。
        """
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot <= 7:
            return {'ok': False, 'error': '席位必須是 0–7'}
        ok, note = self._switch_slot(slot, timeout=timeout)
        seat = {}
        script = self.lab / 'shadow_force.sh'
        if script.exists():
            try:
                res = self.runner(['bash', str(script), 'read'], capture_output=True,
                                  text=True, timeout=timeout, cwd=str(self.lab))
                for line in reversed((res.stdout or '').splitlines()):
                    line = line.strip()
                    if line.startswith('{'):
                        seat = json.loads(line)
                        break
            except Exception:  # noqa: BLE001
                seat = {}
        if note and note.startswith('http'):
            note = '席位已寫入'
        if ok:
            # 記住「這一局有在開局前上身」——之後才允許下單；開局後才切的
            # 不算（主機不會收）。game_key 取不到時先讀一次再記。
            key = self.current_game_key
            if not key:
                try:
                    key = (self.targets(refresh=True) or {}).get('game_key')
                except Exception:  # noqa: BLE001
                    key = None
            self.record_pre_seat(slot, key)
        return {'ok': bool(ok), 'note': note,
                'slot_now': seat.get('slot_now'),
                'slot_forces': seat.get('slot_forces') or {},
                'error': None if ok else (note or '切席位失敗')}

    def drop_client(self, prefix, timeout=45):
        """Make one local player client exit in-process (natural disconnect).

        2026-10-20 使用者要求把 p63 的一發掉線做成按鈕；破壞性操作，呼叫端
        必須先取得明確確認。風夜（旁聽端）不可作為目標。
        """
        if prefix not in dict(TARGETS) or prefix == 'prefix-fengye-shadow':
            return {'ok': False, 'error': '這個客戶端不能作為掉線目標'}
        script = self.lab / 'tools' / 'p63_drop_inject.py'
        if not script.exists():
            return {'ok': False, 'error': 'p63_drop_inject.py 不在 lab'}
        try:
            res = self._run(prefix, [self.z + '\\tools\\p63_drop_inject.py',
                                     '--target-name', 'SANPK.exe'], timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc)}
        text = ((res.stdout or '') + (res.stderr or '')).strip()
        return {'ok': res.returncode == 0, 'output': text[-400:]}

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
                # 2026-10-20 P64：走遊戲按鈕自己的送出函式 0x446482，actor 由「風夜
                # 現在佔的席位」決定（引擎內 0x44B83B）；agent 只在席位勢力 == 目標
                # 勢力時才發射，避免借席失敗時把指令記到別人的勢力上。
                '--ui-path', '--expect-actor', str(int(job.get('actor', 0))),
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

    def _pre_seat_path(self):
        base = Path(self.history_path).parent if self.history_path else Path(__file__).parent / 'data'
        return base / 'pre_seat.json'

    def _load_pre_seat(self):
        """把「開局前上身」紀錄帶過 Hub 重啟（同一局的有效性不該因重啟消失）。"""
        try:
            data = json.loads(self._pre_seat_path().read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(data, dict) or not data.get('game_key'):
            return None
        if time.time() - float(data.get('at') or 0) > 12 * 3600:
            return None
        return data

    def _save_pre_seat(self, seat):
        try:
            path = self._pre_seat_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(seat, ensure_ascii=False), encoding='utf-8')
        except Exception:  # noqa: BLE001
            pass

    def record_pre_seat(self, slot, game_key):
        """記下「這一局在開局前已坐在 slot」——之後的下單會以此放行。"""
        if not game_key:
            return None
        seat = {'slot': slot, 'game_key': game_key, 'at': time.time()}
        self.pre_seat = seat
        self._save_pre_seat(seat)
        return seat

    ACTIVE_STATES = ('pending', 'validating', 'switching_slot', 'seated',
                     'waiting_phase', 'waiting_phase_exit', 'arming', 'fired',
                     'verifying', 'restoring')

    def _expire_stale_jobs(self, season):
        """跨過約定的那一季還沒發出去 → 自動作廢，避免卡住隊列。"""
        if not isinstance(season, int):
            return
        for job in list(self.jobs):
            if job.get('status') not in self.ACTIVE_STATES:
                continue
            due = job.get('due_season')
            if isinstance(due, int) and season > due:
                self._advance(job, 'error',
                              '跨季未完成（應在第 %s 季內政發送，現在第 %s 季）；'
                              '已自動作廢，可重新下單' % (due, season))

    def has_active_jobs(self):
        return any(j.get('status') in self.ACTIVE_STATES for j in self.jobs)

    def should_auto_restore(self, info, enabled=None, restored=None, busy=False):
        """開局後是否該把風夜切回無勢力。純判斷，方便測試。"""
        enabled = self.auto_restore_after_start if enabled is None else enabled
        restored = self._restored_games if restored is None else restored
        seat = self.pre_seat or {}
        key = (info or {}).get('game_key')
        local = (info or {}).get('local') or {}
        if not enabled or not seat or not key or seat.get('game_key') != key:
            return False
        # 有指令在排隊/已武裝時不能切回 5：agent 以「本席勢力」填 actor，
        # 切回無勢力會讓它永遠等不到符合的席位（00:46 那筆就是這樣卡住）。
        if busy:
            return False
        if key in restored:
            return False
        if local.get('force_id') in (None, -1, 0xFFFFFFFF):
            return False
        # 2026-10-21：只在內政期（phase 1）切回，且開局後先等幾秒，避免
        # 12 秒的切席跨過回合邊界把客戶端卡在舊季節。
        if (info or {}).get('phase') != 1:
            return False
        seen = self._game_seen_at.get(key)
        if seen is not None and time.time() - seen < self.auto_restore_delay:
            return False
        return True

    def _maybe_auto_restore(self, info):
        if not self.should_auto_restore(info, busy=self.has_active_jobs()):
            return
        key = info.get('game_key')
        self._restored_games.add(key)
        threading.Thread(target=self._auto_restore_worker, args=(key,),
                         daemon=True, name='auto-restore').start()

    def _auto_restore_worker(self, key):
        ok, note = self._switch_slot(5)
        try:
            with self.lock:
                self.auto_restore_result = {'game_key': key, 'ok': bool(ok), 'note': note}
        except Exception:  # noqa: BLE001
            pass

    def _seated_this_game(self, info):
        seat = self.pre_seat or {}
        key = (info or {}).get('game_key')
        return bool(seat and key and seat.get('game_key') == key)

    def validate(self, payload, info, occupied=None, exclude_id=None):
        """Refuse commands that are known to be invalid (and have crashed clients).

        2026-10-19 22:17: one build with actor=0/city=0/xy=(0,0) produced an AV at
        0x44C156 in all three clients at the round settlement. The panel must
        never send that shape again.
        2026-10-20: 同一格不重複建設——遊戲建物件前不查佔用，重複下就會疊出
        第二個陷阱（畫面疊兩三條血條）。
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
        # 2026-10-20 23:5x：主機只收「開局那一刻就在該席位」的客戶端指令。
        # 這一局沒有先用「開局前上身」，或風夜現在不在目標勢力上，就不要送
        # （送了也會被主機靜默丟掉，只會留下假成功）。
        if payload.get('prefix') == 'prefix-fengye-shadow':
            local = info.get('local') or {}
            if not self._seated_this_game(info) and local.get('force_id') != actor:
                return ('這一局沒有在開局前上身（或風夜現在不在這家勢力上）；'
                        '請先按「開局前上身（風夜席位）」再下單，否則主機會丟棄')
        if preset == 'build':
            if payload.get('build_type') not in BUILD_TYPES:
                return '只支援兵營、馬房、弓房和陷阱'
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
            busy = self.busy_build_cells(exclude_id).get((x, y))
            if busy:
                return '(%s,%s) %s，不重複疊加' % (x, y, busy)
            if occupied is None:
                prefix = payload.get('prefix')
                occupied = self.occupied_cells(prefix) if prefix else {}
            kind = occupied.get((x, y))
            if kind:
                return '(%s,%s) 已經有%s，不再疊加' % (
                    x, y, OCCUPIED_TEXT.get(kind, '物件'))
        if preset == 'personnel':
            if int(payload.get('target_id') or -1) < 0:
                return '人事命令需要武將 id'
        return None

    def _load_history(self):
        """Load a display/audit ledger only: never recreate executable queue items."""
        if not self.history_path or not self.history_path.exists():
            return
        try:
            rows = json.loads(self.history_path.read_text(encoding='utf-8'))
            if not isinstance(rows, list):
                raise ValueError('history must be a list')
        except (OSError, ValueError, TypeError):
            self.history_error = '記錄檔格式無法確認；原檔保留，不會重播'
            return
        bad = False
        for original in rows:
            if not isinstance(original, dict):
                bad = True
                continue
            job = dict(original)
            created = job.get('created')
            if (not isinstance(job.get('id'), str) or not job['id'] or
                    job.get('prefix') not in dict(TARGETS) or job.get('preset') not in PRESETS or
                    isinstance(created, bool) or not isinstance(created, (int, float)) or
                    not math.isfinite(created) or not isinstance(job.get('params'), dict) or
                    not isinstance(job.get('status'), str)):
                bad = True
                continue
            job['events'] = [dict(e) for e in job.get('events', [])
                             if isinstance(e, dict) and isinstance(e.get('note'), str)][-40:] if isinstance(job.get('events', []), list) else []
            if not isinstance(job.get('receipt'), dict):
                job['receipt'] = None
            if not isinstance(job.get('effect'), dict):
                job.pop('effect', None)
            for field in ('finished', 'receipt_at'):
                value = job.get(field)
                if value is not None and (isinstance(value, bool) or
                                          not isinstance(value, (int, float)) or
                                          not math.isfinite(value)):
                    job.pop(field, None)
            status = job['status']
            if job.get('slot_pending_restore'):
                job['status'] = 'unknown'
                job['note'] = '重啟前借席尚未確認還原；不重送，後續代送暫停'
            elif status in CANCELLABLE:
                job['status'] = 'cancelled'
                job['finished'] = time.time()
                job['note'] = '面板已重新啟動；此筆未發送，不會自動重播'
            elif status in ('fired', 'verifying') and job.get('receipt'):
                job['status'] = 'verifying'
                job['note'] = '本機曾回報發送；重啟後遊戲效果尚未確認，不會重送'
            elif status in BUSY_STATUS:
                job['status'] = 'unknown'
                job['note'] = '重啟前已有執行；結果未確認，不重送，後續代送暫停'
            elif status == 'completed' and not (job.get('effect') or {}).get('confirmed'):
                job['status'] = 'verifying'
                job['note'] = '舊記錄沒有遊戲效果證據，保留為未確認'
            self.jobs.append(job)
        if bad:
            self.history_error = '部分舊記錄格式不完整，已略過；沒有重播任何指令'

    def _save_history(self):
        if not self.history_path:
            return True
        try:
            with self.lock:
                # Never truncate unknown sends, unobserved builds, or other
                # unfinished work: that would erase the persistent safety gate.
                terminal = [j for j in self.jobs if j.get('status') in TERMINAL][-200:]
                keep = {j['id'] for j in terminal}
                rows = [self._public(j) for j in self.jobs
                        if j.get('slot_pending_restore') or
                        j.get('status') not in TERMINAL or j['id'] in keep]
                self.history_path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.history_path.with_name(self.history_path.name + '.tmp')
                temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                temp.replace(self.history_path)
            return True
        except (OSError, TypeError, ValueError):
            self.history_error = '記錄檔寫入失敗，本次記錄只保留在面板中'
            return False

    def _update(self, job, status, note, error=None):
        with self.lock:
            job['status'], job['note'] = status, note
            if error is not None:
                job['error'] = error
            job.setdefault('events', []).append({'at': time.time(), 'status': status, 'note': note})
            job['events'] = job['events'][-40:]
            return self._save_history()

    def _advance(self, job, status, note):
        """Cancellation and the first side-effect boundary share one lock."""
        with self.lock:
            if job.get('status') == 'cancelled':
                return False
            saved = self._update(job, status, note)
            if not saved and status in ('switching_slot', 'arming'):
                self._update(job, 'error', '無法保存執行記錄；此筆未發送')
                return False
            return True

    def _prefix_blocker(self, prefix):
        current = self._game_identity
        for job in self.jobs:
            if job.get('prefix') != prefix or job.get('status') not in UNRESOLVED or job.get('legacy'):
                continue
            old = job.get('game_identity')
            if isinstance(current, dict) and isinstance(old, dict):
                # The once-only native agent re-reads &core in its loop. A
                # changed core/build/roster cannot prove it has stopped; only
                # a different actual process lifetime can clear this gate.
                before = old.get('identity') or {}
                after = current.get('identity') or {}
                fields = ('pid', 'creation_filetime')
                if all(type(before.get(k)) is int and type(after.get(k)) is int
                       for k in fields):
                    if any(before[k] != after[k] for k in fields):
                        continue
                elif (type(before.get('pid')) is int and type(after.get('pid')) is int and
                      before['pid'] != after['pid']):
                    continue
            elif isinstance(current, dict):
                old_pid = job.get('target_pid')
                new_pid = (current.get('identity') or {}).get('pid')
                if old_pid is not None and new_pid is not None and old_pid != new_pid:
                    continue
            return job
        return None

    @staticmethod
    def _effect_key(job):
        params = job.get('params') or {}
        if job.get('preset') == 'train':
            return job.get('game_key'), job.get('prefix'), params.get('actor'), params.get('troop')
        return None

    def _effect_blocker(self, job):
        key = self._effect_key(job)
        if key is None:
            return None
        return next((j for j in self.jobs if j['id'] != job['id'] and
                     self._effect_key(j) == key and j.get('status') in ('fired', 'verifying')),
                    None)

    def submit(self, payload, info=None, execute=True):
        """Create the canonical visible row immediately; never probe on caller."""
        if not isinstance(payload, dict):
            return {'ok': False, 'error': '指令參數不完整'}
        if payload.get('preset') not in PRESETS or payload.get('prefix') not in dict(TARGETS):
            return {'ok': False, 'error': '指令或目標不支援'}
        snapshot = info if info is not None else self._cache
        if not snapshot:
            return {'ok': False, 'error': '請先讀取目標與勢力'}
        with self.lock:
            game_key = snapshot.get('game_key')
            if not isinstance(game_key, str) or not game_key:
                return {'ok': False, 'error': '尚未核實當局身分，請等候重新讀取'}
            if self._game_identity is not None and game_key != self.current_game_key:
                return {'ok': False, 'error': '當局已變更或資料未確認，請重新選擇勢力'}
            occupied = dict((self._occupied.get(payload['prefix']) or (0, {}))[1])
            try:
                reason = self.validate(payload, snapshot, occupied=occupied)
            except (ValueError, TypeError, KeyError):
                reason = '指令參數不完整'
            if reason:
                return {'ok': False, 'error': reason}
            target = next((t for t in snapshot.get('targets', [])
                           if t.get('prefix') == payload['prefix']), {})
            blocked = self._prefix_blocker(payload['prefix'])
            status = 'pending' if execute and not blocked else 'held'
            job = {'id': uuid.uuid4().hex[:10], 'tag': uuid.uuid4().hex[:12],
                   'created': time.time(), 'prefix': payload['prefix'],
                   'game_key': game_key, 'game_token': snapshot.get('game_token'),
                   'game_identity_key': snapshot.get('game_identity_key'),
                   'game_identity': snapshot.get('game_identity'),
                   'preset': payload['preset'], 'status': status,
                   'params': {k: payload[k] for k in
                              ('actor', 'troop', 'value', 'extra', 'buy', 'build_type',
                               'x', 'y', 'city', 'subtype', 'target_id') if k in payload},
                   'actor_label': payload.get('actor_label') or str(payload.get('actor')),
                   'city_name': payload.get('city_name'), 'target_pid': target.get('pid'),
                   'auto_slot': bool(payload.get('auto_slot')),
                   'sender_label': payload.get('sender_label') or (
                       '風夜（借席送出）' if payload.get('auto_slot') else '本機客戶端'),
                   'eta_text': payload.get('eta_text') or self.eta_text(
                       snapshot.get('phase'), snapshot.get('year'), snapshot.get('season')),
                   'receipt': None, 'error': None, 'events': []}
            self.jobs.append(job)
            self.queue.append(dict(payload, id=job['id'], game_key=game_key,
                                   execute=bool(execute and not blocked)))
            self._update(job, status,
                         '前筆結果未確認；已記錄，代送暫停' if blocked else
                         ('已加入，等候依序執行' if execute else '已加入，尚未開始執行'))
            if execute and not blocked:
                self._start_worker()
            return {'ok': True, 'job': self._public(job), 'queue': [dict(q) for q in self.queue]}

    def queue_add(self, payload, info=None):
        # Compatibility only. The UI supplies its displayed snapshot.
        return self.submit(payload, info if info is not None else self.targets(), execute=False)

    def cancel(self, job_id):
        with self.lock:
            job = next((j for j in self.jobs if j['id'] == job_id), None)
            if job is None:
                return {'ok': False, 'error': '找不到這筆指令'}
            if job.get('status') not in CANCELLABLE:
                return {'ok': False, 'error': '此筆已開始代送，無法保證撤回；不會重送',
                        'job': self._public(job)}
            self.queue = [q for q in self.queue if q['id'] != job_id]
            job['finished'] = time.time()
            self._update(job, 'cancelled', '已取消；此筆未發送')
            return {'ok': True, 'job': self._public(job)}

    def queue_clear(self):
        with self.lock:
            ids = [j['id'] for j in self.jobs if j.get('status') in CANCELLABLE]
            for job_id in ids:
                self.cancel(job_id)
        return {'ok': True, 'queue': self.queue_view()['queue'], 'cancelled': len(ids)}

    def queue_view(self):
        with self.lock:
            return {'ok': True, 'queue': [dict(it) for it in self.queue],
                    'flush': dict(self.flush_state)}

    def flush_queue(self):
        with self.lock:
            if not self.queue:
                return {'ok': False, 'error': '沒有待執行的指令'}
            if any(self._prefix_blocker(q['prefix']) for q in self.queue):
                return {'ok': False, 'error': '前筆結果或還席未確認；後續代送暫停，不會重送'}
            ids = {item['id'] for item in self.queue}
            for item in self.queue:
                item['execute'] = True
            for job in self.jobs:
                if job['id'] in ids:
                    self._update(job, 'pending', '等候依序執行')
            self._start_worker()
            return {'ok': True, 'batch': len(ids)}

    def send(self, payload):
        return self.submit(payload)

    def _start_worker(self):
        if self._worker_running:
            return
        self._worker_running = True
        self._worker_generation += 1
        threading.Thread(target=self._dispatch, args=(self._worker_generation,),
                         daemon=True, name='cmd-dispatch').start()

    def _pause_prefix(self, prefix):
        with self.lock:
            if not self._prefix_blocker(prefix):
                return
            ids = {q['id'] for q in self.queue if q['prefix'] == prefix}
            for job in self.jobs:
                if job['id'] in ids and job.get('status') in CANCELLABLE:
                    self._update(job, 'held', '前筆結果未確認，後續代送已暫停')
            for item in self.queue:
                if item['prefix'] == prefix:
                    item['execute'] = False
            self.flush_state = {'running': False, 'phase': 'paused',
                                'note': '前筆結果未確認，不重送、不切換席位'}

    def _next_batch(self):
        """Take a contiguous same-seat batch without reordering other factions."""
        for item in list(self.queue):
            if not item.get('execute'):
                continue
            if self.current_game_key and item.get('game_key') != self.current_game_key:
                job = next(j for j in self.jobs if j['id'] == item['id'])
                self.cancel(job['id'])
                continue
            if self._prefix_blocker(item['prefix']):
                self._pause_prefix(item['prefix'])
                continue
            job = next(j for j in self.jobs if j['id'] == item['id'])
            if self._effect_blocker(job):
                self._update(job, 'waiting_effect', '等前一筆同兵種的實際訓練變化；此筆尚未發送，可取消')
                continue
            key = (item.get('game_key'), item['prefix'], item.get('actor'), bool(item.get('auto_slot')))
            batch = []
            start = self.queue.index(item)
            for candidate in self.queue[start:]:
                if not candidate.get('execute'):
                    continue
                if (candidate.get('game_key'), candidate['prefix'], candidate.get('actor'), bool(candidate.get('auto_slot'))) != key:
                    break
                row = next(j for j in self.jobs if j['id'] == candidate['id'])
                if not self._effect_blocker(row):
                    batch.append((candidate, row))
            ids = {j['id'] for _, j in batch}
            self.queue = [q for q in self.queue if q['id'] not in ids]
            return batch
        return []

    def _dispatch(self, generation=None):
        # Also serialize two service objects in one app process. All Wine work
        # stays off Tk; one slot owner holds this through its known receipts.
        generation = self._worker_generation if generation is None else generation
        with _DISPATCH_LOCK:
            try:
                while True:
                    with self.lock:
                        batch = self._next_batch()
                        if not batch:
                            self._worker_running = False
                            if self.flush_state.get('phase') != 'paused':
                                waiting = any(q.get('execute') for q in self.queue)
                                self.flush_state = {'running': False,
                                                    'phase': 'waiting_effect' if waiting else 'idle',
                                                    'note': '等前筆實際效果' if waiting else ''}
                            return
                        self.flush_state = {'running': True, 'phase': 'processing',
                                            'note': batch[0][1]['id']}
                    self._run_batch(batch)
            finally:
                with self.lock:
                    if self._worker_generation == generation:
                        self._worker_running = False

    def _prepare_job(self, payload, job):
        if not self._advance(job, 'validating', '核對客戶端、勢力與建設位置'):
            return None
        prefix = payload['prefix']
        pid = self.pid(prefix)
        if not pid or job.get('target_pid') and pid != job['target_pid']:
            self._advance(job, 'error', '客戶端已離線或已換局；未發送')
            return None
        info = self.targets(refresh=True)
        if not info.get('ok', True):
            self._advance(job, 'error', '無法確認本局資料；未發送')
            return None
        if not job.get('game_key') or job['game_key'] != info.get('game_key'):
            self._advance(job, 'error', '當局身分已變更；舊局指令未發送')
            return None
        # 2026-10-21：跨季未完成就自動作廢（使用者：下一季還沒下到就是有問題）。
        season = info.get('season')
        if isinstance(season, int):
            job['due_season'] = season + (0 if info.get('phase') == 1 else 1)
        occupied = self.occupied_cells(prefix, refresh=True) if payload['preset'] == 'build' else {}
        reason = self.validate(payload, info, occupied=occupied, exclude_id=job['id'])
        if reason:
            self._advance(job, 'error', '檢查未通過；未發送：' + reason)
            return None
        if payload['preset'] == 'build':
            city = next(c for c in info.get('cities', []) if c['city_id'] == payload['city'])
            sites = self.build_sites(prefix, city['xy'], payload['actor'], exclude_id=job['id'],
                                     build_type=payload['build_type'])
            if not sites.get('ok') or (payload['x'], payload['y']) not in {
                    tuple(xy) for xy in sites.get('cells') or []}:
                self._advance(job, 'error', '這個位置已不可建設或無法確認，請重新選址；未發送')
                return None
        # All parameter conversion happens before changing seats.
        args, flag, receipt = self.build_args(job)
        return {'info': info, 'args': args, 'flag': flag, 'receipt': receipt}

    def _wait_for_domestic_phase(self, jobs, prefix):
        """Wait for phase 1 without touching the borrowed seat.

        Firing in the *current* domestic phase keeps the borrowed player seat
        for only the few seconds around the send.  Holding that seat across a
        round boundary is what left the shadow client sitting in settlement
        on 2026-10-20, after which its phase-1 gate never opened again.
        """
        phase, data = self.phase(prefix)
        for job in jobs:
            job['phase_at_submit'] = phase
        shadow = self._round_state(phase, data)
        if shadow is None:
            for job in jobs:
                self._advance(job, 'error', '無法確認階段；未切席、未發送')
            return None
        stale = self._staleness_error(shadow, self.reference_state(prefix))
        if stale:
            for job in jobs:
                self._advance(job, 'error', stale)
            return None
        if phase == 1:
            return 1
        for job in jobs:
            self._advance(job, 'waiting_phase_exit',
                          '等內政階段（目前 phase=%d）；尚未切席、未發送，可撤回' % phase)
        deadline = time.monotonic() + self.phase_wait_timeout
        last_reference = time.monotonic()
        while time.monotonic() < deadline:
            if all(j.get('status') == 'cancelled' for j in jobs):
                return None
            time.sleep(self.poll_interval)
            phase, data = self.phase(prefix)
            shadow = self._round_state(phase, data)
            if shadow is None:
                for job in jobs:
                    self._advance(job, 'error', '階段讀取中斷；未切席、未發送')
                return None
            if phase == 1:
                # Re-check right before the seat change: a hidden observer
                # can report phase 1 from a season it never actually left.
                stale = self._staleness_error(shadow, self.reference_state(prefix))
                if stale:
                    for job in jobs:
                        self._advance(job, 'error', stale)
                    return None
                return 1
            if time.monotonic() - last_reference >= self.reference_check_interval:
                last_reference = time.monotonic()
                stale = self._staleness_error(shadow, self.reference_state(prefix))
                if stale:
                    for job in jobs:
                        self._advance(job, 'error', stale)
                    return None
        for job in jobs:
            self._advance(job, 'error',
                          '等候內政階段逾時（phase=%d）；未切席、未發送' % phase)
        return None

    def _effect_snapshot(self):
        data = self.battlefield(refresh=True)
        if not data.get('ok') or not isinstance(data.get('state'), dict):
            raise ValueError('無法讀取完整的風夜遊戲狀態')
        state = dict(data['state'])
        state['source_prefix'] = data.get('source_prefix', 'prefix-fengye-shadow')
        state['source_pid'] = data.get('source_pid')
        return state

    def _capture_baseline(self, job):
        from fengye_command_effects import capture_effect_baseline
        return capture_effect_baseline(job, self._effect_snapshot())

    def _run_probe_batch(self, prepared):
        """風夜 probe 版：寫 control JSON → probe D5 → 等 result → 驗效果。"""
        from probe_sender import ProbeSender, build_record
        sender = ProbeSender(self.lab, self.z, self._py)
        try:
            host_pid = self.pid('prefix-dingman-local')
            if not host_pid:
                raise ValueError('主機客戶端離線')
            own, host = sender.ids(host_pid)
        except Exception as exc:
            for _, job, _ in prepared:
                self._advance(job, 'error', 'probe 無法取得成員身分；未發送：' + str(exc))
            return
        sender.arm(own, host)
        for payload, job, _plan in prepared:
            if job.get('status') == 'cancelled':
                continue
            try:
                record = build_record(payload)
            except Exception as exc:
                self._advance(job, 'error', 'probe 指令組建失敗；未發送：' + str(exc))
                continue
            try:
                baseline = self._capture_baseline(job)
            except Exception as exc:
                self._advance(job, 'error', '送出前狀態讀取失敗；未發送：' + str(exc))
                continue
            if not baseline.get('ok'):
                self._advance(job, 'error', '送出前狀態不足以驗證效果；此筆未發送')
                continue
            if not self._advance(job, 'arming',
                                 '由風夜 probe 送出 D5（只送一次，已不能安全撤回）'):
                continue
            res = sender.send(record)
            if res.get('ok'):
                job['receipt'] = {'rc': 1, 'raw_rc': res.get('raw_rc'),
                                  'target': res.get('target'),
                                  'probe_request': res.get('request_id')}
                job['receipt_at'] = time.time()
                self._update(job, 'fired', 'probe 已回報送出；正在核對實際數值或建設物件')
                with self.lock:
                    self._verification_jobs[job['id']] = {
                        'job': job, 'baseline': baseline,
                        'deadline': time.monotonic() + self.verification_timeout}
            else:
                self._update(job, 'unknown', 'probe 未回報送出；不重送、後續暫停',
                             str(res.get('error')))
                self._pause_prefix(payload['prefix'])
                break
        self._start_verifier()

    def _run_batch(self, batch):
        """One seat-borrowed batch: prepare -> (wait phase) -> switch seat -> arm
        -> wait receipt -> restore.

        2026-10-20 22:5x: this function had survived three partial edits and
        contained three copies of the seat block plus a reference to an undefined
        `preborrowed` -> every batch raised NameError right after the switch and
        left the ghost parked on the borrowed seat.  Rewritten as one pass; the
        observable behaviour (one switch, one arm, one restore) is unchanged.
        """
        prepared = []
        borrowed = False
        home = None
        marker = None
        prefix = batch[0][0]['prefix']
        try:
            for payload, job in batch:
                try:
                    plan = self._prepare_job(payload, job)
                    if plan is not None:
                        prepared.append((payload, job, plan))
                except Exception as exc:
                    self._advance(job, 'error', '準備檢查失敗；未切席、未發送：' + str(exc))
            prepared = [row for row in prepared if row[1].get('status') != 'cancelled']
            if not prepared:
                return
            if any((p or {}).get('sender') == 'probe' for p, _, _ in prepared):
                return self._run_probe_batch(prepared)
            first_payload, marker, plan = prepared[0]
            auto = bool(first_payload.get('auto_slot')) and prefix == 'prefix-fengye-shadow'
            if auto:
                phase = self._wait_for_domestic_phase([row[1] for row in prepared], prefix)
            else:
                phase, _ = self.phase(prefix)
                if not isinstance(phase, int) or phase not in range(6):
                    for _, job, _ in prepared:
                        self._advance(job, 'error', '無法確認階段；未發送')
                    return
            prepared = [row for row in prepared if row[1].get('status') != 'cancelled']
            if phase is None or not prepared:
                return
            # A phase wait can cross a restart/new-room boundary. Recheck the
            # real source before the first seat-changing operation.
            fresh = self.targets(refresh=True)
            retained = []
            for payload, job, plan in prepared:
                if (not fresh.get('ok', True) or not job.get('game_key') or
                        job['game_key'] != fresh.get('game_key')):
                    self._advance(job, 'error', '等待期間當局身分改變或無法確認；此筆未發送')
                    continue
                plan['info'] = fresh
                retained.append((payload, job, plan))
            prepared = retained
            if not prepared:
                return
            if auto:
                first_payload, marker, plan = prepared[0]
                slot = next((r.get('slot') for r in plan['info'].get('player_slots', [])
                             if r.get('force_id') == first_payload['actor'] and
                             isinstance(r.get('slot'), int)), None)
                # 2026-10-20 23:3x：「開局前上身」後風夜本來就坐在目標席位。
                # 這時再切席（甚至送完還席 5）會把它的玩家身份弄掉——23:02/23:11
                # 兩發就是這樣被主機丟的。已在目標席位＝直接送，不切、不還。
                local = plan['info'].get('local') or {}
                if (slot is not None and local.get('force_id') == first_payload.get('actor')
                        and local.get('slot') == slot):
                    marker['already_seated'] = slot
                    self._advance(marker, 'seated', '風夜已上身 slot %s（勢力 %s）；直接送，不切席'
                                  % (slot, first_payload.get('actor')))
                    home = None
                    auto = False
                    borrowed = False
                else:
                    home = self._ghost_home_slot(default=None)
                    if slot is None or home is None:
                        for _, job, _ in prepared:
                            self._advance(job, 'error', '無法確認借用及旁聽席位；未切席、未發送')
                        return
                    with self.lock:
                        prepared = [row for row in prepared if row[1].get('status') != 'cancelled']
                        if not prepared:
                            return
                        first_payload, marker, plan = prepared[0]
                        marker['slot_home'] = home
                        marker['slot_pending_restore'] = True
                        if not self._advance(marker, 'switching_slot', '準備由風夜代送本批指令'):
                            marker['slot_pending_restore'] = False
                            return
                    borrowed = True  # Even a failed call may already have changed it.
                ok, note = self._switch_slot(slot) if borrowed else (True, 'already seated')
                if not ok:
                    self._update(marker, 'restore_failed', '借席未確認；後續暫停，不再切席', note)
                    return
                # The switch takes ~10s. If the domestic phase ended meanwhile,
                # keep the seat and wait for the NEXT domestic phase instead of
                # aborting: 2026-10-21 00:20 的使用者那筆就是切完席剛好過回合，
                # 被舊邏輯直接判失敗。身份不會因為這一下切換而失效。
                if not borrowed:
                    phase_now = 1
                else:
                    phase_now, _ = self.phase(prefix)
                    if phase_now != 1:
                        self._advance(marker, 'waiting_phase', '切席後已離開內政；保留席位等下一輪內政')
                        deadline = time.monotonic() + self.phase_wait_timeout
                        while phase_now != 1 and time.monotonic() < deadline:
                            if all(job.get('status') in ('cancelled', 'error')
                                   for _, job, _ in prepared):
                                break
                            time.sleep(max(0.5, self.poll_interval * 4))
                            phase_now, data_now = self.phase(prefix)
                            # 2026-10-21 00:27：切席若剛好跨過回合邊界，客戶端可能
                            # 停在上一季（season 少 1）而永遠等不到內政。這種情況
                            # 直接報清楚，不要讓使用者看它掛在那裡。
                            shadow_now = self._round_state(phase_now, data_now)
                            stale_now = self._staleness_error(
                                shadow_now, self.reference_state(prefix))
                            if stale_now:
                                restored, restore_note = self._switch_slot(home)
                                for _, job, _ in prepared:
                                    if job.get('status') != 'cancelled':
                                        self._advance(job, 'error', stale_now + '；未發送、' +
                                                      ('已還席' if restored else
                                                       '還席未確認：' + str(restore_note)))
                                borrowed = not restored
                                if not restored:
                                    self._pause_prefix(prefix)
                                return
                if borrowed and phase_now != 1:
                    restored, restore_note = self._switch_slot(home)
                    reason = ('切席後一直沒等到內政階段' if isinstance(phase_now, int)
                              else '切席後無法確認內政階段')
                    for _, job, _ in prepared:
                        if job.get('status') != 'cancelled':
                            self._advance(job, 'error', reason + '；未發送、' +
                                          ('已還席' if restored else
                                           '還席未確認：' + str(restore_note)))
                    borrowed = not restored
                    if not restored:
                        self._pause_prefix(prefix)
                    return
            for payload, job, plan in prepared:
                if job.get('status') == 'cancelled':
                    continue
                if self._effect_blocker(job):
                    with self.lock:
                        self._update(job, 'waiting_effect', '等前筆同兵種的實際變化；此筆未發送，可取消')
                        self.queue.append(dict(payload, execute=True))
                    continue
                # Capture a distinct real pre-state for this command. Failure is
                # known to precede injection and cannot be called completed.
                try:
                    baseline = self._capture_baseline(job)
                except Exception as exc:
                    self._advance(job, 'error', '送出前狀態讀取失敗；未發送：' + str(exc))
                    continue
                if not baseline.get('ok'):
                    self._advance(job, 'error', '送出前狀態不足以驗證效果；此筆未發送')
                    continue
                baseline_pid = ((baseline.get('binding') or {}).get('identity') or {}).get('pid')
                if baseline_pid is not None and job.get('target_pid') not in (None, baseline_pid):
                    self._advance(job, 'error', '送出前客戶端身分已變更；此筆未發送')
                    continue
                if self._game_identity is not None and job.get('game_key') != self.current_game_key:
                    self._update(job, 'unknown' if borrowed else 'error',
                                 '借席後當局身分改變；不發送、不自動還席' if borrowed else
                                 '當局身分已改變；此筆未發送')
                    break
                if job.get('game_identity_key') and baseline.get('binding'):
                    baseline_key = self._identity_digest(self._identity_facts(baseline['binding']))
                    if baseline_key != job['game_identity_key']:
                        self._update(job, 'unknown' if borrowed else 'error',
                                     '發送前來源局面不一致；不發送、不自動還席')
                        break
                if not self._advance(job, 'arming', '正在準備此筆指令（只送一次，已不能安全撤回）'):
                    continue
                job['flag'], job['receipt_path'] = plan['flag'], plan['receipt']
                try:
                    res = self._run(prefix, plan['args'], timeout=40)
                except Exception as exc:
                    self._update(job, 'unknown', '準備結果未確認；不重送，後續暫停', str(exc))
                    break
                text = (res.stdout or '') + (res.stderr or '')
                if '"thread_id"' not in text:
                    self._update(job, 'unknown', '沒有完整準備回執；不重送，後續暫停', text[-300:])
                    break
                try:
                    Path(plan['flag'].replace(self.z, str(self.lab)).replace('\\', '/')).write_text('')
                except OSError as exc:
                    self._update(job, 'unknown', '啟動結果未確認；不重送，後續暫停', str(exc))
                    break
                self._update(job, 'waiting_phase', '已準備，等內政階段發送及本機回執')
                self._wait_receipt(job)
                if job.get('status') in UNRESOLVED:
                    break
                if job.get('receipt') and job['receipt'].get('rc'):
                    self._update(job, 'verifying', '本機已回報發送；正在核對實際數值或建設物件')
                    with self.lock:
                        self._verification_jobs[job['id']] = {
                            'job': job, 'baseline': baseline,
                            'deadline': time.monotonic() + self.verification_timeout}
            uncertain = any(j.get('status') in UNRESOLVED for _, j, _ in prepared)
            if uncertain:
                # A live agent may still be waiting for phase 1. Never return
                # its slot or send the next request until this is reconciled.
                for payload, job, _ in prepared:
                    if job.get('status') in CANCELLABLE:
                        self._update(job, 'held', '本批前筆結果未確認；此筆尚未發送')
                        if not any(q['id'] == job['id'] for q in self.queue):
                            self.queue.append(dict(payload, execute=False))
                self._pause_prefix(prefix)
                return
            if borrowed:
                prior = marker['status']
                self._update(marker, 'restoring', '本批已收到本機回執，正在返回旁聽')
                ok, note = self._switch_slot(home)
                marker['slot_restore'] = {'to': home, 'ok': ok, 'note': note}
                if not ok:
                    self._update(marker, 'restore_failed', '返回旁聽未確認；後續代送暫停', note)
                    self._pause_prefix(prefix)
                    return
                marker['slot_pending_restore'] = False
                self._update(marker, prior, '已返回旁聽；遊戲效果仍以實際觀測確認' if prior == 'verifying' else
                             '已返回旁聽；' + str(marker.get('note', '')))
                borrowed = False
            self._start_verifier()
        except Exception as exc:
            # Any unexpected exception after the seat boundary is ambiguous.
            target = marker or batch[0][1]
            self._update(target, 'restore_failed' if borrowed else 'error',
                         '借席後執行中斷；後續暫停，不重送、不自動還席' if borrowed else
                         '執行前檢查中斷；未發送', '%s: %s' % (type(exc).__name__, exc))
            if borrowed:
                self._pause_prefix(prefix)
        finally:
            if self._prefix_blocker(prefix):
                self._pause_prefix(prefix)
            # Earlier known sends in a partially failed batch can still have
            # their real effects observed. This never sends or restores a slot.
            self._start_verifier()

    def _send_now(self, payload, job):
        """Compatibility helper; real dispatch groups a same-seat batch."""
        return self._run_batch([(payload, job)])

    def _wait_receipt(self, job):
        path = Path(job['receipt_path'].replace(self.z, str(self.lab)).replace('\\', '/'))
        deadline = time.monotonic() + self.receipt_timeout
        while time.monotonic() < deadline:
            try:
                if path.exists() and path.stat().st_size >= 64:
                    data = dict(zip(RECEIPT_KEYS, struct.unpack('<16I', path.read_bytes()[:64])))
                    if data['magic2'] != RECEIPT_MAGIC2:
                        raise ValueError('回執識別不符')
                    job['receipt'] = {k: data[k] for k in RECEIPT_KEYS if k != 'core'}
                    job['receipt_at'] = time.time()
                    if data['rc']:
                        self._update(job, 'fired', '本機回報已發送；尚未驗證遊戲效果')
                    else:
                        job['finished'] = time.time()
                        self._update(job, 'send_failed', '本機回報發送失敗，沒有標記完成')
                    return
            except Exception as exc:
                self._update(job, 'unknown', '回執無法確認；不重送，後續暫停', str(exc))
                return
            time.sleep(self.poll_interval)
        # A timeout is ambiguous: the armed agent may still fire later.  Read
        # the delivery client once more and explain *why* it never fired, so
        # the queue does not look like an unexplained five-minute freeze.
        note = '回執逾時；客戶端可能仍在等待，不重送、不自動還席'
        try:
            phase, data = self.phase(job['prefix'])
            state = self._round_state(phase, data)
        except Exception:  # noqa: BLE001
            state = None
        if state is not None and state.get('phase') != 1:
            stale = self._staleness_error(state, self.reference_state(job['prefix']))
            if stale:
                note = '回執逾時；' + stale + '；不重送、不自動還席'
            else:
                note = ('回執逾時；代送客戶端停在 phase=%s、season=%s，'
                        '沒有進入內政階段；不重送、不自動還席'
                        % (state.get('phase'),
                           state.get('season') if state.get('season') is not None else '?'))
            job['stall_note'] = note
        self._update(job, 'unknown', note)

    def _start_verifier(self):
        with self.lock:
            if self._verify_running or not self._verification_jobs:
                return
            self._verify_running = True
            threading.Thread(target=self._verification_loop, daemon=True, name='cmd-effects').start()

    def _verify_effect(self, job, baseline, state):
        from fengye_command_effects import check_effect
        return check_effect(job, baseline, state)

    def _verification_loop(self):
        try:
            while True:
                with self.lock:
                    pending = list(self._verification_jobs.values())
                    if not pending:
                        return
                try:
                    state = self._effect_snapshot()
                    error = None
                except Exception as exc:
                    state, error = None, str(exc)
                for item in pending:
                    job = item['job']
                    if self._game_identity is not None and job.get('game_key') != self.current_game_key:
                        with self.lock:
                            self._verification_jobs.pop(job['id'], None)
                        continue
                    # A restore failure must retain its prefix safety gate.
                    if job.get('status') != 'verifying':
                        if job.get('status') not in ('restoring', 'fired'):
                            with self.lock:
                                self._verification_jobs.pop(job['id'], None)
                        continue
                    try:
                        effect = self._verify_effect(job, item['baseline'], state) if state else {
                            'confirmed': False, 'summary': '無法讀取遊戲效果：' + str(error)}
                    except Exception as exc:
                        effect = {'confirmed': False, 'summary': '遊戲效果尚未確認：' + str(exc)}
                    with self.lock:
                        job['effect'] = effect
                        if effect.get('confirmed') is True:
                            if job.get('preset') == 'build':
                                xy = self._job_xy(job.get('params') or {})
                                cached = dict((self._occupied.get(job['prefix']) or (0, {}))[1])
                                if xy:
                                    cached[xy] = 'trap' if job['params'].get('build_type') == 6 else 'building'
                                self._occupied[job['prefix']] = (time.time(), cached)
                            job['finished'] = time.time()
                            self._update(job, 'completed', effect.get('summary') or '已觀察到實際遊戲變化')
                            self._verification_jobs.pop(job['id'], None)
                            self._start_worker()
                        elif time.monotonic() >= item['deadline']:
                            self._update(job, 'verifying', '遊戲效果仍未確認；保留記錄，不重送')
                            job['verification_exhausted'] = True
                            self._verification_jobs.pop(job['id'], None)
                            self._save_history()
                time.sleep(max(self.poll_interval, 3.0))
        finally:
            with self.lock:
                self._verify_running = False
                # A just-finished batch may have added a sample at this boundary.
                if self._verification_jobs and all(
                        item['job'].get('status') == 'verifying'
                        for item in self._verification_jobs.values()):
                    self._start_verifier()

    def _public(self, job):
        out = {k: v for k, v in job.items()
               if k not in ('flag', 'receipt_path') and not k.startswith('_')}
        out['params'] = dict(job.get('params') or {})
        out['events'] = [dict(e) for e in job.get('events', [])]
        out['cancellable'] = job.get('status') in CANCELLABLE
        out['waited'] = round((job.get('finished') or time.time()) - job['created'], 1)
        return out

    def jobs_view(self):
        with self.lock:
            rows = [self._public(j) for j in reversed(self.jobs)]
            current = [job for job in rows if self.current_game_key and
                       job.get('game_key') == self.current_game_key and not job.get('legacy') and
                       not str(job.get('status', '')).startswith('legacy_')]
            return {'ok': True, 'jobs': rows, 'current_jobs': current,
                    'current_game_key': self.current_game_key,
                    'current_game_token': self.current_game_token if self.current_game_key else None,
                    'game_identity_limitation': self.game_identity_limitation,
                    'history_error': getattr(self, 'history_error', None)}
