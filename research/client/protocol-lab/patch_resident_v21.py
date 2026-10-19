#!/usr/bin/env python3
"""Apply the v2.1 "post-round dwell" binary patch to shadow_resident.bin.

Why (2026-10-18 late, live round 2): the v2 driver completed 19 rounds and the
world data kept pace (both processes read year=201), but the ghost's own
rendering/tick loop stopped (tick accumulator frozen) and its screen stayed at
200 spring. Root-cause working theory: the worker re-entered D almost
continuously, starving the game's own per-frame loop. Human rounds take >=10 s
(usually near the full timer), so yielding 1.5 s between rounds costs nothing.

Mechanics (no assembler needed; code page has free space before the blob):
  site 0x00d1 (worker_wait_ui):   6a 01 ff 53 38   push 1; call [ebx+0x38]
  -> e9 <rel32>                                    jmp dwell gadget @0x400
  gadget @0x400: ff b3 b0 01 00 00   push dword ptr [ebx+0x1b0]  (dwell ms)
                 ff 53 38            call dword ptr [ebx+0x38]   (Sleep)
                 e9 <rel32>          jmp worker_ready (0x6d)
The dwell value lives in the blob at +0x1b0 (build_blob writes it), so the
duration is tunable per install without rebuilding the payload.

Idempotent: refuses to run twice (checks for the gadget signature).
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

BUILD = Path(__file__).parent / 'resident-build'
BIN = BUILD / 'shadow_resident.bin'
MANIFEST = BUILD / 'shadow_resident.json'

SITE = 0x00D1
SITE_ORIG = bytes.fromhex('6a01ff5338')
GADGET_OFF = 0x400
WORKER_READY = 0x006D


def main():
    code = bytearray(BIN.read_bytes())
    meta = json.loads(MANIFEST.read_text())
    if len(code) >= GADGET_OFF + 14 and code[GADGET_OFF:GADGET_OFF + 6] == bytes.fromhex('ffb3b0010000'):
        print('already patched (gadget present); nothing to do')
        return 0
    if code[SITE:SITE + 5] != SITE_ORIG:
        print('unexpected bytes at site 0x%x: %s' % (SITE, code[SITE:SITE + 5].hex()))
        return 1
    if len(code) > 0x1000:
        print('code too large for the code page')
        return 1
    # -- patch the site: jmp to gadget
    rel_site = GADGET_OFF - (SITE + 5)
    code[SITE:SITE + 5] = b'\xe9' + struct.pack('<i', rel_site)
    # -- append the gadget at 0x400
    if len(code) < GADGET_OFF:
        code.extend(b'\x90' * (GADGET_OFF - len(code)))
    gadget = bytearray()
    gadget += bytes.fromhex('ffb3b0010000')          # push dword [ebx+0x1b0]
    gadget += bytes.fromhex('ff5338')                # call [ebx+0x38]  (Sleep)
    rel_g = WORKER_READY - (GADGET_OFF + len(gadget) + 5)
    gadget += b'\xe9' + struct.pack('<i', rel_g)     # jmp worker_ready
    code[GADGET_OFF:GADGET_OFF + len(gadget)] = gadget
    BIN.write_bytes(bytes(code))
    digest = hashlib.sha256(bytes(code)).hexdigest()
    meta['sha256'] = digest
    meta['variant'] = 'v2.1-dwell'
    meta['dwell_field'] = 'blob+0x1b0 (ms); patch site 0x00d1 -> gadget 0x0400'
    MANIFEST.write_text(json.dumps(meta, indent=2) + '\n')
    print('patched. size=%d sha256=%s gadget@0x%x rel_g=%d rel_site=%d'
          % (len(code), digest[:16], GADGET_OFF, rel_g, rel_site))
    return 0


if __name__ == '__main__':
    sys.exit(main())
