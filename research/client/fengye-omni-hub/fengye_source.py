"""Fengye-only source adapter. No HTTP listener and no memory collector."""
import importlib.util
import json
import struct
import time
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fengye_backend', ROOT / 'backend/server.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)

CMD_NAMES = {0: '玩家通知', 3: '初始快照', 6: '劇本請求', 7: '開局快照',
             10: '開局指令', 11: '取消', 18: '遊戲數據', 26: '逐輪通知'}


TROOP_CN = {0: '步兵', 1: '骑兵', 2: '弓兵'}
LABELED_CLASSES = {'CSanInetUnitNetCmdMove': '部隊移動', 'CSanInetPhaseEndCmd': '階段結束'}


def _city_names():
    try:
        data = json.loads((ROOT / 'backend/city_id_table.json').read_text(encoding='utf-8'))
        return {int(k): v['name'] for k, v in (data.get('cities') or {}).items()
                if isinstance(v, dict) and isinstance(v.get('name'), str)}
    except (OSError, ValueError, AttributeError, KeyError):
        return {}


CITY_NAMES = _city_names()


def _class_name(raw):
    try:
        size = struct.unpack_from('<H', raw, 4)[0]
        if not 0 < size < 64:
            return None
        return raw[6:6 + size].decode('ascii')
    except (struct.error, UnicodeDecodeError):
        return None


def _move_fields(raw):
    """kind17 衍生欄位（2026-10-16 佈局文檔：位移對位已驗、座標為候選語義）。"""
    try:
        size = struct.unpack_from('<H', raw, 4)[0]
        body = raw[6 + size:]
        if len(body) != 35:
            return None
        return struct.unpack_from('<II', body, 15)
    except struct.error:
        return None


def _value_display(row):
    xy = row.get('target_xy_raw')
    value = row.get('value_raw')
    if isinstance(xy, (list, tuple)) and len(xy) >= 2:
        city = CITY_NAMES.get(value) if isinstance(value, int) else None
        return ('%s (%d, %d)' % (city, xy[0], xy[1])) if city else ('(%d, %d)' % (xy[0], xy[1]))
    if 'troop_kind_raw' in row:
        troop = TROOP_CN.get(row.get('troop_kind_raw'), str(row.get('troop_kind_raw')))
        return '%s 武将%s 兵%s/米%s' % (troop, row.get('general_ids_raw'),
                                        row.get('soldiers_raw'), row.get('rice_raw'))
    if 'target_raw' in row:
        return '對象#%s' % row.get('target_raw')
    if value is not None:
        return str(value)
    return None


def decoded_commands(view):
    """Use the original Hub decoder on complete, hash-checked Fengye records.

    0.2.14 顯示層補強（只加呈現欄位；原文、SHA、解碼欄位全部保留）：
    發送者↔名字/勢力、類別名標註（部隊移動/階段結束）、建造城池名＋座標、出征兵種/兵力。
    """
    from native_command_evidence import decode
    p = view.get('p34') or {}
    names = dict(p.get('member_names') or view.get('member_names') or {})
    snapshot = ((p.get('snapshots') or {}).get('start')
                or (p.get('snapshots') or {}).get('initial') or {})
    kingdoms = {}
    for seat in snapshot.get('rows') or []:
        seat_id = str(seat.get('id') or '')
        if seat_id and seat.get('name'):
            names.setdefault(seat_id, seat.get('name'))
        if seat_id and seat.get('faction'):
            kingdoms[seat_id] = seat.get('faction')
    rows = []
    for batch in (p.get('sync') or {}).get('nonempty') or []:
        for record in batch.get('records') or []:
            sender = record.get('sender')
            row = {'wall': batch.get('wall'), 'round': batch.get('round'),
                   'sender': sender, 'run_name': p.get('run_name'),
                   'source': 'fengye_received_sync', 'server_result_verified': False}
            raw = None
            try:
                raw = bytes.fromhex(record.get('raw') or '')
                sha = record.get('sha8') or ''
                if len(raw) != record.get('len'):
                    raise ValueError('封包不完整，保留未知')
                if not 8 <= len(sha) <= 64 or not hashlib.sha256(raw).hexdigest().startswith(sha):
                    raise ValueError('封包 SHA 未核對，保留未知')
                row.update(decode(raw))
            except (ValueError, TypeError, UnicodeError) as error:
                row['error'] = str(error)
            name = names.get(str(sender))
            kingdom = kingdoms.get(str(sender))
            row['sender_name'] = name
            row['kingdom'] = kingdom
            row['who_display'] = ('%s（%s）' % (name, kingdom)) if (name and kingdom) else (name or sender)
            if raw is not None and row.get('error') is not None:
                class_name = _class_name(raw)
                if class_name:
                    row['class'] = class_name
                    label = LABELED_CLASSES.get(class_name)
                    if label:
                        row['class_cn'] = label
                        if class_name == 'CSanInetUnitNetCmdMove':
                            xy = _move_fields(raw)
                            if xy:
                                row['move_xy'] = list(xy)
                                row['value_display'] = '(%d, %d)' % xy
                                row['status_text'] = '移動欄位對位已驗；座標為候選語義；結算未確認'
                            else:
                                row['status_text'] = '原文已標註；結算未確認'
                        else:
                            row['status_text'] = '原文已標註；結算未確認'
                    else:
                        row['status_text'] = '未編目類別；原文已保留'
            if row.get('error') is None and 'action' in row:
                row['value_display'] = _value_display(row)
            rows.append(row)
    return rows


