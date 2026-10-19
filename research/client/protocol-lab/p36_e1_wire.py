#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P36 E1 — 旁路收聽：NetHook 傳輸層與成員幀的純解碼器（無 I/O）。

依據：research/ai/rea-nethook-transport-20261015.md（靜態報告）
＋ 2026-10-16 對 evidence/p36-live-201443/ c2-c9 pcaps 的實幀校準。
純函式、可單測；不讀檔、不連網、不發幀。

幀式速查（已對真幀校準）：
  0x21 '!'  : 21 crc  vip4  port2BE  src4  sport2BE  plen2LE  payload
              crc = zlib.crc32(frame[2:], 0xFFFFFFFF) & 0xFF
              交付到遊戲時尾部追加 10B：{DD CC BB AA, src4, sport2BE}
  0x22 '"'  : 22 crc  sub(0x70..0x76) id4 seq4LE len2LE tail
              0x70 資料：tail = 80 00|80 01  dst4 port2 ctr4LE plen1 apayload
                       apayload = BE4 len + msg（msg[0]=cmd；cmd 0x06 = 成員訊息）
              0x70 控制：tail[0] in 81/82/83 = 端點/保活控制（本工具記 raw）
  0x31 '1'  : 31 x  id4 d1 d2 d3 extra（用戶信息）
  0x32 '2'  : 32 x  id4 value4LE（線性時戳/狀態）
  0x23 '#'  : 23 x  id4 flag1 value4LE
  0xa1      : a1  x4 id4 1000 id4 000000 c6120001 port2BE token32 ctr4
  0xa2      : a2  x4 id4 0200 4000（上線補充）
  0xa7      : a7  x4 id4 0000（上線通知）
  0xaf      : af  x4 id4 0400 a3key4（陌生名單回報）
  0xa4      : a4  00000000 src4 len2LE  dst4 inner（經中繼兜底轉發）
  0xa3      : a3 key4 ... entries_len1 0 count2LE entries×(17B: id4 d1 d2 d3 flag)
  0xa8      : a8 key4 ... 10 00 id4 d1 d2 d3 flag（註冊回執=自身記錄）
  0xaa      : aa key4 ... 11 00 id4 d1 d2 d3 flag（更新用戶）
  0xa9      : a9 key4 ... id4（移除用戶）

