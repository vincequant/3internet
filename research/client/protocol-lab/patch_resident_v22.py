#!/usr/bin/env python3
"""Apply the v2.2 "auto phase-end" patch to shadow_resident.bin (on top of v2).

Background (static, 2026-10-18 late):
  * The player's "end phase" action is the __thiscall EndPhase(phase_obj) at
    0x49b181. It reads only [phase_obj+0x3c] (must equal G = core-0x912) and
    [phase_obj+0x8a6] (must be 0 = not ended this round), then builds
    CSanInetPhaseEndCmd (X = [core+0x6c0] my_slot, V = 0x444857(core) =
    remaining round time) and submits it via 0x446482(G, cmd), which appends to
    G's local command queue and sets [G+0x80]=1.
  * So no object scan is needed: we can hand it a FAKE this object inside our
    own code page with +0x3c=G and +0x8a6=0.
  * New-round detection: G+0x6c is the round deadline; it changes when a new
    round starts. Fire EndPhase once per changed deadline (blob+0x1b8 stores
    the last seen value).

Layout after this patch (code page, blob stays at bin+0x1000):
  0x00d1  jmp gadget            (was: push 1; call Sleep)
  0x0400  gadget:  call endp ; push [blob+0x1b0] ; call Sleep ; jmp worker_ready
  0x0420  endp:    if deadline changed -> fill fake this (0x600) -> EndPhase
  0x0600  fake this object (0x8b0 bytes, zero padded; +0x3c/+0x8a6 filled at runtime)
The bin is padded to 0xeb0 so the fake object is inside the written payload.

Idempotent: refuses if the endp signature is already present or site bytes differ.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

BUILD = Path(__file__).parent / 'resident-build'
BIN = BUILD / 'shadow_resident.bin'
MANIFEST = BUILD / 'shadow_resident.json'

SITE = 0xD1
SITE_ORIG = bytes.fromhex('6a01ff5338')
GADGET = 0x400
ENDP = 0x420
FAKE = 0x600
WORKER_READY = 0x006D


def pad(x, n, fill=0x90):
    if len(x) < n:
        x.extend(bytes([fill]) * (n - len(x)))


def main():
    code = bytearray(BIN.read_bytes())
    meta = json.loads(MANIFEST.read_text())
    if len(code) >= ENDP + 1 and code[ENDP:ENDP + 4] == bytes.fromhex('8b4308'):
        print('already patched (endp present); nothing to do')
        return 0
    site = code[SITE:SITE + 5]
    if site == SITE_ORIG:
        code[SITE:SITE + 5] = b'\xe9' + struct.pack('<i', GADGET - (SITE + 5))
    elif site[0] != 0xE9:
        print('unexpected bytes at site 0x%x: %s' % (SITE, site.hex()))
        return 1
    # (site already jumping to the gadget from v2.1 is fine; the gadget is rebuilt below)
    if len(code) > 0x1000:
        print('code too large for the code page')
        return 1

    # ---- site: jmp gadget
    code[SITE:SITE + 5] = b'\xe9' + struct.pack('<i', GADGET - (SITE + 5))

    # ---- gadget @0x400: call endp; Sleep(dwell); jmp worker_ready
    g = bytearray()
    g += b'\xe8' + struct.pack('<i', ENDP - (GADGET + 5))          # call endp
    g += bytes.fromhex('ffb3b0010000')                              # push [ebx+0x1b0]
    g += bytes.fromhex('ff5338')                                    # call [ebx+0x38] (Sleep)
    g += b'\xe9' + struct.pack('<i', WORKER_READY - (GADGET + len(g) + 5))
    pad(code, GADGET)
    code[GADGET:GADGET + len(g)] = g

    # ---- endp stub @0x420
    #   eax = core - 0x912 (G)
    #   ecx = [G+0x6c] (round deadline); if unchanged -> ret
    #   [blob+0x1b8] = ecx
    #   fake = ebx - 0xa00 (code base + 0x600); [fake+0x3c]=G; [fake+0x8a6]=0
    #   EndPhase(ecx=fake)   -- indirect through blob+0x1c0 (position-independent)
    e = bytearray()
    e += bytes.fromhex('8b4308')                                    # mov eax,[ebx+8]
    e += bytes.fromhex('2d12090000')                                # sub eax,0x912
    e += bytes.fromhex('8b486c')                                    # mov ecx,[eax+0x6c]
    e += bytes.fromhex('3b8bb8010000')                              # cmp ecx,[ebx+0x1b8]
    je_op = len(e)
    e += b'\x74\x00'                                                # je skip (rel patched below)
    e += bytes.fromhex('898bb8010000')                              # mov [ebx+0x1b8],ecx
    e += bytes.fromhex('8d8b00f6ffff')                              # lea ecx,[ebx-0xa00]
    e += bytes.fromhex('89413c')                                    # mov [ecx+0x3c],eax
    e += bytes.fromhex('c781a608000000000000')                      # mov dword [ecx+0x8a6],0
    e += bytes.fromhex('ff93c0010000')                              # call [ebx+0x1c0] (EndPhase)
    e += b'\xc3'                                                    # ret
    skip_target = len(e)
    e[je_op + 1] = skip_target - (je_op + 2)                        # je rel8 -> skip
    pad(code, ENDP)
    code[ENDP:ENDP + len(e)] = e

    # ---- fake this object area (zeroed) and pad the payload to cover it
    if len(code) < FAKE + 0x8b0:
        code.extend(b'\x00' * (FAKE + 0x8b0 - len(code)))
    BIN.write_bytes(bytes(code))
    digest = hashlib.sha256(bytes(code)).hexdigest()
    meta['sha256'] = digest
    meta['variant'] = 'v2.2-endphase'
    meta['endphase'] = {
        'sender': '0x49b181', 'submit': '0x446482', 'fake_this': 'bin+0x600',
        'round_signal': 'G+0x6c (round deadline), scratch blob+0x1b8',
        'note': 'caller-independent: only [this+0x3c]==G and [this+0x8a6]==0 are read'}
    MANIFEST.write_text(json.dumps(meta, indent=2) + '\n')
    print('patched v2.2: size=%d sha256=%s' % (len(code), digest[:16]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
