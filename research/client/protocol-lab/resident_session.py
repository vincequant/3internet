"""Resident hall/relay session: one grant, then search-only cycles.

Default path (leave_hall_after_grant=True):
  login → 0x200b enter once → capture grant → 0x2002 leave hall immediately →
  keep relay_config for StartServer / SearchSession. Hall 「房间用户」 is not
  held across search cycles. Search cycles never re-send 0x200b / 0x2002 / 0x2001.

Why 0x200b puts you on 「房间用户」:
  Platform TCP 25001 treats ENTER (0x200b) as joining the line room (多线2).
  Server broadcasts occupancy; UI 「房间用户」 and chat 「进来了」 follow that.
  native_login_probe and stay-in-hall residents keep or re-send that join.

Why protocol StartServer can look "in game but not on the list":
  HallSession.login_and_enter still sends 0x200b to obtain the grant/token.
  try_launch_playable_sanpk / StartServer uses the grant on the relay VPN and
  can keep SANPK after HallSession.close(logout=True) drops hall occupancy.
  See Hub main_lobby._attach_sanguo_after_protocol and evidence/hidden-player /
  alternate-observer-paths (raw_nonjoining_search = UDP SearchSession, no
  OpenSession join into SANPK slots).

Never logs passwords, tokens, or ingest secrets. OpcodeLedger lets tests prove
search cycles do not re-enter the hall.
"""
from __future__ import annotations

import random
import socket
import struct
import time
from typing import Callable, Optional

from login_protocol import (
    Frames,
    Reader,
    Transport,
    encode,
    game_directory,
    login_body,
    room_directory,
    user_record,
    wrap,
)

CMD_LOGIN = 0x2001
CMD_LOGOUT = 0x2002
CMD_ENTER = 0x200b
CMD_MEMBERS = 0x200f
CMD_AUTH_OK = 0x2011
CMD_GAME_DIR = 0x2012
CMD_ROOM_DIR = 0x2013
CMD_ENTER_ACK = 0x9000

DEFAULT_HOST = "121.41.166.208"
DEFAULT_PORT = 25001
TARGET_GAME_SUBSTR = "三国对战房"
TARGET_ROOM_SUBSTR = "多线2"

# Hall occupancy vs grant (relay) capability.
PRESENCE_ABSENT = "absent"
PRESENCE_IN_ROOM = "in_room"
PRESENCE_LEFT_AFTER_GRANT = "left_after_grant"
MECHANISM_LEAVE = "leave_hall_after_grant"
MECHANISM_STAY = "stay_in_hall"


def reconnect_delay(failures: int, base: float = 5.0, cap: float = 120.0) -> float:
    """Exponential backoff with full jitter. Never a fixed hammer interval."""
    exp = min(cap, base * (2 ** max(0, failures - 1)))
    return random.uniform(0.0, exp)


def _gbk_str(value: str) -> bytes:
    raw = value.encode("gbk")
    return struct.pack("<H", len(raw)) + raw


def _pack_auth_ok() -> bytes:
    return struct.pack("<I", 0) + _gbk_str("")


def _pack_game(game_id: int, name: str) -> bytes:
    body = struct.pack("<I", game_id) + _gbk_str(name)
    body += _gbk_str("a") + _gbk_str("b")
    body += struct.pack("BB", 0, 0)
    body += _gbk_str("c") + _gbk_str("d") + _gbk_str("e")
    return body


def _pack_room(game_id: int, room_id: int, name: str, server: str = "", port: int = 9151) -> bytes:
    body = struct.pack("<II", game_id, room_id) + _gbk_str(name)
    body += struct.pack("B", 1)
    body += struct.pack("<IIII", 0, 100, 300, 0)
    body += _gbk_str(server)
    body += struct.pack("<H", port)
    body += _gbk_str("x") + _gbk_str("y") + struct.pack("<I", 0)
    return body


def _pack_user(user_id: int = 100001, name: str = "mock-alt", vip: str = "10.0.0.1") -> bytes:
    body = struct.pack("<I", user_id) + _gbk_str(name)
    body += _gbk_str("")  # s08
    body += struct.pack("<I", 0)  # i0c
    body += _gbk_str("")  # s10
    body += struct.pack("<IIIIII", 0, 0, 0, 0, 0, 0)  # i14..i28
    body += _gbk_str(vip) + struct.pack("B", 0)
    return body


