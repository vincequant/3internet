#!/usr/bin/env python3
"""Shadow session recorder -- hub-session writer for the fengye shadow client.

Read-only observer. Samples the shadow SANPK's Koeinm netobj receive slot
([netobj+0x414c] size / [+0x4150] sender / [+0x14c] data) and decodes every
distinct 0x63-frame with p33_wire.inspect_inner, writing hub-compatible rows
to <session-dir>/packets.jsonl:

  native_slot_observed   one per distinct frame (control3/control5 sync frames
                         decode to inner.control.control_cmd / records; the hub
                         uses control5.records as the command stream and
                         control3 samples for round timing).
  received_packet        one per control5 record (the actual CSanInet*Cmd
                         payloads; feeds the hub frame list).

Also maintains <session-dir>/state.json (observed_at / received /
native_sync_state / native_tx_seq / ...) and touches <session-dir>/heartbeat so
the hub keeps seeing the session as live. Phase plan target: shadow data source
for the fengye omni hub ("風夜數據源").

Discipline: never releases or consumes the game's packets; sampling is
opportunistic (possible missed frames -- noted in evidence_type). Only reads
memory of the shadow client in the caller's bottle.

Usage (wine py32, shadow prefix):
  python.exe shadow_session_rec.py \
      --session-dir 'Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\fengye-hub-session\\run-X-shadow' \
      --interval 0.1 [--duration 0] [--meta 'Z:\\...\\meta.json']
"""
from __future__ import annotations

import argparse
import ctypes as c
import hashlib
import json
import struct
import sys
import time
from ctypes import wintypes as w
from pathlib import Path


def _win():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    return k


def find_sanpk(k):
    class E(c.Structure):
        _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
                    ('th32DefaultHeapID', c.c_size_t), ('th32ModuleID', w.DWORD),
                    ('cntThreads', w.DWORD), ('th32ParentProcessID', w.DWORD),
                    ('pcPriClassBase', w.LONG), ('dwFlags', w.DWORD), ('szExeFile', w.WCHAR * 260)]
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    if snap == c.c_void_p(-1).value or not snap:
        return None
    e = E()
    e.dwSize = c.sizeof(e)
    pid = None
    try:
        ok = k.Process32FirstW(snap, c.byref(e))
        while ok:
            if e.szExeFile.lower() == 'sanpk.exe':
                pid = int(e.th32ProcessID)
            ok = k.Process32NextW(snap, c.byref(e))
    finally:
        k.CloseHandle(snap)
    return pid


