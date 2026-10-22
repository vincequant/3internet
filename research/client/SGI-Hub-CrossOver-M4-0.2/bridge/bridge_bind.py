"""Bind the local collector port. The read-only port is optional."""
from http.server import ThreadingHTTPServer


def bind_servers(handler, local_port=None, remote_port=None, host='127.0.0.1'):
    """Keep the local API up when the read-only port is already taken.

    macOS sharingd listens on 8770. Closing 8769 after that failure makes the
    Hub and the quick panel see connection refused.
    """
    # 2026-10-19: 多源并存（例如本机风夜影子）需要第二座桥，端口可由环境变量覆盖。
    import os
    if local_port is None:
        local_port = int(os.environ.get('SGI_BRIDGE_PORT', '8769'))
    if remote_port is None:
        remote_port = int(os.environ.get('SGI_BRIDGE_REMOTE_PORT', '8770'))
    server = ThreadingHTTPServer((host, local_port), handler)
    remote = None
    try:
        remote = ThreadingHTTPServer((host, remote_port), handler)
    except OSError as error:
        print(f'只读端口 {remote_port} 未打开：{error}。本机 {local_port} 继续服务。', flush=True)
    return server, remote
