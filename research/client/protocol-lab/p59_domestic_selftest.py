#!/usr/bin/env python3
"""P59 self-test — runs under Win32 py32 inside the Wine prefix.

Proves, WITHOUT touching any game process, that this environment can:
  1. import the P59 builder and the shared P51 win32 layer;
  2. read Koeinm export RVAs (`_NetMsg_IsConnected@0`, `_NetMsg_GetIPAddress@4`);
  3. statically pass the four kind-18 anchors on the on-disk SANPK.exe;
  4. assemble a valid 54-byte golden wire payload and a 0x160 blob.

usage (wine): python.exe p59_domestic_selftest.py
"""
from __future__ import annotations

import json
import sys

TOOLS = r'Z:\Users\vk\sgi-fengye-lab\shadow\tools'
GAME = r'C:\sgi\run-3.5\3I'
sys.path.insert(0, TOOLS)

import p59_domestic_cmd_build as build  # noqa: E402
import p51_shadow_inject as base  # noqa: E402


def main():
    out = {'ok': False}
    try:
        exports = base.parse_exports(GAME + r'\Koeinm.dll')
        out['koeinm_exports'] = {
            '_NetMsg_IsConnected@0': hex(exports.get('_NetMsg_IsConnected@0', 0)),
            '_NetMsg_GetIPAddress@4': hex(exports.get('_NetMsg_GetIPAddress@4', 0)),
        }
        data = open(GAME + r'\SANPK.exe', 'rb').read()
        out['sanpk_sha256'] = __import__('hashlib').sha256(data).hexdigest()
        pre = build.static_preflight(data)
        out['preflight'] = pre
        out['golden_wire'] = build.expected_wire(12, 1, 95, 0).hex()
        ptr = {name: 0x10000000 + i * 0x100 for i, (name, _) in enumerate(build.BLOB_LAYOUT[2:11])}
        blob = build.build_blob(ptr, actor=12, parameter=1, value=95, extra=0,
                                sanpk_base=pre['image_base'], flag_path=r'Z:\x\flag',
                                receipt_path=r'Z:\x\receipt')
        out['blob_size'] = len(blob)
        out['blob_magic'] = hex(int.from_bytes(blob[:4], 'little'))
        out['cfg'] = {
            'ctor': hex(int.from_bytes(blob[0x2C:0x30], 'little')),
            'send': hex(int.from_bytes(blob[0x30:0x34], 'little')),
            'send_this': hex(int.from_bytes(blob[0x34:0x38], 'little')),
            'core_global': hex(int.from_bytes(blob[0x28:0x2C], 'little')),
        }
        out['ok'] = bool(pre['ok']) and out['blob_size'] == build.BLOB_SIZE
    except Exception as exc:  # noqa: BLE001
        out['error'] = '%s: %s' % (type(exc).__name__, exc)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
