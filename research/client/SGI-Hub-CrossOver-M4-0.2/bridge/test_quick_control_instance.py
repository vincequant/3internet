"""Exercise real process exclusion, crash recovery and focus-only IPC."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
from quick_control_instance import PanelInstance, watch_focus


class InstanceTests(unittest.TestCase):
    def test_competing_launch_focus_and_release(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = PanelInstance(directory); peer = PanelInstance(directory)
            try:
                self.assertTrue(owner.acquire())
                self.assertFalse(peer.acquire())
                peer.request_focus(); peer.request_focus()
                root = Mock(); watch_focus(root, owner)
                root.deiconify.assert_called_once(); root.lift.assert_called_once()
                root.focus_force.assert_called_once()
                root.after.assert_called_once()
                self.assertFalse(owner.consume_focus())
                owner.close()
                self.assertTrue(peer.acquire())
            finally:
                owner.close(); peer.close()

    def test_crashed_owner_releases_lock_without_deleting_file(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('import sys, os; sys.path.insert(0, sys.argv[1]); '
                    'from quick_control_instance import PanelInstance; '
                    'g=PanelInstance(sys.argv[2]); assert g.acquire(); '
                    'print("locked",flush=True); sys.stdin.read(); os._exit(0)')
            child = subprocess.Popen([sys.executable, '-B', '-c', code, str(APP), directory],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            peer = PanelInstance(directory)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                self.assertFalse(peer.acquire())
                child.stdin.close(); self.assertEqual(child.wait(timeout=10), 0)
                self.assertTrue(peer.acquire())
                self.assertTrue((Path(directory) / 'panel.lock').exists())
            finally:
                if child.poll() is None:
                    child.kill(); child.wait()
                child.stdout.close(); peer.close()

    def test_reopen_discards_stale_focus_only(self):
        with tempfile.TemporaryDirectory() as directory:
            peer = PanelInstance(directory)
            Path(directory, 'keep.txt').write_text('keep')
            peer.request_focus()
            try:
                self.assertTrue(peer.acquire())
                self.assertFalse(peer.consume_focus())
                self.assertEqual(Path(directory, 'keep.txt').read_text(), 'keep')
                root = Mock(); watch_focus(root, peer)
                root.focus_force.assert_not_called()
            finally:
                peer.close()