ID 表示：線上 4 字節大端即 32 位成員 ID；顯示作 "10.x.y.z"。
例：0a78483a -> id 175654970 -> "10.120.72.58"（= 风云，c4 watch 實證）。
"""

import hashlib
import struct
import zlib

# ---------------------------------------------------------------- primitives

def crc_loader(data: bytes) -> int:
    """NetHook 校驗：CRC32(seed=0xFFFFFFFF) 取低字節。"""
    return zlib.crc32(data, 0xFFFFFFFF) & 0xFF


def be_id(raw4: bytes) -> int:
    return int.from_bytes(raw4, 'big')


def id_vip_string(member_id: int) -> str:
    """ID -> '10.x.y.z'（大端 4 字節逐字節十進位）。"""
    return '10.%d.%d.%d' % tuple(member_id.to_bytes(4, 'big')[1:])


def id_label(member_id, names=None) -> str:
    if member_id is None:
        return '?'
    s = id_vip_string(member_id)
    if names:
        n = names.get(str(member_id)) or names.get(member_id)
        if n:
            return '%s(%s)' % (n, s)
    return s


def gbk_runs(data: bytes, min_cjk=2):
    """找出所有合法 GBK 雙字節串（>=min_cjk 個漢字），回傳 [(offset, text)]。"""
    out = []
    i, n = 0, len(data)
    while i < n:
        if 0x81 <= data[i] <= 0xFE and i + 1 < n and \
                0x40 <= data[i + 1] <= 0xFE and data[i + 1] != 0x7F:
            j, seq = i, b''
            while j + 1 < n and 0x81 <= data[j] <= 0xFE and \
                    0x40 <= data[j + 1] <= 0xFE and data[j + 1] != 0x7F:
                seq += data[j:j + 2]
                j += 2
            try:
                s = seq.decode('gbk')
            except Exception:
                i += 1
                continue
            cjk = sum(1 for ch in s if '\u4e00' <= ch <= '\u9fff')
            if cjk >= min_cjk:
                out.append((i, s))
            i = j
        else:
            i += 1
    return out


def ascii_runs(data: bytes, minlen=2):
    """可列印 ASCII 串（>=minlen），用於計算機名/英文聊天。"""
    out, cur, start = [], b'', 0
    for i, b in enumerate(data + b'\x00'):
        if 32 <= b < 127:
            if not cur:
                start = i
            cur += bytes([b])
        else:
            if len(cur) >= minlen:
                out.append((start, cur.decode('ascii')))
            cur = b''
    return out


def u16le(b, off): return struct.unpack_from('<H', b, off)[0]


def u16be(b, off): return struct.unpack_from('>H', b, off)[0]


def u32le(b, off): return struct.unpack_from('<I', b, off)[0]


# ---------------------------------------------------------------- '!' 0x21

MARKER_TAIL = b'\xdd\xcc\xbb\xaa'  # 0xAABBCCDD 小端；loader 交付給遊戲時追加


def decode_bang(b: bytes) -> dict:
    """0x21 資料幀。回傳欄位；長度不足時 ok=False"""
    d = {
        'class': 'bang', 'ok': False,
        'crc_ok': crc_loader(b[2:]) == b[1] if len(b) >= 2 else False,
    }
    if len(b) < 16:
        d['reason'] = 'short'
        return d
    d['ok'] = True
    vip = b[2:6]
    d['vip_marker'] = vip == b'\x02\x00\x00\x00'
    d['vip_id'] = None if d['vip_marker'] else be_id(vip)
    d['deliver_port'] = u16be(b, 6)
    d['src_id'] = be_id(b[8:12])
    d['src_port'] = u16be(b, 12)
    d['plen'] = u16le(b, 14)
    payload = b[16:16 + d['plen']]
    d['payload'] = payload
    d['payload_hex'] = payload.hex()
    # 交付版（loader→game）尾部 10B 尾標：DD CC BB AA + src + sport
    if len(payload) >= 10 and payload[-10:-6] == MARKER_TAIL:
        d['delivery_marker'] = {
            'src_id': be_id(payload[-6:-2]),
            'src_port': u16be(payload, len(payload) - 2),
        }
        d['game_payload'] = payload[:-10]
        d['game_payload_hex'] = payload[:-10].hex()
    return d


# ---------------------------------------------------------------- '"' 0x22 UDT

UDT_SUBTYPE_LABEL = {
    0x70: 'udt_data', 0x71: 'udt_ack_release', 0x72: 'udt_conn_open',
    0x73: 'udt_conn_establish', 0x74: 'udt_unknown_74', 0x75: 'udt_window_update',
    0x76: 'udt_rtt_heartbeat',
}


def decode_app_message(msg: bytes) -> dict:
    """0x70 資料幀的內層應用訊息：cmd1 + 各類 body。只提取已證實欄位。"""
    d = {'raw_hex': msg.hex()}
    if not msg:
        return d
    d['cmd'] = msg[0]
    d['cmd_hex'] = '0x%02x' % msg[0]
    if len(msg) >= 5:
        cand = be_id(msg[1:5])
        if cand >> 24 == 0x0A:  # 成員 ID 都以 0x0A 開頭（虛擬 10.* 命名空間）
            d['sender_id'] = cand
    texts = [s for _, s in gbk_runs(msg)]
    asciis = [s for _, s in ascii_runs(msg) if not s.isdigit() and len(s) >= 6]
    if texts:
        d['gbk_text'] = texts
    if asciis:
        d['ascii_text'] = asciis
    # cmd 0x06（成員訊息）：已知聊天內型 tail = 46 00*11 07 id4 ffffffff <GBK/ASCII text> 00
    if msg[0] == 0x06:
        m = msg.find(b'\xff\xff\xff\xff')
        if m > 0:
            d['broadcast_marker'] = True
            body = msg[m + 4:]
            nul = body.find(b'\x00')
            if nul < 0:
                nul = len(body)
            try:
                text = body[:nul].decode('gbk')
            except Exception:
                text = ''
            if text and all(ord(ch) >= 32 and ord(ch) != 127 for ch in text):
                d['chat_text'] = text
        else:
            d['member_msg'] = True
    return d


def decode_udt(b: bytes) -> dict:
    d = {'class': 'udt', 'ok': False,
         'crc_ok': crc_loader(b[2:]) == b[1] if len(b) >= 2 else False}
    if len(b) < 3:
        d['reason'] = 'short'
        return d
    sub = b[2]
    d['subtype'] = '0x%02x' % sub
    d['subtype_label'] = UDT_SUBTYPE_LABEL.get(sub, 'udt_?')
    if len(b) < 7:
        d['ok'] = True
        d['raw_hex'] = b.hex()
        return d
    d['id'] = be_id(b[3:7])
    if len(b) < 13:
        d['ok'] = True
        d['raw_tail_hex'] = b[7:].hex()
        return d
    d['seq'] = u32le(b, 7)
    ln = u16le(b, 11)
    d['tail_len'] = ln
    tail = b[13:13 + ln]
    d['tail_hex'] = tail.hex()
    d['ok'] = True
    if sub == 0x70 and len(tail) >= 13 and tail[0] == 0x80:
        # 資料幀：80 00|80 01 dst4 port2(BE) ctr4LE plen1 payload
        d['marker'] = tail[0:2].hex()
        d['dst_id'] = be_id(tail[2:6])
        d['dst_port'] = u16be(tail, 6)
        d['ctr'] = u32le(tail, 8)
        plen = tail[12]
        apayload = tail[13:13 + plen]
        d['aplen'] = plen
        d['apayload_hex'] = apayload.hex()
        if len(apayload) >= 4:
            inner_len = int.from_bytes(apayload[:4], 'big')
            if inner_len == len(apayload) - 4:
                d['msg'] = decode_app_message(apayload[4:])
    elif sub == 0x70 and len(tail) >= 7 and tail[0] in (0x81, 0x82, 0x83):
        # 小型連線控制：81 id1 port1 id2 port2 / 82 id port / 83 00 id port
        d['ctrl_marker'] = '0x%02x' % tail[0]
        off = 2 if (tail[0] == 0x83 and len(tail) >= 6 and tail[1] == 0x00) else 1
        if len(tail) >= off + 4:
            d['ctrl_id'] = be_id(tail[off:off + 4])
        if len(tail) >= off + 6:
            d['ctrl_port'] = u16be(tail, off + 4)
        if tail[0] == 0x81 and len(tail) >= off + 12:
            d['ctrl_id2'] = be_id(tail[off + 6:off + 10])
            d['ctrl_port2'] = u16be(tail, off + 10)
    return d


def u16le_nofail(b, off):
    return u16le(b, off) if len(b) >= off + 2 else None


# ---------------------------------------------------------------- 小型控制幀

def decode_rec(t: int, b: bytes) -> dict:
    """0x31 '1' / 0x32 '2' / 0x23 '#' 小型控制幀。"""
    d = {'ok': len(b) >= 6}
    if not d['ok']:
        return d
    d['id'] = be_id(b[2:6])
    if t == 0x32:
        if len(b) >= 10:
            d['value'] = u32le(b, 6)
    elif t == 0x23:
        if len(b) >= 11:
            d['flag'] = b[6]
            d['value'] = u32le(b, 7)
    elif t == 0x31:
        if len(b) >= 18:
            d['d1'] = u32le(b, 6)
            d['d2'] = u32le(b, 10)
            d['d3'] = u32le(b, 14)
        if len(b) > 18:
            d['rest_hex'] = b[18:].hex()
    return d


def decode_delivered(b: bytes) -> dict:
    """loader→遊戲 的交付形態：<game payload> DDCCBBAA src4 sport2BE（無 16B 頭）。"""
    d = {'class': 'delivered', 'ok': False}
    if len(b) >= 10 and b[-10:-6] == MARKER_TAIL:
        d['ok'] = True
        d['game_payload'] = b[:-10]
        d['game_payload_hex'] = b[:-10].hex()
        d['src_id'] = be_id(b[-6:-2])
        d['src_port'] = u16be(b, len(b) - 2)
    return d


def decode_relay_small(b: bytes) -> dict:
    """0xa1/a2/a7/af：loader→中繼的小幀（欄位依報告+實幀校準）。"""
    d = {'ok': len(b) >= 9, 'raw_hex': b.hex()}
    if not d['ok']:
        return d
    d['id'] = be_id(b[5:9])
    if b[0] == 0xA1 and len(b) >= 27:
        d['port'] = u16be(b, 25)
        if len(b) >= 63:
            d['token_hex'] = b[27:59].hex()
            d['ctr'] = u32le(b, 59)
    if b[0] == 0xAF and len(b) >= 15:
        d['a3_key'] = u32le(b, 11)
    return d


def decode_a4(b: bytes) -> dict:
    """a4 兜底轉發：a4 00000000 src4 len2LE dst4 inner。inner 遞迴解。"""
    d = {'class': 'a4', 'ok': False}
    if len(b) < 15:
        d['reason'] = 'short'
        return d
    d['ok'] = True
    d['src_id'] = be_id(b[5:9])
    ln = u16le(b, 9)
    d['len'] = ln
    d['dst_id'] = be_id(b[11:15])
    inner = b[15:15 + ln - 4]
    d['inner_hex'] = inner.hex()
    d['inner'] = decode_frame(inner)
    return d


def decode_a3(b: bytes) -> dict:
    d = {'class': 'a3', 'ok': False}
    if len(b) < 13:
        return d
    d['ok'] = True
    d['key'] = u32le(b, 1)
    d['entries_len_byte'] = b[9]
    count = u16le(b, 11)
    d['count'] = count
    entries = []
    off = 13
    for _ in range(count):
        e = b[off:off + 17]
        if len(e) < 17:
            d['ok'] = False
            d['reason'] = 'entry_truncated'
            break
        entries.append({
            'id': be_id(e[0:4]),
            'd1': u32le(e, 4), 'd2': u32le(e, 8), 'd3': u32le(e, 12),
            'flag': e[16],
            'raw_hex': e.hex(),
        })
        off += 17
    d['entries'] = entries
    return d


def decode_record_frame(b: bytes) -> dict:
    """a8 註冊回執 / aa 更新：key4 ... len 00 id4 d1 d2 d3 flag。"""
    d = {'ok': False}
    d['key'] = u32le(b, 1) if len(b) >= 5 else None
    if len(b) >= 28:
        d['ok'] = True
        d['len_byte'] = b[9]
        d['id'] = be_id(b[11:15])
        d['d1'] = u32le(b, 15)
        d['d2'] = u32le(b, 19)
        d['d3'] = u32le(b, 23)
        d['flag'] = b[27]
        d['raw_hex'] = b.hex()
    return d


def decode_a9(b: bytes) -> dict:
    d = {'ok': len(b) >= 15}
    if d['ok']:
        d['key'] = u32le(b, 1)
        d['id'] = be_id(b[11:15])
    return d


# ---------------------------------------------------------------- dispatcher

HANDSHAKE_TYPES = {0xA1, 0xA2, 0xA7, 0xAF, 0xA8, 0xA3, 0xA9, 0xAA}


def decode_frame(b: bytes):
    """把一個 UDP payload 解成 dict；未知類回 {'class':'unknown', raw_hex}。"""
    if not b:
        return {'class': 'empty'}
    t = b[0]
    if t == 0x21:
        d = decode_bang(b); d['class'] = 'bang'; return d
    if t == 0x22:
        d = decode_udt(b); d['class'] = 'udt'; return d
    if t == 0x31:
        d = decode_rec(t, b); d['class'] = 'rec1'; return d
    if t == 0x32:
        d = decode_rec(t, b); d['class'] = 'rec2'; return d
    if t == 0x23:
        d = decode_rec(t, b); d['class'] = 'hash'; return d
    if t == 0xA4:
        return decode_a4(b)
    if t == 0xA3:
        return decode_a3(b)
    if t == 0xA8:
        d = decode_record_frame(b); d['class'] = 'a8'; return d
    if t == 0xAA:
        d = decode_record_frame(b); d['class'] = 'aa'; return d
    if t == 0xA9:
        d = decode_a9(b); d['class'] = 'a9'; return d
    if t in (0xA1, 0xA2, 0xA7, 0xAF):
        d = decode_relay_small(b)
        d['class'] = {0xA1: 'a1', 0xA2: 'a2', 0xA7: 'a7', 0xAF: 'af'}[t]
        return d
    if len(b) >= 4 and b[:4] == b'\xe8\x03\x00\x00':
        d = {'class': 'instr1000', 'ok': True, 'raw_hex': b.hex()}
        if len(b) >= 0x14:
            d['flag4'] = b[4]
            d['flag5'] = b[5]
            # 地址欄位在線上是虛擬 IP 的 4 位元組（大端），端口為大端 2 位元組
            d['addr1_id'] = be_id(b[6:10])
            d['port1'] = u16be(b, 10)
            d['addr2_id'] = be_id(b[12:16])
            d['port2'] = u16be(b, 16)
            d['plen'] = u16le(b, 18)
            d['payload_hex'] = b[20:].hex()
        return d
    if len(b) >= 4 and b[:4] == b'\xe9\x03\x00\x00':
        d = {'class': 'instr1001', 'ok': True, 'raw_hex': b.hex()}
        if len(b) >= 0x18:
            d['user_id'] = u32le(b, 0x14)
        return d
    # 交付到遊戲的本機形態（無 16B 頭、尾標結尾）
    d = decode_delivered(b)
    if d['ok']:
        return d
    return {'class': 'unknown', 'raw_hex': b.hex(), 'first_byte': '0x%02x' % t}


def frame_sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]
