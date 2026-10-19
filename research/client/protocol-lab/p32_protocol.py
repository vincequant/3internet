"""P32 offline wire and once-only action gate. No native or network calls."""
import struct
from p28_wire import inspect_object


def declaration(name):
    return b'\xff\xff'+struct.pack('<HH', 1, len(name))+name


def cmd2(machine):
    if not isinstance(machine, bytes) or not 0 < len(machine) < 255 or b'\0' in machine:
        raise ValueError('nonempty_native_computer_name_required')
    return (declaration(b'CSanInetGetInitCmdData')+struct.pack('<III', 2, 0, 2)
            +bytes([len(machine)])+machine+b'\0\0')


def cmd1(index, own_id):
    if not isinstance(index, int) or not 0 <= index < 8:
        raise ValueError('row_index_bound')
    if not isinstance(own_id, int) or not 0 < own_id <= 0xffffffff:
        raise ValueError('own_id_bound')
    blob = declaration(b'CSanInetCmdObject')+struct.pack('<III', 1, index, own_id)+b'\0'
    obj = inspect_object(blob)
    if (obj.get('cmd'), obj.get('a'), obj.get('b'), obj.get('derived_tail_length')) != (1, index, own_id, 0):
        raise ValueError('cmd1_roundtrip_failed')
    return blob


class FakeExit:
    """Only a validated cmd7 + actual cmd9 call + host cmd10 can arm cmd1.

    A separate user-report receipt binds authorization to this member/run.
    Reservation happens before calling native code; errors are never retried.
    """
    def __init__(self, own_id, host_id, name):
        self.own_id, self.host_id, self.name = own_id, host_id, name
        self.index = self.ready_seq = self.start_mono = None
        self.reserved = self.cancelled = False

    def snapshot(self, packet):
        hits = [r for r in packet.get('snapshot', {}).get('rows', [])
                if r.get('id') == self.own_id and r.get('name_e', {}).get('gbk_display') == self.name]
        if len(hits) != 1 or hits[0].get('state42') != 0:
            raise ValueError('own_active_cmd7_row_not_unique')
        self.index = hits[0]['index']

    def observe(self, packet):
        if packet.get('sender') != self.host_id:
            return
        obj = packet.get('object', {})
        if obj.get('parse_unknown') or obj.get('derived_tail_length') != 0:
            return
        if obj.get('cmd') == 11:
            self.cancelled = True
        if obj.get('cmd') == 10 and self.ready_seq is not None:
            self.start_mono = packet['mono'] if self.start_mono is None else self.start_mono

    def reserve(self, receipt, log_path, now, tx_seq, connected):
        if self.reserved or self.cancelled or self.index is None or self.start_mono is None:
            return None
        if not connected or tx_seq <= self.ready_seq or now-self.start_mono < 2:
            return None
        if (receipt.get('own_id') != self.own_id or receipt.get('host_id') != self.host_id
                or receipt.get('collector_log') != str(log_path)
                or receipt.get('user_report') != '已点开局'
                or not isinstance(receipt.get('reported_wall'), (int, float))):
            return None
        self.reserved = True
        return cmd1(self.index, self.own_id)
