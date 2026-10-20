"""Token-gated holder for the latest iPad Hub document. One row, replaced in place."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = '127.0.0.1'
PORT = 8791
ENV_DIR = Path('/etc/sgi-hub-live')
MAX_BODY = 700_000


def load_env(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding='utf8').splitlines():
        text = line.strip()
        if not text or text.startswith('#') or '=' not in text:
            continue
        key, value = text.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


WRITE = load_env(ENV_DIR / 'write.env').get('SGI_WAR_WRITE_TOKEN', '')
READ = load_env(ENV_DIR / 'read.env').get('SGI_WAR_READ_TOKEN', '')
CURRENT = {'raw': None, 'updated_at': None}


def same(left, right):
    if not left or not right or len(left) != len(right):
        return False
    diff = 0
    for a, b in zip(left, right):
        diff |= ord(a) ^ ord(b)
    return diff == 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send(self, code, body, content_type='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else body.encode('utf8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-SGI-War-Read-Token, X-SGI-War-Write-Token')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, b'')

    def do_POST(self):
        if not same(self.headers.get('X-SGI-War-Write-Token', ''), WRITE):
            return self._send(401, json.dumps({'ok': False, 'error': 'unauthorized_write'}))
        length = int(self.headers.get('Content-Length', '0') or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413, json.dumps({'ok': False, 'error': 'payload_too_large'}))
        raw = self.rfile.read(length)
        try:
            doc = json.loads(raw)
        except ValueError:
            return self._send(400, json.dumps({'ok': False, 'error': 'invalid_json'}))
        if not isinstance(doc, dict) or not doc.get('snapshot_id'):
            return self._send(400, json.dumps({'ok': False, 'error': 'missing_snapshot'}))
        CURRENT['raw'] = raw
        CURRENT['updated_at'] = doc.get('capture_end')
        return self._send(200, json.dumps({
            'ok': True, 'action': 'accepted', 'snapshot_id': doc.get('snapshot_id'),
        }))

    def do_GET(self):
        if not CURRENT['raw']:
            return self._send(200, json.dumps({'ok': True, 'found': False}))
        hub = json.loads(CURRENT['raw'])
        return self._send(200, json.dumps({
            'ok': True, 'found': True, 'updated_at': CURRENT['updated_at'], 'hub': hub,
        }, ensure_ascii=False))


def main():
    if not WRITE or not READ:
        raise SystemExit('missing token file')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