def class_name(raw):
    try:
        data = bytes.fromhex(str(raw or '')[:240])
    except ValueError:
        return None
    start = data.find(b'CSanInet')
    if start < 0:
        return None
    end = start
    while end < len(data) and 32 <= data[end] < 127:
        end += 1
    return data[start:end].decode('ascii') or None


def feed_items(view):
    """Show each real item once; zero/unknown is never filled with demo data."""
    p = view.get('p34') or {}
    items = []
    for f in p.get('frames') or []:
        cmd = f.get('cmd')
        name = CMD_NAMES.get(cmd, 'cmd' + str(cmd)) if isinstance(cmd, int) else f.get('cls') or '未知'
        items.append({'wall': f.get('wall'), 'kind': 'frame', 'label': name,
                      'detail': 'type {} · {} B · {}'.format(f.get('type', '—'), f.get('len', '—'), f.get('sha8', ''))})
    for b in (p.get('sync') or {}).get('nonempty') or []:
        for r in b.get('records') or []:
            items.append({'wall': b.get('wall'), 'kind': 'data', 'label': class_name(r.get('raw')) or '遊戲數據',
                          'detail': '第 {} 輪 · sender={} · {} B · {}\n{}'.format(
                              b.get('round', '—'), r.get('sender', '—'), r.get('len', '—'),
                              r.get('sha8', ''), str(r.get('raw') or '')[:240])})
    for e in (p.get('control') or {}).get('events') or []:
        items.append({'wall': e.get('wall'), 'kind': 'control', 'label': e.get('ev') or '控制事件',
                      'detail': '{}{}{}'.format(e.get('text') or '',
                                               ' · rc=' + str(e['rc']) if e.get('rc') is not None else '',
                                               ' · ' + str(e['reason']) if e.get('reason') else '')})
    for m in (p.get('chat') or {}).get('messages') or []:
        items.append({'wall': m.get('wall'), 'kind': 'chat', 'label': m.get('text') or '—', 'detail': '風夜收到的對話'})
    return sorted(items, key=lambda x: x.get('wall') or 0, reverse=True)


def control_ready(view, now=None):
    now = time.time() if now is None else now
    transport = view.get('transport') or {}
    checked = transport.get('checked_at')
    return bool((view.get('p34') or {}).get('live_probe') and transport.get('status') == 'online'
                and isinstance(checked, (int, float)) and 0 <= now - checked <= 20)


STATUS_ICONS = {'ok': '✅', 'warn': '⚠️', 'off': '⚪', 'info': '🔹'}