def _pack_enter_ack(room_id: int = 1001) -> bytes:
    body = struct.pack("<I", 0) + _gbk_str("") + struct.pack("<I", room_id)
    body += _pack_user()
    body += _gbk_str("mock-token")
    return body


class OpcodeLedger:
    """Records outbound protocol commands without payloads."""

    def __init__(self):
        self.sent = []

    def record(self, command: int, sequence: int):
        self.sent.append({"command": command, "sequence": sequence, "hex": hex(command)})

    def counts(self):
        out = {}
        for row in self.sent:
            out[row["command"]] = out.get(row["command"], 0) + 1
        return out

    def count(self, command: int) -> int:
        return self.counts().get(command, 0)

    def commands_after(self, index: int):
        return [row["command"] for row in self.sent[index:]]


class SocketTransport:
    """Real TCP transport used on the collector Mac only."""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=8.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self._parser = Transport()
        self._frames = Frames()

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

    def send_raw(self, data: bytes):
        self.sock.sendall(data)

    def recv_frames(self, deadline: float):
        out = []
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            self.sock.settimeout(remaining)
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                raise ConnectionError("server_closed")
            for main, sub, payload in self._parser.feed(data):
                if main == 101 and sub == 1:
                    out.extend(self._frames.feed(payload))
        return out

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


class MockTransport:
    """In-memory transport for structural tests. No network, no credentials."""

    def __init__(self):
        self.connected = False
        self.closed = False
        self.sent_packets = []
        self._seq_inbox = []
        self.auto_reply = True
        self._login_seen = False
        self._enter_seen = False

    def connect(self):
        self.connected = True
        self.closed = False

    def send_raw(self, data: bytes):
        self.sent_packets.append(data)

    def note_client_cmd(self, command: int):
        """Called by session after recording outbound cmds so mock can reply."""
        if not self.auto_reply:
            return
        if command == CMD_LOGIN and not self._login_seen:
            self._login_seen = True
            self.queue_server_frame(CMD_GAME_DIR, 0, _pack_game(1001, "★★★三国对战房★★★"))
            self.queue_server_frame(CMD_ROOM_DIR, 0, _pack_room(1001, 1001, "多线2（主线）"))
            self.queue_server_frame(CMD_AUTH_OK, 1, _pack_auth_ok())
        elif command == CMD_ENTER and not self._enter_seen:
            self._enter_seen = True
            self.queue_server_frame(CMD_ENTER_ACK, 2, _pack_enter_ack(1001))

    def queue_server_frame(self, cmd, seq, body=b""):
        self._seq_inbox.append((cmd, seq, body))

    def recv_frames(self, deadline: float):
        frames = list(self._seq_inbox)
        self._seq_inbox.clear()
        return frames

    def close(self):
        self.closed = True
        self.connected = False


