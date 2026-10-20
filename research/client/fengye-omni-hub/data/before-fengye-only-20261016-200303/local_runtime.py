"""Reuse authorized original Hub settings privately, without altering them."""
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent


def configure(data_dir=None):
    data = Path(data_dir or ROOT / 'data')
    data.mkdir(parents=True, exist_ok=True)
    candidates = (ROOT.parent / 'SGI-Hub-CrossOver-M4-0.2', Path.home() / 'Applications/SGI-Hub')
    upstream = next((p for p in candidates if (p / 'connection.local.json').is_file()), None)
    target = data / 'connection.local.json'
    if upstream and not target.exists():
        shutil.copy2(upstream / 'connection.local.json', target)
        selected = upstream / 'selected-source.local.json'
        if selected.is_file():
            shutil.copy2(selected, data / selected.name)
    os.environ['SGI_CONNECTION_CONFIG'] = str(target)
    settings = data / 'omni-install.local.json'
    if upstream and not settings.exists():
        settings.write_text(json.dumps({'archive_root': str(upstream / 'game-archives'),
                                        'history_root': str(upstream / 'history-data')}, ensure_ascii=False))
    try:
        cfg = json.loads(settings.read_text())
    except (OSError, ValueError):
        cfg = {}
    for name, key in (('SGI_HUB_REPLAY', 'archive_root'), ('SGI_HUB_HISTORY', 'history_root')):
        if cfg.get(key) and Path(cfg[key]).is_dir():
            os.environ[name] = cfg[key]
    return target