def module_base(k, pid, name_lower):
    ps = c.WinDLL('psapi', use_last_error=True)
    ps.EnumProcessModules.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    ps.GetModuleBaseNameW.argtypes = [w.HANDLE, c.c_void_p, w.LPWSTR, w.DWORD]
    h = k.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h:
        return None
    try:
        arr = (c.c_void_p * 1024)()
        need = w.DWORD(0)
        if not ps.EnumProcessModules(h, arr, c.sizeof(arr), c.byref(need)):
            return None
        buf = c.create_unicode_buffer(260)
        for m in arr[:need.value // c.sizeof(c.c_void_p)]:
            if ps.GetModuleBaseNameW(h, m, buf, 260) and buf.value.lower() == name_lower:
                return int(m)
    finally:
        k.CloseHandle(h)
    return None


def scan_inner_object(raw):
    """Minimal extraction of an embedded game packet (ffff 01 s.... name ...).

    Layout: b'ffff' + schema(1B) + 0x00 + name_len(u16 LE) + name(ascii) +
            first u32 field (the CSanInet* class/kind id where present).
    """
    idx = raw.find(b'\xff\xff\x01')
    if idx < 0:
        return None
    inner = raw[idx:]
    try:
        nlen = struct.unpack_from('<H', inner, 4)[0]
        if not 0 < nlen < 64 or len(inner) < 6 + nlen:
            return None
        name = inner[6:6 + nlen].decode('ascii')
    except (struct.error, UnicodeDecodeError):
        return None
    obj = {'sha256': hashlib.sha256(inner).hexdigest(), 'length': len(inner), 'class_name': name}
    try:
        first = struct.unpack_from('<I', inner, 6 + nlen)[0]
        if 0 < first < 0x10000:
            obj['cmd'] = first
    except struct.error:
        pass
    return obj


def _control7_object(raw):
    """inner63 frame with DLL control cmd==7: one host-delivered game object.

    Layout (measured 2026-10-18, run-20261018-134329-shadow):
      63 | seq u32 | stamp 4B | size u32 | sender u32 | target u32 |
      control: cmd u32(=7) | u32 | declared u32 | object[declared]
    Samples: CSanInetInitGameData 721B (opening roster), CSanInetPlayerNotifyData 122B.
    p33_wire.decode_control does not implement cmd 7; this helper only unwraps the
    envelope inside the recorder and leaves p33_wire untouched.
    """
    if len(raw) < 33 or raw[0] != 0x63:
        return None
    size = struct.unpack_from('>I', raw, 9)[0]
    if len(raw) != 21 + size:
        return None
    control = raw[21:]
    if len(control) < 12 or struct.unpack_from('>I', control, 0)[0] != 7:
        return None
    declared = struct.unpack_from('>I', control, 8)[0]
    if not 0 < declared <= len(control) - 12:
        return None
    return control[12:12 + declared]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session-dir', required=True)
    ap.add_argument('--interval', type=float, default=0.1)
    ap.add_argument('--state-every', type=float, default=2.0)
    ap.add_argument('--heartbeat-every', type=float, default=5.0)
    ap.add_argument('--duration', type=float, default=0.0)
    ap.add_argument('--meta', default='')
    ap.add_argument('--p33-dir', default=r'Z:\Users\vkquant\sgi-protocol-lab-20260915')
    # The hub's process-chain classifier (remote_snapshot.processes) recognises
    # driver processes by script basename; --chain-alias carries a recognised
    # basename so the shadow session is reported alive. Cosmetic until the hub
    # learns this tool natively.
    ap.add_argument('--chain-alias', default='', help='argv shim for the hub chain classifier (unused)')
    ap.add_argument('--line', default='', help='hall line label (chain metadata)')
    args = ap.parse_args()

    session = Path(args.session_dir)
    session.mkdir(parents=True, exist_ok=True)
    if args.p33_dir not in sys.path:
        sys.path.insert(0, args.p33_dir)
    try:
        from p33_wire import inspect_inner
    except Exception as error:
        print(json.dumps({'error': 'inspect_inner unavailable: ' + repr(error)}, ensure_ascii=False))
        return 1
    try:
        from p28_wire import inspect_object as p28_inspect_object, decode_snapshot as p28_decode_snapshot
    except Exception:
        p28_inspect_object = None
        p28_decode_snapshot = None

    k = _win()
    pid = find_sanpk(k)
    if not pid:
        print(json.dumps({'error': 'no sanpk.exe in this bottle'}))
        return 1
    base = module_base(k, pid, 'koeinm.dll')
    if not base:
        print(json.dumps({'error': 'koeinm.dll not loaded'}))
        return 1
    netobj = base + 0x12170
    h = k.OpenProcess(0x0010, False, pid)
    if not h:
        print(json.dumps({'error': 'OpenProcess failed'}))
        return 1

    def rd(addr, n):
        buf = c.create_string_buffer(n)
        got = c.c_size_t()
        if not k.ReadProcessMemory(h, c.c_void_p(addr), buf, n, c.byref(got)) or got.value != n:
            return None
        return buf.raw

    meta = {}
    if args.meta:
        try:
            meta = json.loads(Path(args.meta).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            meta = {}
    state = dict(meta)
    state.update(phase=state.get('phase') or 'room', connected=True, application_ready=True,
                 observed_at=time.time(), received=0, released=0, receiver_errors=0,
                 mode='shadow_observer', recorder_pid=pid)
    if args.line:
        state['line'] = args.line
    out_path = session / 'packets.jsonl'
    out = out_path.open('a', encoding='utf-8', buffering=1)
    hb = session / 'heartbeat'
    hb.write_text(str(time.time()), encoding='utf-8')

    def save_state():
        try:
            tmp = session / 'state.json.tmp'
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            tmp.replace(session / 'state.json')
        except OSError:
            pass

    save_state()
    print(json.dumps({'shadow_session_rec_start': True, 'pid': pid, 'netobj': hex(netobj),
                      'session': str(session)}, ensure_ascii=False))

    t0 = time.monotonic()
    last_key = None
    last_state = 0.0
    last_hb = 0.0
    frames = 0
    reads_failed = 0
    while args.duration <= 0 or time.monotonic() - t0 < args.duration:
        try:
            hdr = rd(netobj + 0x414c, 8)
            if hdr is None:
                reads_failed += 1
                if reads_failed > 200:  # ~20s of unreadable target -> client gone
                    state.update(phase='stopped', connected=False, error='target_lost')
                    save_state()
                    break
            else:
                reads_failed = 0
                size, sender = struct.unpack('<ii', hdr)
                if 0 < size <= 0x4000:
                    raw = rd(netobj + 0x14c, size)
                    if raw and raw[0] == 0x63:
                        key = (sender, hashlib.sha256(raw).digest())
                        if key != last_key:
                            last_key = key
                            wall = time.time()
                            try:
                                parsed = inspect_inner(raw)
                            except ValueError:
                                parsed = {'unknown_control_or_incomplete_slot': True}
                            out.write(json.dumps({
                                'ev': 'native_slot_observed', 'sender_slot': sender,
                                'length': size, 'raw_hex': raw.hex(),
                                'sha256': hashlib.sha256(raw).hexdigest(),
                                'inner': parsed,
                                'evidence_type': 'sampled_shadow_receive_slot; possible_missed_frames',
                                'wall': wall}, ensure_ascii=False) + '\n')
                            frames += 1
                            control = parsed.get('control') if isinstance(parsed, dict) else None
                            if isinstance(control, dict) and control.get('control_cmd') == 5:
                                for rec in control.get('records') or []:
                                    if not isinstance(rec, dict):
                                        continue
                                    rhex = rec.get('raw_hex')
                                    if not isinstance(rhex, str) or not rhex:
                                        continue
                                    try:
                                        rbytes = bytes.fromhex(rhex)
                                    except ValueError:
                                        continue
                                    row = {'ev': 'received_packet', 'wall': wall,
                                           'sender': rec.get('sender'), 'target': 0,
                                           'length': rec.get('length') or len(rbytes),
                                           'raw_hex': rhex,
                                           'sha256': hashlib.sha256(rbytes).hexdigest(),
                                           'type': 4, 'packet_index': frames,
                                           'evidence_type': 'extracted_from_control5_broadcast'}
                                    obj = scan_inner_object(rbytes)
                                    if obj:
                                        row['object'] = obj
                                    if obj and obj.get('class_name') == 'CSanInetInitGameData' and p28_decode_snapshot is not None:
                                        idx = rbytes.find(b'\xff\xff\x01')
                                        frame = rbytes[idx:] if idx >= 0 else rbytes
                                        try:
                                            base = p28_inspect_object(frame)
                                            if 'base_end' in base:
                                                row['snapshot'] = p28_decode_snapshot(frame, base['base_end'])
                                                row['length'] = len(frame)
                                                for key in ('cmd', 'a', 'b', 'schema'):
                                                    if base.get(key) is not None:
                                                        row['object'][key] = base[key]
                                        except ValueError as exc:
                                            row['snapshot_unknown'] = str(exc)
                                    out.write(json.dumps(row, ensure_ascii=False) + '\n')
                            else:
                                # control cmd 7（主機直投單一物件，如開局名單／玩家通知）：
                                # 解封套 → 存成 hub 可讀的 received_packet 行。
                                direct = _control7_object(raw)
                                if direct is not None:
                                    obj = scan_inner_object(direct)
                                    if obj:
                                        row = {'ev': 'received_packet', 'wall': wall,
                                               'sender': 0, 'target': 0,
                                               'length': len(direct), 'raw_hex': direct.hex(),
                                               'sha256': hashlib.sha256(direct).hexdigest(),
                                               'type': 4, 'packet_index': frames,
                                               'evidence_type': 'decoded_from_control7_message'}
                                        row['object'] = obj
                                        if (obj.get('class_name') == 'CSanInetInitGameData'
                                                and p28_decode_snapshot is not None):
                                            idx = direct.find(b'\xff\xff\x01')
                                            frame = direct[idx:] if idx >= 0 else direct
                                            try:
                                                base = p28_inspect_object(frame)
                                                if 'base_end' in base:
                                                    snap = p28_decode_snapshot(frame, base['base_end'])
                                                    row['snapshot'] = snap
                                                    consumed = snap.get('consumed') if isinstance(snap, dict) else None
                                                    if isinstance(consumed, int) and 0 < consumed <= len(frame):
                                                        frame = frame[:consumed]
                                                    row['length'] = len(frame)
                                                    row['raw_hex'] = frame.hex()
                                                    row['sha256'] = hashlib.sha256(frame).hexdigest()
                                                    for key in ('cmd', 'a', 'b', 'schema'):
                                                        if base.get(key) is not None:
                                                            row['object'][key] = base[key]
                                            except ValueError as exc:
                                                row['snapshot_unknown'] = str(exc)
                                        out.write(json.dumps(row, ensure_ascii=False) + '\n')
        except (ValueError, OSError):
            state['receiver_errors'] = state.get('receiver_errors', 0) + 1
            if state['receiver_errors'] > 60:
                state.update(phase='stopped', connected=False, error='reader_errors')
                save_state()
                break
        now = time.monotonic()
        if now - last_state >= args.state_every:
            last_state = now
            state['observed_at'] = time.time()
            state['received'] = frames
            try:
                syncb = rd(netobj + 0x84a8, 4)
                txb = rd(netobj + 0x8440, 4)
                if syncb:
                    state['native_sync_state'] = struct.unpack('<I', syncb)[0]
                if txb:
                    state['native_tx_seq'] = struct.unpack('<I', txb)[0]
            except (ValueError, OSError):
                pass
            save_state()
        if now - last_hb >= args.heartbeat_every:
            last_hb = now
            try:
                hb.write_text(str(time.time()), encoding='utf-8')
            except OSError:
                pass
        time.sleep(max(0.03, args.interval))

    state.update(phase=state.get('phase') if state.get('phase') == 'stopped' else 'stopped',
                 connected=False, observed_at=time.time(), received=frames)
    save_state()
    try:
        out.close()
    except OSError:
        pass
    print(json.dumps({'shadow_session_rec_done': True, 'frames': frames,
                      'session': str(session)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
