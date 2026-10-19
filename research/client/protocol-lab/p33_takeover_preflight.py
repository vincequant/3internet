"""Read-only takeover preflight for P33 Phase 3: p26 host discovery + rows read.

Runs no session and writes nothing to game state; wraps the same read_probe
helpers p33_sync_orchestrate.py uses so a later launch sees identical results.
"""
import json
import os
import subprocess
from pathlib import Path

lab = Path.home() / 'sgi-protocol-lab-20260915'
rt = json.loads((Path.home() / 'Library/Application Support/SGI-Wine/runtime.json').read_text())
env = dict(os.environ, WINEPREFIX=rt['prefix'], WINEDEBUG='-all',
           DYLD_FALLBACK_LIBRARY_PATH=rt['dependency_lib'])
wine = [rt['wine'], str(lab / 'python32/sgi-protocol-probe.exe'), '-X', 'utf8']


def read_probe(script, extra, label):
    r = subprocess.run(wine + [str(lab / script)] + extra, env=env,
                       capture_output=True, text=True, timeout=40)
    if r.returncode:
        raise SystemExit('%s_failed rc=%d stderr=%s' % (label, r.returncode, r.stderr[:400]))
    return json.loads(r.stdout)


def summarize(row):
    return {k: row.get(k) for k in ('idx', 'id', 'name', 'state', 'w4', 'machine_name')}


hosts_all = read_probe('p26_find_host.py', [], 'p26')['hosts']
hosts = [h for h in hosts_all if h.get('host_name') == '丁满']
print(json.dumps({'all_hosts': hosts_all, 'dingman_count': len(hosts)},
                 ensure_ascii=False, indent=1))
if len(hosts) != 1:
    raise SystemExit('dingman_host_not_unique count=%d' % len(hosts))
host = hosts[0]
rows = read_probe('p32_app_rows_read.py', [str(host['pid'])], 'rows')
report = {'host': host, 'tables': []}
for t in rows['tables']:
    entry = {'hypothesis': t.get('table_hypothesis'),
             'row0_name': t['rows'][0].get('name'), 'row0_id': t['rows'][0].get('id'),
             'rows': [summarize(r) for r in t['rows']],
             'free_slots': sum(1 for r in t['rows']
                               if r.get('id') == 0 and r.get('state') == 0 and r.get('w4') == 0)}
    report['tables'].append(entry)
current = [t for t in report['tables']
           if t['row0_id'] == host['host_id'] and t['row0_name'] == '丁满'
           and t['hypothesis'] != 'P_pair_upper']
report['current_table_unique'] = len(current) == 1
report['current_free_slots'] = current[0]['free_slots'] if current else None
print(json.dumps(report, ensure_ascii=False, indent=1))
if not current or not current[0]['free_slots']:
    raise SystemExit('launch_would_fail_no_free_slot')
print('PREFLIGHT_OK')
