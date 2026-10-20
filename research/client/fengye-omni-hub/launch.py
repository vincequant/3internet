"""Open the independent native viewer; reuse its own Mac window when possible."""
import os
from pathlib import Path
import subprocess
import sys
import plistlib

ROOT = Path(__file__).resolve().parent


def main():
    script = str(ROOT / 'run.py')
    native = Path.home() / 'Library/Application Support/SGI-Wine/風夜全知情報 Hub.app/Contents/MacOS/FengyeHub'
    use_native = False
    if sys.platform == 'darwin' and native.is_file():
        try:
            info = plistlib.loads((native.parent.parent / 'Info.plist').read_bytes())
            use_native = info.get('SGIFengyeSourceRoot') == str(ROOT)
        except (OSError, ValueError):
            pass
    if sys.platform == 'darwin':
        try:
            rows = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True, timeout=3)
            for row in rows.splitlines():
                pid, _, cmd = row.strip().partition(' ')
                if not (script in cmd or use_native and str(native) in cmd) or '--replay' in cmd or '--verify-json' in cmd or not pid.isdigit():
                    continue
                if int(pid) == os.getpid():
                    continue
                result = subprocess.run(['osascript', '-e',
                    'tell application "System Events" to set frontmost of first application process whose unix id is ' + pid + ' to true'],
                    capture_output=True, timeout=4)
                if result.returncode == 0:
                    print('風夜全知情報 Hub 已在運行，已切到原視窗。')
                    return
        except (OSError, subprocess.SubprocessError):
            pass
    (ROOT / 'data').mkdir(exist_ok=True)
    options = {'start_new_session': True} if os.name == 'posix' else {
        'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    with (ROOT / 'data/native.log').open('ab') as log:
        child = subprocess.Popen([str(native)] if use_native else [sys.executable, '-B', script], cwd=ROOT, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, **options)
    (ROOT / 'data/native.pid').write_text(str(child.pid), encoding='utf-8')
    print('風夜全知情報 Hub 已啟動（原生視窗）。')


if __name__ == '__main__':
    main()
