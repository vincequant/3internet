import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from graceful_shutdown import install

class Shutdown(unittest.TestCase):
    def test_signal_only_flags_and_event_loop_closes(self):
        root=Mock();close=Mock()
        with patch('graceful_shutdown.sys.platform','darwin'), patch('graceful_shutdown.signal.signal') as register:
            install(root,close)
            callback=root.after.call_args.args[1]
            callback();self.assertEqual(root.after.call_count,2);close.assert_not_called()
            handler=register.call_args_list[0].args[1]
            handler(15,None);close.assert_not_called();self.assertEqual(root.after.call_count,2)
            callback();close.assert_called_once();self.assertEqual(root.after.call_count,2)

    def test_windows_does_not_replace_native_signal_handling(self):
        root=Mock()
        with patch('graceful_shutdown.sys.platform','win32'), patch('graceful_shutdown.signal.signal') as register:
            install(root,Mock());register.assert_not_called();root.after.assert_not_called()
