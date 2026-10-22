"""Build/apply a verified, explicit source bundle. Machine config is never shipped.

python publish.py build OUTPUT.zip
python publish.py apply OUTPUT.zip TARGET
python publish.py rollback TARGET BACKUP
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parent
TOP = {'RELEASE.json', 'requirements.txt', 'Start-Mac.command', 'Start-Windows.cmd',
       'Start-Quick-Control.command', 'Start-Quick-Control.cmd', 'QUICK-CONTROL.md',
       'Start-Room-Watch.command', 'Start-Room-Watch.cmd',
       'Start-Quiet-Wait.command', 'Start-Quiet-Wait.cmd',
       'Start-Wine-Nav.command', 'Start-Wine-Nav.cmd',
       'Start-Replay.command', 'Start-Replay.cmd',
       'Start-War-Query.command', 'Start-War-Query.cmd',
       'publish.py', 'README-SYNC.md', 'REPLAY.md', 'WAR-QUERY.md', 'GROK_WAR_PROMPT.md',
       'MOVE-GRID-CALIBRATION.md',
       'CHATGPT-MCP.md'}

WIN32_PYTHON_SUFFIX = {'.exe', '.dll', '.pyd', '.zip', '.txt', '.pth', '.json', '.md'}


def allowed(name):
    p = Path(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or '__pycache__' in p.parts:
        return False
    if name in TOP:
        return True
    if len(p.parts) >= 2 and p.parts[0] == 'bridge' and p.parts[1] == 'win32-python':
        return p.suffix.lower() in WIN32_PYTHON_SUFFIX
    if (p.parts[0] in ('app', 'bridge') and 'python' not in p.parts
            and p.suffix in ('.py', '.json', '.jsonl', '.bmp', '.png', '.mbm', '.lbm', '.rbm')):
        return True
    return (p.parts[0] == 'room_monitor' and p.suffix == '.py'
            and 'credentials.json' not in p.parts and '.login.json' not in p.parts)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def build(out):
    files = {str(p.relative_to(ROOT)).replace('\\', '/'): p.read_bytes()
             for p in ROOT.rglob('*') if p.is_file() and allowed(str(p.relative_to(ROOT)).replace('\\', '/'))}
    manifest = {'release': json.loads(files['RELEASE.json']), 'sha256': {n: digest(b) for n, b in files.items()}}
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr('DEPLOY-MANIFEST.json', json.dumps(manifest, indent=2))
    print(json.dumps({'bundle': str(out), 'files': len(files), 'version': manifest['release']['version']}))

def apply(bundle, target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle) as z:
        manifest = json.loads(z.read('DEPLOY-MANIFEST.json'))
        names = manifest['sha256']
        if any(not allowed(n) for n in names) or set(z.namelist()) != set(names) | {'DEPLOY-MANIFEST.json'}:
            raise ValueError('Bundle contains unapproved paths')
        content = {n: z.read(n) for n in names}
        if any(digest(content[n]) != sha for n, sha in names.items()):
            raise ValueError('Bundle checksum mismatch')
    changed = [n for n in names if not (target / n).is_file() or digest((target / n).read_bytes()) != names[n]]
    if not changed:
        print(json.dumps({'status': 'unchanged', 'version': manifest['release']['version']}))
        return
    backup = target / 'updates' / ('release-' + str(time.time_ns()))
    backup.mkdir(parents=True)
    created = []
    for name in changed:
        old = target / name
        if old.exists():
            dst = backup / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, dst)
        else:
            created.append(name)
    old_manifest=(target/'DEPLOY-MANIFEST.json').read_text(encoding='utf8') if (target/'DEPLOY-MANIFEST.json').exists() else None
    (backup / 'rollback.json').write_text(json.dumps({'changed': changed, 'created': created, 'old_manifest': old_manifest}), encoding='utf8')
    try:
        for name in changed:
            dst = target / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            temp = dst.with_name(dst.name + '.deploy-tmp')
            temp.write_bytes(content[name])
            temp.replace(dst)
            if dst.suffix == '.command':
                dst.chmod(0o755)
        (target / 'DEPLOY-MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    except Exception:
        rollback(target, backup)
        raise
    print(json.dumps({'status': 'deployed', 'changed': len(changed), 'backup': str(backup), 'version': manifest['release']['version']}))

def rollback(target, backup):
    target, backup = Path(target), Path(backup)
    record = json.loads((backup / 'rollback.json').read_text(encoding='utf8'))
    for name in record['changed']:
        if not allowed(name):
            raise ValueError('Invalid rollback path')
        dst = target / name
        if name in record['created']:
            if dst.exists():
                retained = backup / 'rolled-back-new-files' / name
                retained.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(retained))
        else:
            shutil.copy2(backup / name, dst)
    manifest=target/'DEPLOY-MANIFEST.json'
    if record.get('old_manifest') is not None:manifest.write_text(record['old_manifest'],encoding='utf8')
    elif manifest.exists():shutil.move(str(manifest),str(backup/'rolled-back-manifest.json'))
    print(json.dumps({'status': 'rolled_back', 'backup': str(backup)}))

if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'build':
        build(sys.argv[2])
    elif command == 'apply':
        apply(sys.argv[2], sys.argv[3])
    elif command == 'rollback':
        rollback(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit('Unknown command')
