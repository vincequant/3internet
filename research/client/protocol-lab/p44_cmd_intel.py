#!/usr/bin/env python3
"""p44_cmd_intel.py — 風夜（幽靈）指令流解碼器 v0.2（離線）。

v0.2（2026-10-16，按 HUB-TO-FENGYE 遷移盤點 P0 補強）：
  - 落盤底層完整解碼欄位（decoded_fields），含外交 flags/other/other2/cards
    與 sender_raw/base_value_semantics，不再白名單丟欄。
  - 證據限制欄位顯式保留：command_committed=null、server_result_verified=false、
    action_training_eligible=false（無獨立依據前不得更改）。
  - 來源連結：source_file/source_line、外層控制幀 sha256、control_seq、
    記錄索引、raw record sha256/full hex；未知類別保留完整原文。
  - 時間分欄：wall_clock（牆鐘）；game_date=null（無可信來源前不標）。

來源：風夜探針日誌中 control5 廣播挾帶的指令記錄（native_slot_observed），
或由該日誌抽取出的指令傾印（JSON list, {wall,seq,sender,raw}）。
解碼：直接遷用玩家 Hub 解碼知識（bridge/native_command_evidence.py），
Hub bridge 路徑可用 SGI_HUB_BRIDGE 環境變數覆寫（預設為本 repo 內）。
範圍：內政(18)/人事(20)/出征(16)/外交(19) 全欄位；建造附座標與城池 id；
階段結束(21)/部隊移動(17) Hub 未編目，保留結構欄位（語義未標定）。
邊界：純離線，只讀風夜日誌，不觸碰任何遊戲進程內存；未知不猜測、不補造。

用法：
  python3 p44_cmd_intel.py --run /path/to/run-192945
  python3 p44_cmd_intel.py --run dump.json --jsonl out.jsonl
  python3 p44_cmd_intel.py --selftest
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import time
from collections import Counter
from pathlib import Path

DEFAULT_BRIDGE = (Path(__file__).resolve().parents[1]
                  / 'SGI-Hub-CrossOver-M4-0.2' / 'bridge')
BRIDGE = Path(os.environ.get('SGI_HUB_BRIDGE', str(DEFAULT_BRIDGE)))
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))
import native_command_evidence as nce  # noqa: E402  遷用 Hub 解碼器

TROOP_CN = {0: '步兵', 1: '骑兵', 2: '弓兵'}
SENDER_CN = {}
CARD_CN = {}
CITY_CN = {}
try:
    _catalog = json.loads((Path(nce.__file__).resolve().parent / 'card_catalog.json')
                          .read_text(encoding='utf-8'))
    CARD_CN = {int(k): v for k, v in (_catalog.get('names') or {}).items()
               if str(k).isdigit() and isinstance(v, str)}
except (OSError, ValueError, AttributeError):
    CARD_CN = {}
try:
    _cities = json.loads((Path(__file__).resolve().parent / 'city_id_table.json')
                         .read_text(encoding='utf-8'))
    CITY_CN = {int(k): v['name'] for k, v in (_cities.get('cities') or {}).items()
               if isinstance(v, dict) and isinstance(v.get('name'), str)}
except (OSError, ValueError, AttributeError, KeyError):
    CITY_CN = {}


def extract(path):
    """回傳 (records, names)。

    record: {wall, control_seq, sender, rec_index, outer_sha256, raw,
             src_file, src_line}
    """
    p = Path(path)
    log = p / 'p42_live.jsonl' if p.is_dir() else p
    records, names = [], {}
    if log.suffix == '.json':
        data = json.loads(log.read_text(encoding='utf-8'))
        for i, r in enumerate(data if isinstance(data, list) else [data]):
            records.append({'wall': r.get('wall', 0), 'control_seq': r.get('seq'),
                            'sender': r.get('sender'), 'rec_index': i,
                            'outer_sha256': None, 'raw': r.get('raw'),
                            'src_file': log.name, 'src_line': None})
        return records, names
    for lineno, line in enumerate(log.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        for r in (e.get('rows') or []):
            if isinstance(r, dict) and r.get('id') and r.get('name'):
                names[r['id']] = r['name']
        if e.get('ev') != 'native_slot_observed':
            continue
        inner = e.get('inner') or {}
        ctrl = inner.get('control') or {}
        if ctrl.get('control_cmd') != 5:
            continue
        for j, r in enumerate(ctrl.get('records') or []):
            records.append({'wall': e.get('wall', 0), 'control_seq': inner.get('seq'),
                            'sender': r.get('sender'), 'rec_index': j,
                            'outer_sha256': e.get('sha256'), 'raw': r.get('raw_hex'),
                            'src_file': log.name, 'src_line': lineno})
    return records, names


def decode(rec):
    raw = bytes.fromhex(rec['raw'])
    clen = struct.unpack_from('<H', raw, 4)[0]
    cls = raw[6:6 + clen].decode('ascii')
    wall = rec.get('wall') or 0
    row = {
        'wall': wall,
        'wall_clock': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(wall)),
        'game_date': None,  # 無可信遊戲時鐘來源前不標（見遷移盤點 8.2）
        'control_seq': rec.get('control_seq'),
        'record_index': rec.get('rec_index'),
        'sender': rec.get('sender'),          # 外層會話 sender（與 actor 分欄）
        'source_file': rec.get('src_file'),
        'source_line': rec.get('src_line'),
        'outer_frame_sha256': rec.get('outer_sha256'),
        'class': cls,
        'raw_len': len(raw),
        'raw_sha256': hashlib.sha256(raw).hexdigest(),
        'raw_hex': rec['raw'],                # 未知類別亦保留完整原文
        'command_committed': None,            # 證據限制：無獨立依據前不得更改
        'server_result_verified': False,
        'action_training_eligible': False,
    }
    try:
        d = nce.decode(raw)
    except ValueError as exc:
        body = raw[6 + clen:]
        row.update(decoded=False, kind_raw=struct.unpack_from('<i', body, 0)[0],
                   reason=str(exc))
        return row
    row.update(decoded=True, kind=d['native_type'], subtype=d['subtype'],
               action=d['action'], actor_force_id=d['actor_force_id'],
               decoded_fields=d)
    return row


def _fields(row):
    return row.get('decoded_fields') or {}


def fmt(row):
    who = SENDER_CN.get(row['sender'], str(row['sender']))
    t = time.strftime('%H:%M:%S', time.localtime(row.get('wall') or 0))
    if not row.get('decoded'):
        return '%s ｜ %s ｜ [未編目 kind=%s] %s (raw %dB 已保留)' % (
            t, who, row.get('kind_raw'), row.get('reason'), row.get('raw_len'))
    f = _fields(row)
    parts = [row['action']]
    if f.get('target_xy_raw'):
        x, y = f['target_xy_raw'][:2]
        parts.append('@(%d,%d)' % (x, y))
        city = CITY_CN.get(f.get('value_raw'))
        parts.append(city or ('城池#%s' % f.get('value_raw')))
    if 'troop_kind_raw' in f:
        parts.append(TROOP_CN.get(f['troop_kind_raw'], str(f['troop_kind_raw'])))
        parts.append('武将%s' % (f['general_ids_raw'],))
        parts.append('兵%s/米%s' % (f.get('soldiers_raw'), f.get('rice_raw')))
        parts.append('placement%s' % (f.get('placement_raw'),))
    elif 'target_raw' in f:
        parts.append('target=%s' % f['target_raw'])
    elif row['class'] == 'CSanInetDiplomacyCmd':
        cards = [CARD_CN.get(c, '卡#%s' % c) for c in (f.get('cards_raw') or []) if c]
        if cards:
            parts.append('cards=' + ','.join(cards))
    elif row['class'] == 'CSanInetDomesticCmd' and not f.get('target_xy_raw'):
        parts.append('param=%s value=%s' % (f.get('parameter_raw'), f.get('value_raw')))
    return '%s ｜ %s ｜ %s' % (t, who, ' '.join(str(x) for x in parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', help='run 目錄（含 p42_live.jsonl）、日誌或傾印 JSON')
    ap.add_argument('--jsonl', help='輸出解碼後 JSONL 到此')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        from p40_d5_inject import GOLDEN_RECORDS
        for g in GOLDEN_RECORDS:
            d = decode({'raw': g, 'wall': 0})
            assert d['decoded'] and d['action'].endswith('训练'), d
        print('selftest ok: %d/%d golden records -> 训练类' % (
            len(GOLDEN_RECORDS), len(GOLDEN_RECORDS)))
        return
    if not args.run:
        raise SystemExit('need --run or --selftest')
    src = Path(nce.__file__)
    print('# 解碼源: %s sha256=%s' % (
        src, hashlib.sha256(src.read_bytes()).hexdigest()))
    records, names = extract(args.run)
    SENDER_CN.update(names)
    out = [decode(r) for r in records]
    out.sort(key=lambda r: r['wall'])
    print('# 風夜指令流 v0.2 — %d 條（%s 至 %s）' % (
        len(out),
        time.strftime('%H:%M:%S', time.localtime(out[0]['wall'])) if out else '-',
        time.strftime('%H:%M:%S', time.localtime(out[-1]['wall'])) if out else '-'))
    for r in out:
        print(fmt(r))
    print('# 統計:', dict(Counter(
        '%s/%s' % (r['class'], r.get('action', '未編目')) for r in out)))
    if args.jsonl:
        Path(args.jsonl).write_text(
            '\n'.join(json.dumps(r, ensure_ascii=False) for r in out) + '\n',
            encoding='utf-8')
        print('# JSONL ->', args.jsonl)


if __name__ == '__main__':
    main()
