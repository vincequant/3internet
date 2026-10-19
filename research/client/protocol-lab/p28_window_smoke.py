"""Synthetic, own-process heap/window smoke. NEVER calls Start/OpenSession.

Real DLL DecodeWParam + DeletePacket, synthetic labeled payloads. No game,
relay, authentication, foreign memory, UDP, TCP or protocol frames.
"""
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p28_window import Receiver, WM_DATA, WM_EVENT


def main():
    out = Path(sys.argv[1])
    assert c.sizeof(c.c_void_p) == 4
    dllpath = Path(r'C:\sgi\run-3.5\3I\Koeinm.dll')
    assert hashlib.sha256(dllpath.read_bytes()).hexdigest() == '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
    dll = c.WinDLL(str(dllpath))
    decode = getattr(dll, '_NetMsg_DecodeWParam@4')
    decode.argtypes, decode.restype = [c.c_uint32], c.c_int
    delete = getattr(dll, '_NetMsg_DeletePacket@4')
    delete.argtypes, delete.restype = [c.c_void_p], c.c_int
    events = []
    exits = []
    k = c.WinDLL('kernel32', use_last_error=True)
    k.GetProcessHeap.restype = c.c_void_p
    k.HeapAlloc.argtypes, k.HeapAlloc.restype = [c.c_void_p, c.c_uint32, c.c_size_t], c.c_void_p
    receiver = Receiver(events.append, decode, delete, lambda x: exits.append(x) or 1)
    try:
        # Base cmd3 fixture, explicitly synthetic and not a room snapshot.
        name = b'CSanInetCmdObject'
        data = b'\xff\xff'+struct.pack('<HH', 1, len(name))+name+struct.pack('<III', 3, 0, 0)+b'\0'
        raw = struct.pack('<III', 123, 456, len(data))+data
        ptr = k.HeapAlloc(k.GetProcessHeap(), 0, len(raw))
        assert ptr
        c.memmove(ptr, raw, len(raw))
        assert receiver.u.PostMessageW(receiver.hwnd, WM_DATA, 4, ptr)
        assert receiver.u.PostMessageW(receiver.hwnd, WM_EVENT, 1, 777)
        assert receiver.u.PostMessageW(receiver.hwnd, WM_EVENT, 2, 888)
        deadline = time.monotonic()+3
        while time.monotonic() < deadline and len(exits) == 0:
            receiver.pump()
            time.sleep(.01)
        packets = [e for e in events if e['ev'] == 'received_packet']
        releases = [e for e in events if e['ev'] == 'packet_release']
        assert len(packets) == 1 and packets[0]['raw_hex'] == data.hex()
        assert packets[0]['object']['cmd'] == 3
        assert receiver.errors == 0 and receiver.freed == 1 and releases[0]['rc'] != 0
        assert exits == [888]  # scalar type1 was neither freed nor dereferenced
        result = {'synthetic': True, 'no_network_start': True, 'passed': True,
                  'events': events, 'exit_ids': exits}
    finally:
        receiver.close()
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
