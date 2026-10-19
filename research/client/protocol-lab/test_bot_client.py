import unittest
from unittest.mock import patch
from types import SimpleNamespace
import sgi_bot_client as client


class ClientTests(unittest.TestCase):
    def test_host_cannot_inject_ssh_options_or_commands(self):
        for host in ['-oProxyCommand=bad', 'mac; bad', 'mac\ncmd', 'mac $(bad)']:
            with self.assertRaises(ValueError):
                client.fetch(host)

    def test_invalid_response_does_not_become_empty_success(self):
        with patch.object(client.shutil, 'which', return_value='/usr/bin/ssh'), patch.object(
                client.subprocess, 'run', return_value=SimpleNamespace(stdout='not JSON', returncode=255)):
            self.assertFalse(client.fetch('monitor')['ok'])

    def test_remote_error_preserved(self):
        with patch.object(client.shutil, 'which', return_value='/usr/bin/ssh'), patch.object(
                client.subprocess, 'run', return_value=SimpleNamespace(
                    stdout='{"ok":false,"status":"query_failed","rooms":[]}', returncode=2)):
            self.assertEqual(client.fetch('monitor')['status'], 'query_failed')

    def test_empty_is_explicitly_uncertain(self):
        result = {'ok': True, 'status': 'unconfirmed_empty', 'rooms': [],
                  'updated_at': 1, 'age_seconds': 0}
        self.assertIn('不能据此确认', client.brief(result))


if __name__ == '__main__':
    unittest.main()
