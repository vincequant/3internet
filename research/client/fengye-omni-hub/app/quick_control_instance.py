"""One panel per user; repeated launches request focus, never game input.

The OS releases the lock even after a crash. Keep the lock file in place:
unlinking it would let another process lock a different inode concurrently.
"""
import errno
import os
from pathlib import Path
import uuid


class PanelInstance:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else Path.home() / '.sgi-quick-control'
        self.stream = None

    def acquire(self):
        if self.stream is not None:
            return True
        self.directory.mkdir(parents=True, exist_ok=True)
        stream = (self.directory / 'panel.lock').open('a+b')
        if stream.seek(0, 2) == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            return False
        self.stream = stream
        self.consume_focus()  # discard requests from an earlier, exited panel
        return True

    def request_focus(self):
        # Unique files prevent concurrent launchers from losing each other's
        # request. Empty files carry no arbitrary command or game action.
        (self.directory / ('focus-' + uuid.uuid4().hex)).touch(exist_ok=False)

    def consume_focus(self):
        requested = False
        for path in self.directory.glob('focus-*'):
            try:
                path.unlink(); requested = True
            except FileNotFoundError:
                pass
        return requested

    def close(self):
        if self.stream is not None:
            # Closing releases both flock and the Windows byte-range lock.
            self.stream.close(); self.stream = None


def watch_focus(root, instance):
    if instance.consume_focus():
        root.deiconify(); root.lift(); root.focus_force()
    root.after(250, lambda: watch_focus(root, instance))
