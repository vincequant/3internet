"""風夜指令流解碼（Hub 側）：control5 批次記錄 → 已解碼指令列。

解碼知識遷自玩家 Hub 的 bridge/native_command_evidence.py（單一解碼來源）；
bridge 路徑可用 SGI_HUB_BRIDGE 覆寫，預設為本 repo 相鄰目錄。
解碼器或資料表不可用時輸出「未解碼」而非猜測；kind 17/21 等未編目類別
保留 kind 與長度（原文由上游 payload 另行保留）。
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

TROOP_CN = {0: '步兵', 1: '骑兵', 2: '弓兵'}
BRIDGE = None
NCE = None
CARDS = {}
CITY_NAMES = {}
DECODER_SOURCE = None


def _bridge_dir():
    env = os.environ.get('SGI_HUB_BRIDGE')
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / 'SGI-Hub-CrossOver-M4-0.2' / 'bridge',
                      here.parents[1] / 'bridge'):
        if candidate.is_dir():
            return candidate
    return None


def _load():
    global BRIDGE, NCE, CARDS, CITY_NAMES, DECODER_SOURCE
    BRIDGE = _bridge_dir()
    try:
        data = json.loads((Path(__file__).resolve().parent / 'city_id_table.json')
                          .read_text(encoding='utf-8'))
        CITY_NAMES = {int(k): v['name'] for k, v in (data.get('cities') or {}).items()
                      if isinstance(v, dict) and isinstance(v.get('name'), str)}
    except (OSError, ValueError, AttributeError, KeyError):
        CITY_NAMES = {}
    if BRIDGE is None:
        return
    try:
        if str(BRIDGE) not in sys.path:
            sys.path.insert(0, str(BRIDGE))
        import native_command_evidence as nce
        NCE = nce
        DECODER_SOURCE = Path(nce.__file__).name
    except Exception:  # noqa: BLE001 - any import failure degrades to raw display
        NCE = None
    try:
        data = json.loads((BRIDGE / 'card_catalog.json').read_text(encoding='utf-8'))
        CARDS = {int(k): v for k, v in (data.get('names') or {}).items()
                 if str(k).isdigit() and isinstance(v, str)}
    except (OSError, ValueError, AttributeError):
        CARDS = {}


_load()


def decoder_available():
    return NCE is not None


def card_name(card_id):
    return CARDS.get(card_id)


def _detail(decoded):
    cls = decoded.get('native_class')
    if cls == 'CSanInetUnitNetCmdCreate':
        generals = [g for g in (decoded.get('general_ids_raw') or [])
                    if isinstance(g, int) and 0 <= g < 0xffff]
        return '兵种%s · 武将%s · 兵%s/米%s · placement%s' % (
            TROOP_CN.get(decoded.get('troop_kind_raw'), decoded.get('troop_kind_raw')),
            generals or '—', decoded.get('soldiers_raw'), decoded.get('rice_raw'),
            decoded.get('placement_raw'))
    if cls == 'CSanInetDomesticCmd':
        target = decoded.get('target_xy_raw')
        if isinstance(target, list) and len(target) >= 2:
            city = CITY_NAMES.get(decoded.get('value_raw'))
            name = city or ('城池#%s' % decoded.get('value_raw'))
            return '%s @(%d,%d)' % (name, target[0], target[1])
        return 'param=%s value=%s extra=%s' % (
            decoded.get('parameter_raw'), decoded.get('value_raw'), decoded.get('extra_raw'))
    if cls == 'CSanInetPersonnelCmd':
        return 'target=%s' % decoded.get('target_raw')
    if cls == 'CSanInetDiplomacyCmd':
        cards = [card_name(c) or ('卡#%s' % c) for c in (decoded.get('cards_raw') or []) if c]
        return 'cards=%s' % ','.join(cards) if cards else ''
    return ''


def decode_record(sender, raw_hex):
    """Decode one control5 record; never guesses, unknown stays explicit."""
    out = {'sender': sender}
    text = str(raw_hex or '')[:240]
    if not text:
        out.update(decoded=False, reason='no_raw')
        return out
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        out.update(decoded=False, reason='bad_hex')
        return out
    out['raw_len'] = len(raw)
    out['raw_sha8'] = hashlib.sha256(raw).hexdigest()[:12]
    if NCE is None:
        out.update(decoded=False, reason='decoder_unavailable')
        return out
    try:
        decoded = NCE.decode(raw)
    except ValueError as exc:
        kind = None
        if len(raw) >= 10:
            clen = struct.unpack_from('<H', raw, 4)[0]
            if 0 < clen < 64 and len(raw) >= 6 + clen + 4:
                kind = struct.unpack_from('<i', raw, 6 + clen)[0]
        out.update(decoded=False, reason=str(exc), kind=kind)
        return out
    out.update(decoded=True, kind=decoded.get('native_type'),
               subtype=decoded.get('subtype'), action=decoded.get('action'),
               actor=decoded.get('actor_force_id'), detail=_detail(decoded))
    return out