class ResidentSession:
    """Obtain one hall grant, optionally leave 「房间用户」, then search-only."""

    # High-risk alts that must never be used for production hall login.
    BLOCKED_LIVE_ACCOUNTS = frozenset({"abcde"})

    def __init__(
        self,
        transport,
        search_fn: Callable[[dict], dict],
        ledger: Optional[OpcodeLedger] = None,
        account: str = "mock-alt",
        leave_hall_after_grant: bool = True,
        allow_live_login: bool = False,
    ):
        self.transport = transport
        self.search_fn = search_fn
        self.ledger = ledger or OpcodeLedger()
        self.account = account
        self.leave_hall_after_grant = leave_hall_after_grant
        self.allow_live_login = allow_live_login
        self.sequence = 0
        self.login_verified = False
        self.entered = False  # grant obtained (may already have left hall)
        self.hall_presence = PRESENCE_ABSENT
        self.relay_config = None
        self.target_room_id = None
        self.session_id = 0
        self.search_cycles = 0
        self.last_query_status = None
        self.last_rooms = []
        self.last_observed_at = None
        self.last_error = None
        self._logout_after_grant_done = False

    @property
    def presence_mechanism(self) -> str:
        return MECHANISM_LEAVE if self.leave_hall_after_grant else MECHANISM_STAY

    @property
    def room_list_visible_expected(self) -> bool:
        """True only while hall TCP still holds the 多线2 occupancy."""
        return self.hall_presence == PRESENCE_IN_ROOM

    @property
    def has_grant(self) -> bool:
        return bool(self.relay_config)

    def _next_seq(self) -> int:
        self.sequence += 1
        return self.sequence

    def _send_cmd(self, command: int, body: bytes = b""):
        seq = self._next_seq()
        self.ledger.record(command, seq)
        note = getattr(self.transport, "note_client_cmd", None)
        if callable(note):
            note(command)
        self.transport.send_raw(wrap(encode(command, seq, body)))
        return seq

    def _apply_grant(self, user: dict, token: str, target: Optional[dict], ack_room: int):
        self.entered = True
        self.session_id += 1
        self.target_room_id = ack_room
        self.hall_presence = PRESENCE_IN_ROOM
        self.relay_config = {
            "username": user["name"],
            "virtual_ip": user["s2c"],
            "server": (target or {}).get("server") or DEFAULT_HOST,
            "port": (target or {}).get("port", 9151),
            "game_id": (target or {}).get("game_id", 1001),
            "room_id": ack_room,
            "user_id": user["id"],
            "token": token,
        }

    def _leave_hall_keep_grant(self):
        """Send 0x2002 so platform drops 「房间用户」; keep relay_config for search."""
        if self._logout_after_grant_done:
            return
        if not self.relay_config:
            raise RuntimeError("leave_without_grant")
        self._send_cmd(CMD_LOGOUT)
        self._logout_after_grant_done = True
        self.login_verified = False  # hall TCP logged out; grant still held
        self.hall_presence = PRESENCE_LEFT_AFTER_GRANT

    def establish(self, username: str, password: str, wait_seconds: float = 12.0) -> dict:
        """Login + one enter for grant. Default: leave hall before returning."""
        self.account = username
        if self.allow_live_login:
            if username in self.BLOCKED_LIVE_ACCOUNTS:
                raise RuntimeError("blocked_high_risk_alt")
            if isinstance(self.transport, MockTransport):
                raise RuntimeError("live_flag_with_mock_transport")
        else:
            # Structural / dry-run only. Real TCP requires allow_live_login=True
            # plus a clean alt (never abcde).
            if not isinstance(self.transport, MockTransport):
                raise RuntimeError("live_login_disabled")
        self.transport.connect()
        self._send_cmd(CMD_LOGIN, login_body(username, password))
        del password

        target_game = None
        target = None
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline and not self.entered:
            slice_end = min(deadline, time.monotonic() + 1.0)
            frames = self.transport.recv_frames(slice_end)
            if not frames:
                if isinstance(self.transport, MockTransport):
                    frames = self.transport.recv_frames(slice_end)
                if not frames:
                    if not isinstance(self.transport, MockTransport):
                        continue
                    if self.entered:
                        break
                    if self.ledger.count(CMD_ENTER) and not self.entered:
                        continue
                    if self.login_verified:
                        continue
                    break
            for cmd, seq, body in frames:
                if cmd == CMD_GAME_DIR:
                    game, _ = game_directory(body)
                    if TARGET_GAME_SUBSTR in game["name"]:
                        target_game = game["id"]
                elif cmd == CMD_ROOM_DIR:
                    room, _ = room_directory(body)
                    if target_game is not None and room["game_id"] == target_game:
                        if TARGET_ROOM_SUBSTR in room["name"].replace(" ", ""):
                            target = room
                elif cmd == CMD_AUTH_OK:
                    r = Reader(body)
                    auth_result = r.number()
                    _message = r.string()
                    self.login_verified = auth_result == 0
                    if not self.login_verified:
                        raise RuntimeError("login_failed")
                    if target is None:
                        raise RuntimeError("target_room_missing")
                    if not self.entered and self.ledger.count(CMD_ENTER) == 0:
                        self._send_cmd(CMD_ENTER, struct.pack("<I", target["id"]))
                        self.target_room_id = target["id"]
                elif cmd == CMD_ENTER_ACK:
                    if self.ledger.count(CMD_ENTER) < 1:
                        continue
                    r = Reader(body)
                    enter_result = r.number()
                    _msg = r.string()
                    ack_room = r.number()
                    user = user_record(r)
                    token = r.string()
                    if enter_result != 0:
                        raise RuntimeError("enter_failed")
                    self._apply_grant(user, token, target, ack_room)
                    if self.leave_hall_after_grant:
                        # Leave hall ASAP — do not request members (extends visibility).
                        self._leave_hall_keep_grant()
                    else:
                        self._send_cmd(CMD_MEMBERS, struct.pack("<I", ack_room))

        if not self.has_grant:
            raise RuntimeError("session_not_established")
        if self.leave_hall_after_grant and self.hall_presence != PRESENCE_LEFT_AFTER_GRANT:
            raise RuntimeError("failed_to_leave_hall_after_grant")
        return {
            "login_verified": True,
            "entered": True,
            "has_grant": True,
            "session_id": self.session_id,
            "room_id": self.target_room_id,
            "enter_count": self.ledger.count(CMD_ENTER),
            "logout_count": self.ledger.count(CMD_LOGOUT),
            "hall_presence": self.hall_presence,
            "room_list_visible_expected": self.room_list_visible_expected,
            "presence_mechanism": self.presence_mechanism,
        }

    def search_once(self) -> dict:
        """Run one room search without login/enter/logout on the hall TCP."""
        if not self.has_grant:
            raise RuntimeError("not_in_session")
        # Hall socket may already be logged out; only drain if still connected.
        if self.hall_presence == PRESENCE_IN_ROOM:
            try:
                self.transport.recv_frames(time.monotonic() + 0.2)
            except ConnectionError:
                raise
        started = time.monotonic()
        cfg = dict(self.relay_config)
        result = self.search_fn(cfg)
        del cfg
        rooms = result.get("rooms") or []
        uniq = {
            (r.get("id"), r.get("name"), r.get("host")): r
            for r in rooms
            if isinstance(r, dict)
        }
        rooms = sorted(
            uniq.values(),
            key=lambda x: (str(x.get("id")), str(x.get("name")), str(x.get("host"))),
        )
        status = "replies_received" if rooms else "unconfirmed_empty"
        self.search_cycles += 1
        self.last_rooms = rooms
        self.last_query_status = status
        self.last_observed_at = time.time()
        self.last_error = None
        return {
            "ok": True,
            "account": self.account,
            "rooms": rooms,
            "query_status": status,
            "observed_at": self.last_observed_at,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "session_id": self.session_id,
            "search_cycles": self.search_cycles,
            "enter_count": self.ledger.count(CMD_ENTER),
            "logout_count": self.ledger.count(CMD_LOGOUT),
            "login_count": self.ledger.count(CMD_LOGIN),
            "hall_presence": self.hall_presence,
            "room_list_visible_expected": self.room_list_visible_expected,
            "presence_mechanism": self.presence_mechanism,
            "game_start_confirmed": False,
            "opensession_join": False,
        }

    def logout(self):
        """Hall logout. No-op if already left after grant."""
        if self._logout_after_grant_done or self.hall_presence == PRESENCE_LEFT_AFTER_GRANT:
            return
        if not self.login_verified and self.hall_presence != PRESENCE_IN_ROOM:
            return
        try:
            self._send_cmd(CMD_LOGOUT)
        except OSError:
            pass
        self.login_verified = False
        if self.hall_presence == PRESENCE_IN_ROOM:
            self.hall_presence = PRESENCE_ABSENT if not self.relay_config else PRESENCE_LEFT_AFTER_GRANT

    def close(self, send_logout: bool = True):
        if send_logout and self.hall_presence == PRESENCE_IN_ROOM:
            self.logout()
        self.transport.close()
        # Drop grant from memory on full close.
        if self.relay_config is not None:
            self.relay_config.clear()
            self.relay_config = None
        self.entered = False

    def public_status(self) -> dict:
        return {
            "ok": bool(self.has_grant and self.last_query_status is not None),
            "phase": "ready" if self.has_grant else "idle",
            "account": self.account,
            "rooms": self.last_rooms,
            "query_status": self.last_query_status,
            "observed_at": self.last_observed_at,
            "session_id": self.session_id,
            "search_cycles": self.search_cycles,
            "enter_count": self.ledger.count(CMD_ENTER),
            "logout_count": self.ledger.count(CMD_LOGOUT),
            "login_count": self.ledger.count(CMD_LOGIN),
            "hall_presence": self.hall_presence,
            "room_list_visible_expected": self.room_list_visible_expected,
            "presence_mechanism": self.presence_mechanism,
            "game_start_confirmed": False,
            "opensession_join": False,
            "error": self.last_error,
        }


def mock_search_fn(relay_config: dict) -> dict:
    """Deterministic search for dry-run / unit tests. Ignores token content."""
    _ = relay_config.get("room_id")
    return {
        "rooms": [
            {
                "id": "42",
                "name": "SGZWLB",
                "host": "mock-host",
                "current": 1,
                "maximum": 8,
            }
        ],
        "relay_registered": True,
        "opensession_join": False,
    }
