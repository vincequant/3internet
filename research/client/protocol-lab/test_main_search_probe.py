"""Source checks for the main-prefix grok-bot SearchSession contrast."""
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parent
PROBE = LAB / 'main_loader_probe.py'
RUNNER = LAB / 'run_main_search_probe.py'
LOADER = LAB / 'loader_probe.py'


class MainLoaderProbeTests(unittest.TestCase):
    def test_is_grokbot_topology_without_sanpk_or_monitor_asserts(self):
        src = PROBE.read_text(encoding='utf-8')
        orig = LOADER.read_text(encoding='utf-8')
        self.assertIn("InitDll(callback, udp_port)", src)
        self.assertIn('for _attempt in range(3):', src)
        self.assertIn('time.monotonic() + 5', src)
        self.assertIn('--with-nethook', src)
        self.assertIn('255.255.255.255', src)
        self.assertIn("'--port', '7777'", src)
        self.assertIn("'--app-id', '78731'", src)
        self.assertIn('prefix-sikarugir10', src)
        self.assertNotIn('prefix-monitor', src)
        self.assertNotIn("username'] == 'abcde'", src)
        self.assertNotIn('SANPK.exe', src)
        self.assertNotIn("/1an", src)
        self.assertIn("'launched_sanpk': False", src)
        self.assertIn("udp_port not in (4577, 4578)", src)
        self.assertIn('cfg[\'token\'] = None', src)
        self.assertIn('os.chdir(str(root))', src)
        self.assertIn('range(3)', orig)
        self.assertIn('monotonic()+5', orig.replace(' ', ''))

    def test_runner_contrasts_both_ports_and_reads_sockets(self):
        src = RUNNER.read_text(encoding='utf-8')
        self.assertIn('for port in (4577, 4578):', src)
        self.assertIn('WATCHED', src)
        self.assertIn('25001', src)
        self.assertIn('9151', src)
        self.assertIn('socket_snapshot', src)
        self.assertIn('tk_snapshot', src)
        self.assertIn('load_credentials', src)
        self.assertIn("kind='main'", src)
        self.assertIn('grant_for_takeover', src)
        self.assertNotIn('creds-set', src)
        self.assertIn("if found['sanguo']:", src)
        self.assertIn('stop_leftover_protocol', src)
        self.assertIn('lsof', src)
        self.assertNotIn('nmap', src.lower())
        self.assertIn("[-400:]", src)
        self.assertNotIn("[-400]", src.replace('[-400:]', ''))


if __name__ == '__main__':
    unittest.main()
