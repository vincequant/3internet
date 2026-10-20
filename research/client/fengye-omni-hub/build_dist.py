"""Ship only reviewed source/assets. Local configuration and observations stay local."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = ('player_text.py', 'backend/fengyun_local.py', 'backend/lab_remote.py',
         'tests/test_fengyun.py', 'tests/test_player_text.py', 'run.py', 'launch.py', 'native_window.py', 'fengye_source.py', 'local_runtime.py',
         'backend/server.py', 'backend/remote_snapshot.py', 'backend/cmd_intel.py',
         'backend/city_id_table.json',
         'RELEASE.json', 'UPSTREAM.json',
         'README.md', 'requirements.txt', 'build_app.py', 'build_dist.py',
         '啟動風夜Hub.command', '启动风夜Hub.cmd', 'tests/test_native.py',
         'config.example.json', 'room_client.py', 'backend/room_protocol.py',
         'backend/room_remote.py', 'backend/room_probe.py', 'tests/test_rooms.py',
         'command_service.py', 'tests/test_command_dedupe.py',
         'command_panel.py', 'command_presentation.py', 'fengye_command_effects.py',
         'fengye_diagnostics.py', 'fengye_capture_status.py', 'fengye_force_views.py',
         'tests/test_capture_status.py', 'tests/test_force_views.py',
         'tests/test_construction_grid.py',
         'build_picker.py', 'fengye_battle_panel.py', 'fengye_icon.py',
         'legacy_command_history.py',
         'tests/test_command_queue.py', 'tests/test_command_session.py',
         'tests/test_command_effects.py', 'tests/test_command_presentation.py',
         'tests/test_command_panel.py', 'tests/test_build_picker.py',
         'tests/test_battle_panel.py', 'tests/test_legacy_command_history.py',
         'assets/fengye-icon.png', 'assets/fengye-icon-256.png',
         'assets/fengye-icon.ico', 'assets/fengye.icns', 'assets/fengye-icon.prompt.txt',
         'docs/command-map-0.2.32.md', 'docs/verify_native_0_2_32.py',
         'docs/panel-0.2.32-battle.png', 'docs/panel-0.2.32-commands.png',
         'docs/panel-0.2.32-picker.png',
         'docs/live-and-construction-0.2.33.md', 'docs/live-0.2.33-review.md',
         'docs/construction-native-rule-0.2.33.md', 'docs/construction-live-0.2.33.json',
         'docs/verify_native_0_2_33.py', 'docs/live-0.2.33-verification.json',
         'docs/panel-0.2.33-forces.png', 'docs/panel-0.2.33-compare.png',
         'docs/panel-0.2.33-commands.png', 'docs/panel-0.2.33-battle.png',
         'docs/panel-0.2.33-picker.png',
         'tests/test_map_camera.py', 'tests/test_map_events.py',
         'docs/map-display-0.2.31.md',
         'docs/panel-20261020-mapfix-0.2.31-window.png',
         'docs/panel-20261020-mapfix-0.2.31-canvas.png',
         'docs/panel-20261020-mapfix-0.2.31-canvas.ps')
LAB_TOOLS = ('_p60_battle.py', '_p60_pick_cell_wide.py',
             '_p60_construction_grid.py', '_p60_construction_rules.py')


def main():
    upstream = json.loads((ROOT / 'UPSTREAM.json').read_text(encoding='utf-8'))['files']
    sources = {n: ROOT / n for n in set(FILES) | set(upstream)}
    sources.update({'lab-tools/' + n: (ROOT / 'lab-tools' / n if (ROOT / 'lab-tools' / n).is_file()
                                      else ROOT.parent / 'protocol-lab' / n) for n in LAB_TOOLS})
    names = sorted(sources)
    if any(Path(n).is_absolute() or '..' in Path(n).parts or n.startswith('data/') for n in names):
        raise ValueError('Unapproved distribution path')
    contents = {n: sources[n].read_bytes() for n in names}
    sums = {n: hashlib.sha256(b).hexdigest() for n, b in contents.items()}
    release = json.loads(contents['RELEASE.json'])
    dest = ROOT / 'dist'
    dest.mkdir(exist_ok=True)
    archive = dest / ('fengye-omni-hub-' + release['version'] + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in contents.items():
            z.writestr('fengye-omni-hub/' + name, data)
        z.writestr('fengye-omni-hub/SHA256SUMS.txt', ''.join('{}  {}\n'.format(sums[n], n) for n in names))
    archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
    print(json.dumps({'archive': str(archive), 'files': len(names), 'version': release['version']}))


if __name__ == '__main__':
    main()