def status_items(view, now=None):
    """風夜狀態清單——玩家看得懂的大白話，不出現欄位名、代碼或協議術語。

    資料來源只有本局自己的 status.json（影子端只讀採集）與會話紀錄；
    沒有資料就明說沒有，不拿舊局回填。
    """
    now = time.time() if now is None else now
    s = view.get('status') or {}
    session = view.get('session') or {}
    items = []

    def add(level, label, detail=None):
        items.append({'level': level, 'label': label, 'detail': detail})

    line = str(s.get('line') or session.get('line') or '').replace('多线', '多線')
    present = s.get('present')
    age = s.get('age')
    link = s.get('link') or {}
    fresh = isinstance(age, (int, float)) and age <= 15
    connected_ok = bool(s and present and fresh and link.get('connected'))
    scene = s.get('scene') or {}
    in_map = bool(scene.get('in_map'))
    driver_now = s.get('driver') or {}
    rounds_now = driver_now.get('rounds') or 0

    if s and present and fresh:
        if connected_ok:
            add('ok', '風夜已連上遊戲' + ('（%s）' % line if line else ''))
        else:
            add('warn', '風夜遊戲在跑，但連線不穩')
    elif s and present:
        add('warn', '風夜狀態停住了', '最後更新在 %.0f 秒前' % (age or 0))
    elif session.get('alive'):
        add('warn', '風夜程式在跑，遊戲還沒起來')
    else:
        add('off', '風夜目前不在線上', '按「讓風夜進房」開始')

    room = session.get('room_name')
    if room:
        detail = '房間位址 %s' % session.get('virtual_ip') if session.get('virtual_ip') else None
        add('ok', '已在房間：%s' % room, detail)
    elif session.get('alive'):
        add('info', '還在大廳，尚未進房')

    if session.get('ghost_registered'):
        add('ok', '已在房東的玩家名單報到')

    hide = s.get('hide') or {}
    if isinstance(hide, dict) and hide.get('verified'):
        add('ok', '已藏身（其他玩家名單看不到風夜）')
    elif session.get('ghost_withdrawn'):
        add('info', '藏身訊號已送出', '等房東名單上風夜消失，再按開始')
    elif room:
        add('warn', '還沒藏身', '開局前請按「讓風夜藏好」')

    god = s.get('godview') or {}
    if isinstance(god, dict) and god.get('installed'):
        add('ok', '上帝視角已打開', '全圖可見、沒有迷霧、部隊與城池圖示外露')

    patches = s.get('patches') if isinstance(s.get('patches'), dict) else {}
    patch_ok = bool(patches.get('ready'))
    if patches:
        opening = patches.get('opening') or {}
        guard = patches.get('guard') or {}
        suppress = patches.get('suppress') or {}
        detail = '守衛 %s/%s · 防崩 %s/%s · 抑制 %s/%s' % (
            opening.get('ok', 0), opening.get('total', 0),
            guard.get('ok', 0), guard.get('total', 0),
            suppress.get('ok', 0), suppress.get('total', 0))
        if patch_ok:
            add('ok', '補丁已裝好', detail)
        else:
            missing = []
            for label, part in (('開局守衛', opening), ('防崩', guard), ('抑制', suppress)):
                if part.get('missing'):
                    missing.append(label)
            if missing:
                detail += ' · 缺：' + '、'.join(missing)
            add('warn', '補丁還沒裝齊', detail)
    elif s and present:
        add('warn', '補丁狀態還沒讀到')

    seat = s.get('seat') or {}
    slot = seat.get('slot')
    force = seat.get('force')
    if isinstance(slot, int):
        if slot < 0 or force in (None, -1, 4294967295):
            # 空席：沒有自己的勢力，也不會替任何玩家出兵
            add('ok', '風夜沒有自己的勢力（純旁觀）')
        else:
            add('info', '目前跟著第 %d 位玩家的視角' % (slot + 1), '要看誰由「風夜・遠端勢力切換」決定')

    # 2026-10-19 用戶裁定：風夜固定無勢力、只旁聽；「回合自動跟隨」狀態不再顯示。
    rx = s.get('rx') or {}
    rx_age = rx.get('last_age')
    if isinstance(rx_age, (int, float)):
        total = rx.get('received')
        detail = '最後一筆 %.0f 秒前' % rx_age
        if isinstance(total, int):
            detail += ' · 共 %d 筆' % total
        # 本作是回合制：沒人動作時本來就會安靜一兩分鐘，別把停頓誤報成故障。
        quiet = 90
        add('ok' if rx_age <= quiet else 'warn',
            '正在收遊戲資料' if rx_age <= quiet else '遊戲資料停下來了', detail)

    world = s.get('world') or {}
    if isinstance(world, dict) and world.get('cities'):
        units = world.get('units') or 0
        line_w = '%d 座城 · %d 名武將 · %d 支部隊' % (
            world.get('cities') or 0, world.get('generals') or 0, units)
        if in_map and units == 0:
            add('warn', '還沒同步到部隊', line_w + '（部隊是逐回合增量，開局前的看不到）')
        else:
            add('ok', '已讀到本局世界', line_w)

    free = s.get('disk_free_gb')
    if isinstance(free, (int, float)) and free < 3:
        add('warn', '遠端電腦空間快滿了', '只剩 %.1f GB，可能造成掉資料' % free)

    # 開局標準線：連線 → 進房 → 報到 → 藏身 → 補丁。五項齊了才算「可以按開始」。
    # 上帝視角、回合跟隨不列入硬門檻。
    hide_now_ok = isinstance(hide, dict) and hide.get('verified')
    # 2026-10-22：D8 藏身之後應用層那一行本來就會消失，所以「進房／報到」讀不到是預期結果。
    in_room_ok = bool(session.get('room_name')) or hide_now_ok
    reported_ok = bool(session.get('ghost_registered')) or hide_now_ok
    standard = [('連線', connected_ok), ('進房', in_room_ok),
                ('報到', reported_ok), ('藏身', hide_now_ok),
                ('補丁', patch_ok)]
    done = sum(1 for _name, ok in standard if ok)
    missing = [name for name, ok in standard if not ok]
    if done == len(standard):
        if in_map:
            detail = '開局標準 %d/%d' % (done, len(standard))
            if rounds_now:
                detail += ' · 已跟到第 %d 回合' % rounds_now
            items.insert(0, {'level': 'ok', 'label': '已開局：風夜正在旁聽', 'detail': detail})
        elif hide_now_ok:
            items.insert(0, {'level': 'ok', 'label': '已藏身：房主可以直接按「開始」',
                             'detail': '開局標準 %d/%d（藏身模式下主機不會等我們、也不會分勢力）'
                                       % (done, len(standard))})
        else:
            items.insert(0, {'level': 'ok', 'label': '可以按「開始」了',
                             'detail': '開局標準 %d/%d：%s' % (done, len(standard), ' · '.join(n for n, _ in standard))})
    else:
        items.insert(0, {'level': 'warn', 'label': '還不能按「開始」',
                         'detail': '開局標準 %d/%d，還缺：%s' % (done, len(standard), '、'.join(missing))})

    return items


