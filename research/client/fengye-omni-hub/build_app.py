"""Install a native Mac .app entry, without embedding a browser or game files."""
from pathlib import Path
import plistlib
import shutil
import sys
import sysconfig
import json
import subprocess
import tempfile
import os

ROOT = Path(__file__).resolve().parent


def main():
    target = Path.home() / 'Library/Application Support/SGI-Wine/風夜全知情報 Hub.app'
    binary = target / 'Contents/MacOS/FengyeHub'
    binary.parent.mkdir(parents=True, exist_ok=True)
    # Embed the existing Python runtime so the running process keeps this
    # bundle's identity and window, instead of becoming an anonymous Python.app.
    def literal(value):
        return json.dumps(str(value), ensure_ascii=False)
    source = '''#include <Python.h>
int main(int argc, char **argv) {
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.parse_argv = 0;
    config.write_bytecode = 0;
    PyStatus status = PyConfig_SetBytesString(&config, &config.home, HOME_PATH);
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesString(&config, &config.executable, PYTHON_PATH);
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesString(&config, &config.run_filename, SCRIPT_PATH);
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesArgv(&config, argc, argv);
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    if (PyRun_SimpleString(SITE_SETUP) != 0) return 1;
    return Py_RunMain();
}
'''
    # A venv contains third-party packages, but its standard library remains
    # under base_prefix. Pointing PyConfig.home at the venv prevents even
    # encodings from loading on machines that build through SGI-Hub's venv.
    macros = '#define HOME_PATH {}\n#define PYTHON_PATH {}\n#define SCRIPT_PATH {}\n#define SITE_SETUP {}\n'.format(
        literal(sys.base_prefix), literal(sys.executable), literal(ROOT / 'run.py'),
        literal('import site; site.addsitedir(' + repr(sysconfig.get_path('purelib')) + ')'))
    with tempfile.TemporaryDirectory() as folder:
        code = Path(folder) / 'main.c'
        staged = Path(folder) / 'FengyeHub'
        code.write_text(macros + source)
        library = Path(sysconfig.get_config_var('LIBDIR'))
        subprocess.run(['/usr/bin/clang', '-I' + sysconfig.get_path('include'), str(code),
                        '-L' + str(library), '-lpython' + sysconfig.get_python_version(),
                        '-Wl,-rpath,' + str(library), '-o', str(staged)], check=True)
        os.replace(staged, binary)
    info = {'CFBundleIdentifier': 'com.vk.sgi.fengye-omni-hub', 'CFBundleName': '化神指揮部',
            'CFBundleDisplayName': '化神指揮部', 'CFBundleExecutable': 'FengyeHub',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': json.loads((ROOT / 'RELEASE.json').read_text())['version'],
            'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '14.0',
            'NSAppSleepDisabled': True}
    info['SGIFengyeSourceRoot'] = str(ROOT)
    # Fengye has its own identity. Never borrow or change the game's/Wine's icon.
    icon = ROOT / 'assets' / 'fengye.icns'
    if icon.is_file():
        resources = target / 'Contents/Resources'
        resources.mkdir(exist_ok=True)
        shutil.copy2(icon, resources / 'AppIcon.icns')
        info['CFBundleIconFile'] = 'AppIcon'
    (target / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    print(target)


if __name__ == '__main__':
    main()
