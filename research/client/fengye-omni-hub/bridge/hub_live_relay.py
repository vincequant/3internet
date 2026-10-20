"""Push the local collector to vkquant so the iPad Hub stays current.

Reads http://127.0.0.1:8769/api/state and posts a slim document to
https://www.vkquant.ai/api/sgi-war/live. The write token stays in
~/.config/sgi-war/write.env. This process does not touch the game.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from hub_live import hub_live_document

LOCAL = 'http://127.0.0.1:8769/api/state'
INTERVAL_S = 2
WRITE_HEADER = 'X-SGI-War-Write-Token'


def load_write_config():
    path = Path(os.environ.get('SGI_WAR_WRITE_ENV') or Path.home() / '.config' / 'sgi-war' / 'write.env')
    values = {}
    if path.is_file():
        for line in path.read_text(encoding='utf8').splitlines():
            text = line.strip()
            if not text or text.startswith('#') or '=' not in text:
                continue
            key, value = text.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    url = os.environ.get('SGI_WAR_UPLOAD_URL') or values.get('SGI_WAR_UPLOAD_URL')
    token = os.environ.get('SGI_WAR_WRITE_TOKEN') or values.get('SGI_WAR_WRITE_TOKEN')
    if not url or not token:
        return None
    return {'url': url, 'token': token}


def live_url(upload_url):
    # D1 is full, so the live document is held on the mainland site, not the worker.
    return 'https://vkquant.com/tk-hub/api'


def fetch_local():
    req = urllib.request.Request(LOCAL, method='GET')
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode('utf8'))


def post_live(url, token, doc):
    body = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf8')
    req = urllib.request.Request(
        url, data=body, method='POST',
        headers={'Content-Type': 'application/json', WRITE_HEADER: token, 'User-Agent': 'sgi-war-uploader/0.1'},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf8'))


def main():
    cfg = load_write_config()
    if not cfg:
        print('缺少 ~/.config/sgi-war/write.env', file=sys.stderr)
        return 1
    url = live_url(cfg['url'])
    last = None
    while True:
        try:
            doc = hub_live_document(fetch_local())
            snap = None if not doc else doc.get('snapshot_id')
            if doc and snap != last:
                result = post_live(url, cfg['token'], doc)
                if result.get('ok'):
                    last = snap
                    print('sent', snap, file=sys.stderr)
                else:
                    print('reject', result.get('error'), file=sys.stderr)
        except urllib.error.HTTPError as error:
            print('wait', error.code, file=sys.stderr)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            print('wait', type(error).__name__, file=sys.stderr)
        time.sleep(INTERVAL_S)


if __name__ == '__main__':
    sys.exit(main() or 0)