def mode_text(view, now=None):
    t = view.get('transport') or {}
    session = view.get('session') or {}
    if t.get('status') == 'file':
        return '回放 · 本地記錄'
    if t.get('status') == 'offline':
        return '離線 · 無法讀取採集端'
    if session:
        # 2026-10-17：只顯示當前加入的那局會話（不再回放其他 run）。
        labels = {'lobby': '大廳中', 'joining': '進房中', 'room': '已在房間',
                  'starting': '啟動中', 'disconnected': '連線斷開',
                  'stopped': '已停止', 'stale': '停止回應'}
        phase = str(session.get('phase') or 'unknown')
        label = labels.get(phase, phase)
        if session.get('fresh'):
            return '本局會話 · ' + label
        return '本局會話 · ' + ('已停止' if not session.get('alive') or phase == 'stopped' else '停止回應')
    if control_ready(view, now):
        return '在線 · 風夜探針'
    return '未就緒 · 尚無本局資料'


def validate_control(payload):
    if not isinstance(payload, dict) or payload.get('op') not in ('chat', 'stop'):
        raise ValueError('未知操作')
    if payload['op'] == 'stop':
        return {'op': 'stop'}
    text = payload.get('text')
    if not isinstance(text, str) or not text.strip() or not 0 < len(text) <= 120:
        raise ValueError('發言需為 1–120 字')
    try:
        text.encode('gbk')
    except UnicodeEncodeError:
        raise ValueError('文字含 GBK 無法表示的字元') from None
    return {'op': 'chat', 'text': text}


class FengyeSource:
    def __init__(self, data_dir=None, replay=None, sources=None):
        self.sources = sources or backend.Sources(data_dir=data_dir or ROOT / 'data', source_file=replay)
        self.view = self.sources.view()

    def refresh(self, search=False):
        self.view = self.sources.refresh(search=search)
        return self.view

    def send(self, payload):
        payload = validate_control(payload)
        if self.sources.source_file or not control_ready(self.view):
            return {'status': 'error', 'error': 'probe_not_running：回放或未就緒時不能操控'}
        # Existing backend keeps its two-second limiter and remote once-only
        # writer. No retries, including an ambiguous SSH failure.
        return self.sources.control(payload)
