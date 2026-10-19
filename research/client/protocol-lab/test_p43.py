"""Offline tests for P43 (hardened pre-start D8 probe) and runner --child-script."""
import json
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def t_p43_probe_source_shape():
    src = (LAB/'p43_prestart_d8_probe.py').read_text()
    assert "'p43_prestart_d8_hardened'" in src
    assert 'disconnect_observed' in src
    assert 'stop_touching_native_after_disconnect' in src
    assert 'd8_prestart_send_return' in src
    assert 'P42Gate' in src and 'd8_prestart_authorized' in src
    assert 'alive_now is False' in src
    assert 'exit_rc' in src and 'end_rc' in src


@test
def t_p43_disconnect_guard_before_pump():
    src = (LAB/'p43_prestart_d8_probe.py').read_text()
    i_guard = src.index('stop_touching_native_after_disconnect')
    i_pump = src.index('receiver.pump()', i_guard)
    assert i_guard < i_pump


@test
def t_runner_child_script_arg():
    src = (LAB/'p42_prestart_d8_run.py').read_text()
    assert "'--child-script'" in src
    assert 'P2_CHILD_SCRIPT=args.child_script' in src
    assert 'dict.fromkeys(sources + (args.child_script,))' in src


@test
def t_p43_probe_prepared_only():
    r = subprocess.run([sys.executable, str(LAB/'p43_prestart_d8_probe.py')],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out['state'] == 'prepared_only' and out['d8'] is False


@test
def t_long_run_windows():
    import importlib.util
    spec = importlib.util.spec_from_file_location('p42_run_probe', LAB/'p42_prestart_d8_run.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.resolve_windows(None, None, True) == (82800, 86400)
    assert mod.resolve_windows(None, None, False) == (3600, 7200)
    assert mod.resolve_windows(7200, 10800, True) == (7200, 10800)
    assert mod.resolve_windows(7200, None, True) == (7200, 86400)
    assert mod.resolve_windows(None, 12000, False) == (3600, 12000)


@test
def t_p43_health_sample_shape():
    src = (LAB/'p43_prestart_d8_probe.py').read_text()
    assert "'--health-seconds'" in src
    assert "'health_sample'" in src
    assert 'observe_remaining' in src
    assert 'last_activity_age' in src
    assert '30 <= args.health_seconds <= 1800' in src


@test
def t_runner_post_exit_tail():
    src = (LAB/'p42_prestart_d8_run.py').read_text()
    assert "'--long-run'" in src
    assert "'post-exit-tail.json'" in src
    assert "'post-exit-watch.jsonl'" in src
    assert 'tail_seconds' in src
    assert "'--health-seconds', str(args.health_seconds)" in src
    assert "args.hold+240" in src


@test
def t_runner_child_script_dry():
    r = subprocess.run([sys.executable, str(LAB/'p42_prestart_d8_run.py'), '--launch',
                        '--child-script', 'p43_prestart_d8_probe.py'],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and 'new_room_user_approval_required' in r.stderr


@test
def t_p42_regression():
    r = subprocess.run([sys.executable, str(LAB/'test_p42.py')],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '10/10 passed' in r.stdout


def main():
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append((fn.__name__, repr(exc)))
        else:
            print('ok  ', fn.__name__)
    print('%d/%d passed' % (len(TESTS)-len(failed), len(TESTS)))
    if failed:
        for name, err in failed:
            print('FAIL', name, err)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
