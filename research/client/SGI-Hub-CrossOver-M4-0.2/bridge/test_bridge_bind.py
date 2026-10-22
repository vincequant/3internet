import socket
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from bridge_bind import bind_servers

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'ok'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BridgeBindTests(unittest.TestCase):
    def test_remote_port_taken_keeps_local_port(self):
        busy = socket.socket()
        busy.bind(('127.0.0.1', 0))
        busy.listen(1)
        remote_port = busy.getsockname()[1]
        local = remote = None
        try:
            local, remote = bind_servers(Handler, local_port=0, remote_port=remote_port)
            self.assertIsNone(remote)
            self.assertGreater(local.server_address[1], 0)
            with socket.create_connection(local.server_address, timeout=2):
                pass
        finally:
            if remote is not None:
                remote.server_close()
            if local is not None:
                local.server_close()
            busy.close()

    def test_bridge_keeps_local_when_readonly_port_fails(self):
        text = (ROOT / 'bridge/windows_bridge.py').read_text(encoding='utf-8')
        self.assertIn('server,remote_server=bind_servers(Handler)', text)
        self.assertNotIn('except Exception:server.server_close();raise', text)
        self.assertIn('if remote_server is not None:', text)
        main = (ROOT / 'app/mac_main.py').read_text(encoding='utf-8')
        self.assertIn('采集桥未就绪，仍打开全知情报：', main)
        self.assertLess(main.index('采集桥未就绪，仍打开全知情报：'), main.index('root=tk.Tk()'))


if __name__ == '__main__':
    unittest.main()
