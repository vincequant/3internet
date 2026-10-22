"""Handle process termination on the Tk event loop, never inside a signal frame.

Tk 9's macOS SIGTERM handler calls Tcl_Exit synchronously. Destroy bindings can
then re-enter Python without the expected _tkinter thread state and abort.
Only set a Python flag in our handler; the periodic Tk callback closes normally.
"""
import signal
import sys

def install(root, close):
    if sys.platform == 'win32':
        return
    pending = [False]
    def request(_signum, _frame):
        pending[0] = True
    def poll():
        if pending[0]:
            close()
        else:
            root.after(100, poll)
    # Install after Tk initialization, which installs its own native handler.
    signal.signal(signal.SIGTERM, request)
    signal.signal(signal.SIGINT, request)
    root.after(100, poll)
