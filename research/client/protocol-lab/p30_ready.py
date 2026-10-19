"""Headless snapshot preparation and one normal cmd9 receipt per session.

This does not implement a SANPK simulation, archive-load cmd8, or game sync.
Readiness means a complete serialized cmd7 snapshot was retained, after cmd3,
with any requested scenario file actually read and its native checksum matched.
"""
import hashlib
import struct

CMD9 = (b'\xff\xff'+struct.pack('<HH', 1, 17)+b'CSanInetCmdObject'
        +struct.pack('<III', 9, 1, 0)+b'\0')


def checksum(data):
    # Koeitlbm Func0503 @1784 + Func0504 @17fa; reflected polynomial 8408,
    # initial FFFF and final xor FFFF. Pure bounded read of supplied bytes.
    crc = 65535
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 65535


class Preparation:
    def __init__(self, own_id, host_id, name, load_scenario):
        self.own_id, self.host_id, self.name = own_id, host_id, name
        self.load_scenario = load_scenario
        self.snapshot = None
        self.initial = False
        self.blocked = False
        self.sent = False
        self.closed = False
        self.scenario = None

    def accept(self, packet):
        """Return a logged decision; sending is the caller's explicit action."""
        obj = packet.get('object', {})
        cmd = obj.get('cmd')
        if packet.get('sender') != self.host_id or self.closed:
            return {'ev': 'prep_ignored', 'cmd': cmd, 'reason': 'foreign_sender_or_closed'}
        if 'parse_unknown' in obj:
            return {'ev': 'prep_ignored', 'cmd': cmd, 'reason': 'unknown_object'}
        if cmd in (3, 7):
            snap = packet.get('snapshot')
            own = [r for r in (snap or {}).get('rows', [])
                   if r.get('id') == self.own_id and r.get('name_e', {}).get('gbk_display') == self.name]
            if not snap or snap.get('consumed') != packet['length'] or len(own) != 1:
                self.blocked = True
                return {'ev': 'prep_blocked', 'cmd': cmd, 'reason': 'incomplete_snapshot_or_identity'}
            self.snapshot = packet  # retain exact raw bytes + state, not just a success flag
            if cmd == 3:
                self.initial = True
                return {'ev': 'snapshot_stored', 'cmd': cmd, 'sha256': packet['sha256']}
            if not self.initial or self.blocked or self.sent:
                return {'ev': 'prep_blocked', 'cmd': cmd, 'reason': 'initial_missing_blocked_or_already_sent'}
            self.sent = True  # reserve once BEFORE any native enqueue; never blind retry
            return {'ev': 'ready_once', 'cmd': 7, 'sha256': packet['sha256'],
                    'scope': 'headless_snapshot_receiver; no_simulation_or_sync'}
        if cmd == 6:
            if not self.initial or obj.get('class_name') != 'CSanInetCmdObject' or obj.get('derived_tail_length') != 0:
                self.blocked = True
                return {'ev': 'prep_blocked', 'cmd': cmd, 'reason': 'invalid_scenario_request'}
            if obj['a'] == 0:
                return {'ev': 'scenario_not_requested', 'cmd': cmd}
            try:
                blob, source = self.load_scenario(obj['a'])
                actual = checksum(blob)
                self.scenario = blob
                matched = actual == obj['b']
                self.blocked = self.blocked or not matched
                return {'ev': 'scenario_checked', 'scenario': obj['a'],
                        'source': source, 'sha256': hashlib.sha256(blob).hexdigest(),
                        'length': len(blob), 'checksum': actual, 'expected': obj['b'], 'matched': matched}
            except (OSError, ValueError) as exc:
                self.blocked = True
                return {'ev': 'prep_blocked', 'cmd': cmd, 'reason': 'scenario_read_failed',
                        'detail': type(exc).__name__}
        if cmd in (8, 11):
            self.closed = True
            return {'ev': 'prep_blocked', 'cmd': cmd,
                    'reason': 'archive_load_unimplemented' if cmd == 8 else 'host_cancelled'}
        if cmd == 10:
            return {'ev': 'start_command_received', 'cmd': cmd, 'ready_sent': self.sent,
                    'scope': 'command_received; gameplay_not_verified'}
        return {'ev': 'prep_observed', 'cmd': cmd}
