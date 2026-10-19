"""Structural tests: leave-hall grant path; mock only; abcde blocked for live."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from resident_session import (
    CMD_ENTER,
    CMD_LOGIN,
    CMD_LOGOUT,
    CMD_MEMBERS,
    MECHANISM_LEAVE,
    MECHANISM_STAY,
    PRESENCE_IN_ROOM,
    PRESENCE_LEFT_AFTER_GRANT,
    MockTransport,
    ResidentSession,
    SocketTransport,
    mock_search_fn,
    reconnect_delay,
)

MOCK_ALT = "mock-alt"


def _load_resident_mod():
    path = Path(__file__).resolve().parent / "bin" / "sgi_tk_resident.py"
    spec = importlib.util.spec_from_file_location("sgi_tk_resident_mod", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class ResidentSessionTests(unittest.TestCase):
    def test_leave_hall_after_grant_then_many_searches(self):
        transport = MockTransport()
        session = ResidentSession(
            transport, mock_search_fn, account=MOCK_ALT, leave_hall_after_grant=True
        )
        info = session.establish(MOCK_ALT, "unit-test-password", wait_seconds=2.0)
        ledger = session.ledger
        self.assertEqual(ledger.count(CMD_LOGIN), 1)
        self.assertEqual(ledger.count(CMD_ENTER), 1)
        self.assertEqual(ledger.count(CMD_LOGOUT), 1)
        self.assertEqual(ledger.count(CMD_MEMBERS), 0)
        self.assertEqual(info["hall_presence"], PRESENCE_LEFT_AFTER_GRANT)
        self.assertFalse(info["room_list_visible_expected"])
        self.assertEqual(info["presence_mechanism"], MECHANISM_LEAVE)
        self.assertTrue(session.has_grant)
        self.assertFalse(session.room_list_visible_expected)

        enter_at = ledger.count(CMD_ENTER)
        logout_at = ledger.count(CMD_LOGOUT)
        login_at = ledger.count(CMD_LOGIN)
        for _ in range(5):
            result = session.search_once()
            self.assertEqual(result["enter_count"], enter_at)
            self.assertEqual(result["logout_count"], logout_at)
            self.assertEqual(result["login_count"], login_at)
            self.assertEqual(result["hall_presence"], PRESENCE_LEFT_AFTER_GRANT)
            self.assertFalse(result["room_list_visible_expected"])
            self.assertFalse(result["opensession_join"])
            self.assertFalse(result["game_start_confirmed"])

        self.assertEqual(ledger.count(CMD_ENTER), 1)
        self.assertEqual(ledger.count(CMD_LOGOUT), 1)
        self.assertEqual(ledger.count(CMD_LOGIN), 1)
        self.assertEqual(session.search_cycles, 5)

        session.close(send_logout=True)
        self.assertEqual(ledger.count(CMD_LOGOUT), 1)

    def test_stay_in_hall_mode_still_one_enter(self):
        session = ResidentSession(
            MockTransport(), mock_search_fn, leave_hall_after_grant=False
        )
        info = session.establish(MOCK_ALT, "unit-test-password", wait_seconds=2.0)
        self.assertEqual(info["hall_presence"], PRESENCE_IN_ROOM)
        self.assertTrue(info["room_list_visible_expected"])
        self.assertEqual(info["presence_mechanism"], MECHANISM_STAY)
        self.assertEqual(session.ledger.count(CMD_ENTER), 1)
        self.assertEqual(session.ledger.count(CMD_LOGOUT), 0)
        self.assertGreaterEqual(session.ledger.count(CMD_MEMBERS), 1)
        for _ in range(3):
            session.search_once()
        self.assertEqual(session.ledger.count(CMD_ENTER), 1)
        self.assertEqual(session.ledger.count(CMD_LOGOUT), 0)
        session.close(send_logout=True)
        self.assertEqual(session.ledger.count(CMD_LOGOUT), 1)

    def test_blocks_abcde_for_live_login(self):
        session = ResidentSession(
            MockTransport(), mock_search_fn, allow_live_login=True
        )
        with self.assertRaisesRegex(RuntimeError, "blocked_high_risk_alt"):
            session.establish("abcde", "x")

    def test_real_tcp_disabled_without_live_flag(self):
        # Do not connect: constructor alone is fine; establish must refuse.
        session = ResidentSession(
            SocketTransport(host="127.0.0.1", port=1),
            mock_search_fn,
            allow_live_login=False,
        )
        with self.assertRaisesRegex(RuntimeError, "live_login_disabled"):
            session.establish("clean-alt", "x")

    def test_unconfirmed_empty_is_not_no_rooms_claim(self):
        def empty_search(_cfg):
            return {"rooms": [], "relay_registered": True}

        session = ResidentSession(MockTransport(), empty_search)
        session.establish(MOCK_ALT, "unit-test-password", wait_seconds=2.0)
        result = session.search_once()
        self.assertEqual(result["query_status"], "unconfirmed_empty")
        self.assertEqual(result["rooms"], [])
        self.assertFalse(result["game_start_confirmed"])
        self.assertEqual(session.ledger.count(CMD_ENTER), 1)
        self.assertEqual(session.ledger.count(CMD_LOGOUT), 1)
        session.close(send_logout=True)
        self.assertEqual(session.ledger.count(CMD_LOGOUT), 1)

    def test_public_status_has_no_secrets(self):
        session = ResidentSession(MockTransport(), mock_search_fn)
        session.establish(MOCK_ALT, "unit-test-password", wait_seconds=2.0)
        session.search_once()
        blob = json.dumps(session.public_status(), ensure_ascii=False)
        self.assertNotIn("password", blob.lower())
        self.assertNotIn("token", blob.lower())
        self.assertNotIn("mock-token", blob)
        self.assertIn("hall_presence", blob)
        self.assertIn(PRESENCE_LEFT_AFTER_GRANT, blob)
        session.close(send_logout=True)

    def test_reconnect_delay_is_jittered_and_bounded(self):
        samples = {reconnect_delay(3, base=5.0, cap=60.0) for _ in range(40)}
        self.assertGreater(len(samples), 5)
        self.assertTrue(all(0.0 <= s <= 60.0 for s in samples))

    def test_search_cycles_never_emit_hall_opcodes(self):
        session = ResidentSession(MockTransport(), mock_search_fn)
        session.establish(MOCK_ALT, "unit-test-password", wait_seconds=2.0)
        after_establish = len(session.ledger.sent)
        for _ in range(8):
            session.search_once()
        mid = session.ledger.commands_after(after_establish)
        self.assertEqual(mid, [])
        session.close(send_logout=True)


class ResidentCliDryRunTests(unittest.TestCase):
    def test_cli_dry_run_no_reenter_and_not_on_list(self):
        mod = _load_resident_mod()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mod.DEFAULT_STATUS = tmp_path / "status.json"
            mod.DEFAULT_LOCK = tmp_path / "lock"
            mod.DEFAULT_LOG = tmp_path / "log"
            rc = mod.main(["--dry-run", "--cycles", "4", "--interval", "0"])
            self.assertEqual(rc, 0)
            status = json.loads(mod.DEFAULT_STATUS.read_text(encoding="utf-8"))
            self.assertEqual(status.get("enter_count"), 1)
            self.assertEqual(status.get("login_count"), 1)
            self.assertEqual(status.get("logout_count"), 1)
            self.assertEqual(status.get("search_cycles"), 4)
            self.assertEqual(status.get("hall_presence"), PRESENCE_LEFT_AFTER_GRANT)
            self.assertFalse(status.get("room_list_visible_expected"))
            self.assertEqual(status.get("presence_mechanism"), MECHANISM_LEAVE)
            # Dry-run must not bind the high-risk alt as the live default.
            self.assertNotEqual(status.get("account"), "abcde")


class DashboardResidentPollTests(unittest.TestCase):
    def test_dashboard_reads_resident_not_probe(self):
        import dashboard

        source = Path(dashboard.__file__).read_text(encoding="utf-8")
        self.assertNotIn("native_login_probe.py", source)
        self.assertNotIn("subprocess", source)
        self.assertIn("read_resident", source)
        self.assertIn("hall_presence", source)
        self.assertIn("room_list_visible_expected", source)

        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "resident-status.json"
            status.write_text(
                json.dumps(
                    {
                        "phase": "ready",
                        "ok": True,
                        "account": MOCK_ALT,
                        "rooms": [
                            {
                                "id": "1",
                                "name": "SGZWLB",
                                "host": "h",
                                "current": 1,
                                "maximum": 8,
                            }
                        ],
                        "query_status": "replies_received",
                        "observed_at": 1000.0,
                        "enter_count": 1,
                        "logout_count": 1,
                        "login_count": 1,
                        "search_cycles": 3,
                        "hall_presence": PRESENCE_LEFT_AFTER_GRANT,
                        "room_list_visible_expected": False,
                        "presence_mechanism": MECHANISM_LEAVE,
                        "game_start_confirmed": False,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(dashboard, "RESIDENT_STATUS", status), mock.patch.object(
                dashboard, "_read_resident_http", return_value=None
            ):
                row = dashboard.read_resident()
            self.assertEqual(row["enter_count"], 1)
            self.assertEqual(row["query_status"], "replies_received")
            self.assertFalse(row["room_list_visible_expected"])


if __name__ == "__main__":
    unittest.main()
