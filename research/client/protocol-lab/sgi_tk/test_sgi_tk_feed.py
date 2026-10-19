import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sgi_tk_scheduler
import sgi_tk_uploader as uploader


class UploaderTests(unittest.TestCase):
    def test_payload_whitelist_and_no_password(self):
        payload = uploader.build_payload({
            "ok": True,
            "status": "replies_received",
            "updated_at": 1780000000.5,
            "rooms": [{
                "id": "1",
                "name": "SGZ<script>",
                "host": "VK",
                "current": 1,
                "maximum": 8,
                "password": "secret",
                "extra": "drop-me",
            }],
            "account": "abcde",
        })
        self.assertEqual(payload["source_id"], "sgi-tk-monitor")
        self.assertEqual(payload["rooms"][0]["name"], "SGZ<script>")
        self.assertNotIn("password", json.dumps(payload))
        self.assertNotIn("abcde", json.dumps(payload))
        self.assertFalse(payload["game_start_confirmed"])

    def test_failed_result_keeps_explicit_status(self):
        payload = uploader.build_payload({
            "ok": False,
            "status": "timeout",
            "rooms": [],
            "message": "等待最新查询结果超时，不能判断是否有房间",
        })
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["query_status"], "timeout")


class SchedulerTests(unittest.TestCase):
    def test_second_instance_does_not_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "scheduler.lock"
            with patch.object(sgi_tk_scheduler, "LOCK_PATH", lock), \
                    patch.object(sgi_tk_scheduler, "LOG_PATH", Path(tmp) / "log.jsonl"), \
                    patch.object(sgi_tk_scheduler, "STATE_PATH", Path(tmp) / "state.json"):
                first = sgi_tk_scheduler.acquire_lock()
                self.assertIsNotNone(first)
                second = sgi_tk_scheduler.acquire_lock()
                self.assertIsNone(second)
                first.close()

    def test_backoff_is_bounded(self):
        self.assertEqual(sgi_tk_scheduler.backoff_seconds(1), 5)
        self.assertLessEqual(sgi_tk_scheduler.backoff_seconds(9), 60)


if __name__ == "__main__":
    unittest.main()
