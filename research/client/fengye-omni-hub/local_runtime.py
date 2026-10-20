"""Keep this viewer independent of player-side Omni sources."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def configure(data_dir=None):
    data = Path(data_dir or ROOT / 'data')
    data.mkdir(parents=True, exist_ok=True)
    os.environ['SGI_FENGYE_ONLY'] = '1'
    return data
