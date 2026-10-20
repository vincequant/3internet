"""Bind the local collector port. The read-only port is optional."""
from http.server import ThreadingHTTPServer


def bind_servers(handler, local_port=8769, remote_port=8770, host='127.0.0.1'):
    """Keep the local API up when the read-only port is already taken.

    macOS sharingd listens on 8770. Closing 8769 after that failure makes the
    Hub and the quick panel see connection refused.
    """
    server = ThreadingHTTPServer((host, local_port), handler)
    remote = None
    try:
        remote = ThreadingHTTPServer((host, remote_port), handler)
    except OSError as error:
        print(f'只读端口 {remote_port} 未打开：{error}。本机 {local_port} 继续服务。', flush=True)
    return server, remote
