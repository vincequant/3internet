#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P41：房間「隱形退房」訊框建構器（2026-10-16 run4 定點實證）。

已定點坐實的離開訊框（用戶按房內【取消】→ run4-142642 14:40:54.394，連發×3）：
    a4 00000000 <self> 18 00000000 00  2153 ffffffff 1e61 <self> d0c0 0400 0001338b
      |------ a4 wrapper ------|       |-------------- '!' 投遞幀 20B --------------|

模型（2026-10-16 晚修正，與 p39c2 '!' 格式對齊）：
- '!' 投遞幀 = [21][crc8][目標 BE4][交付端口 BE2][來源 BE4][tag2][plen LE2][payload]
  - crc8 = zlib.crc32(frame[2:], 0xFFFFFFFF) & 0xFF —— 五個歷史實例全部逐幀驗證通過；
    這也解釋了「每個實例第二個位元組不同」（31/ad/34/53）＝各幀內容的 CRC。
  - 目標 = ffffffff（廣播）；交付端口 = 1e61（7777）。
  - tag2 = 每次廣播變動的 2 bytes（d0c0/e914/e889/d02f/d735…；語義未定，疑似
    nonce/計數，原樣承載即可）；plen = 0400（LE 4）；payload = 0001338b（固定）。
- a4 wrapper = [a4][00000000][來源 BE4][LEN=4+len('!')][00][目標 BE4][...]
  - 本幀：LEN = 0x18（4+20）；wrapper 目標欄 = 00000000（廣播態）。
  - 校驗：P9C2 投遞 wrapper LEN=0x26=4+34（'!'34B）；23e0/23f6 wrapper LEN=0x0f=4+11。

發送路徑（離線床已驗證的 p39c2 1000 指令）：
    instr1000(addr1=self, port1=BE2(tag2), addr2=0xffffffff, port2=0x1e61,
              payload=0001338b) -> 原版 loader 組出 '!' + a4 wrapper。

本模組**只建構/解析位元組，不進行任何網絡發送**。
"""
import struct
import zlib

LEAVE_CLASS = 0x21
BROADCAST = 0xffffffff
DELIVER_PORT = 0x1E61            # 7777
WRAPPER_ZERO = bytes.fromhex('00000000')
WIRE_FLAG_LEN = 0x18             # 4 + len('!') = 4 + 20
BODY4 = bytes.fromhex('0001338b')  # 固定尾 4B（同 c4 指令 payload）

PAYLOAD_LEN = 20
WIRE_LEN = 35

# 黃金樣本（run4-142642 14:40:54.394 實證原文）
GOLDEN_SESSION_ID = 0x0ADD08E3
GOLDEN_TAG2 = 0xD0C0
GOLDEN_LEAVE_WIRE_HEX = (
    'a4000000000add08e31800000000002153ffffffff1e610add08e3d0c004000001338b'
)
# 五個已捕獲實例（同一離開事件家族；tag2 各異，其餘全同）
CAPTURED_INSTANCES = [
    ('13:53:03', 0xE914, '2153ffffffff1e610add08e3e91404000001338b'),
    ('13:53:22', 0xE889, '2131ffffffff1e610add08e3e88904000001338b'),
    ('14:00:10', 0xD02F, '21adffffffff1e610add08e3d02f04000001338b'),
    ('14:07:09', 0xD735, '2134ffffffff1e610add08e3d73504000001338b'),
    ('14:40:54', 0xD0C0, '2153ffffffff1e610add08e3d0c004000001338b'),
]


def _u32_be(value, name):
    if not isinstance(value, int) or not (0 <= value <= 0xffffffff):
        raise ValueError('%s must be a u32, got %r' % (name, value))
    return struct.pack('>I', value)


def _tag2_bytes(tag2):
    if isinstance(tag2, int):
        if not 0 <= tag2 <= 0xFFFF:
            raise ValueError('tag2 out of range: %r' % (tag2,))
        return struct.pack('>H', tag2)
    blob = bytes(tag2)
    if len(blob) != 2:
        raise ValueError('tag2 must be 2 bytes or u16')
    return blob


def build_leave_payload(session_id, tag2=GOLDEN_TAG2, body=BODY4, target=BROADCAST,
                        deliver_port=DELIVER_PORT):
    """建 20B '!' 投遞幀：21 <crc8> <目標> <端口> <self> <tag2> 0400 <body4>。

    crc8 = crc32(0x21 之後的尾段, seed=0xFFFFFFFF) & 0xFF（與 loader '!' 一致）。
    """
    if len(body) != 4:
        raise ValueError('body must be 4 bytes')
    tail = (
        _u32_be(target, 'target')
        + struct.pack('>H', deliver_port & 0xFFFF)
        + _u32_be(session_id, 'session_id')
        + _tag2_bytes(tag2)
        + struct.pack('<H', len(body))
        + body
    )
    crc = zlib.crc32(tail, 0xFFFFFFFF) & 0xFF
    return bytes([LEAVE_CLASS, crc]) + tail


def build_leave_wire(session_id, tag2=GOLDEN_TAG2, body=BODY4, target=BROADCAST,
                     deliver_port=DELIVER_PORT):
    """建 35B a4 上行封裝：a4 00000000 <self> 18 00 00000000 <'!20>。"""
    payload = build_leave_payload(session_id, tag2, body, target, deliver_port)
    return (
        b'\xa4' + WRAPPER_ZERO
        + _u32_be(session_id, 'session_id')
        + bytes([4 + len(payload)])
        + b'\x00' + WRAPPER_ZERO
        + payload
    )


def build_leave_instr1000(session_id, tag2=GOLDEN_TAG2, body=BODY4,
                          target=BROADCAST, deliver_port=DELIVER_PORT,
                          flag4=1, flag5=1):
    """建 1000 指令（供原版 loader 發出本退房幀；床測見 p41_bed_test.py）。

    欄位：LE32(1000) || flag4 || flag5 || addr1=self || port1=tag2 bytes
          || addr2=target || port2=deliver_port || LE16(len(body)) || body
    （addr1/port1 由 loader 複製進 '!' [8..11]/[12..13]，addr2/port2 進 [2..5]/[6..7]。）

    旗標實測（2026-10-16）：
    - 01 01 = 廣播模式（run5 lo0 15:11:45 實錄遊戲原話，addr2=ffffffff）；
    - 00 00 = 單人投遞（p39c2 c4/step1 既證）。
    """
    if len(body) != 4:
        raise ValueError('body must be 4 bytes')
    if flag4 not in (0, 1) or flag5 not in (0, 1):
        raise ValueError('flag_range')
    tag = _tag2_bytes(tag2)
    return (
        struct.pack('<I', 1000) + bytes([flag4, flag5])
        + _u32_be(session_id, 'session_id') + tag
        + _u32_be(target, 'target') + struct.pack('>H', deliver_port & 0xFFFF)
        + struct.pack('<H', len(body)) + body
    )


def parse_leave_wire(frame):
    """解析 35B 封裝；不合法即 ValueError。回傳 dict。

    偏移：a4[0] 00000000[1:5] self[5:9] 18[9] 00[10] 00000000[11:15]
          '!'[15:35] = 21[15] crc[16] target[17:21] port[21:23] self[23:27]
                       tag2[27:29] plen[29:31] body[31:35]
    """
    if not isinstance(frame, (bytes, bytearray)) or len(frame) != WIRE_LEN:
        raise ValueError('frame must be %d bytes' % WIRE_LEN)
    if frame[0] != 0xa4 or frame[1:5] != b'\x00\x00\x00\x00' or frame[9] != WIRE_FLAG_LEN:
        raise ValueError('bad a4 wrapper header')
    if frame[10] != 0x00 or frame[11:15] != b'\x00\x00\x00\x00':
        raise ValueError('bad wrapper target field')
    if frame[15] != LEAVE_CLASS or frame[29:31] != b'\x04\x00' or frame[31:35] != BODY4:
        raise ValueError('bad payload markers')
    self_a = struct.unpack_from('>I', frame, 5)[0]
    self_b = struct.unpack_from('>I', frame, 23)[0]
    if self_a != self_b:
        raise ValueError('session id mismatch: %08x vs %08x' % (self_a, self_b))
    if zlib.crc32(frame[17:], 0xFFFFFFFF) & 0xFF != frame[16]:
        raise ValueError('crc mismatch')
    return {
        'session_id': self_a,
        'target': struct.unpack_from('>I', frame, 17)[0],
        'deliver_port': struct.unpack_from('>H', frame, 21)[0],
        'tag2': frame[27:29].hex(),
        'body4': frame[31:35].hex(),
    }


if __name__ == '__main__':
    golden = build_leave_wire(GOLDEN_SESSION_ID, GOLDEN_TAG2)
    assert golden.hex() == GOLDEN_LEAVE_WIRE_HEX, 'golden mismatch'
    print('golden OK  :', golden.hex())
    print('ghost 樣本 :', build_leave_wire(0x0AA802D6, GOLDEN_TAG2).hex())
    print('instr1000  :', build_leave_instr1000(GOLDEN_SESSION_ID, GOLDEN_TAG2).hex())
    print('parse      :', parse_leave_wire(golden))
