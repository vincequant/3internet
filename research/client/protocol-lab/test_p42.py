"""Offline tests for the P42 pre-start D8 components (no live calls, no game)."""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))

from p42_wire import P42Gate, d8_prestart_authorized, username_authorized42  # noqa: E402
from p33_wire import own_sync_withdrawal  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def receipt(**kw):
    base = {'contract': 'P42', 'source': 'p42_derived_authorization',
            'enable_d8_prestart': True, 'own_id': 100, 'host_id': 200,
            'collector_log': 'Z:\\x\\p42_live.jsonl', 'observed_wall': time.time()}
    base.update(kw)
    return base


@test
def t_username_allowlist():
    assert username_authorized42('风夜') and username_authorized42('小白')
    assert not username_authorized42('风云') and not username_authorized42('')
    assert username_authorized42(' ', True) and not username_authorized42(' ')


@test
def t_body_vector():
    assert own_sync_withdrawal(8) == bytes.fromhex('0000000800000008')
    assert (own_sync_withdrawal(0x0A99597A)
            == bytes.fromhex('00000008') + bytes.fromhex('0a99597a'))


@test
def t_receipt_accepts():
    base = receipt()
    now = time.time()
    assert d8_prestart_authorized(base, 100, 200, 'Z:\\x\\p42_live.jsonl', now)


@test
def t_receipt_rejections():
    log = 'Z:\\x\\p42_live.jsonl'
    assert not d8_prestart_authorized(None, 100, 200, log, time.time())
    for kwargs, owns in (
            ({'contract': 'P34'}, (100, 200, log)),
            ({'source': 'p34_derived_authorization'}, (100, 200, log)),
            ({'enable_d8_prestart': False}, (100, 200, log)),
            ({'own_id': 101}, (100, 200, log)),
            ({'host_id': 201}, (100, 200, log)),
            ({'collector_log': 'Z:\\y\\x'}, (100, 200, log)),
            ({'observed_wall': time.time()-601}, (100, 200, log))):
        r = receipt(**kwargs)
        assert not d8_prestart_authorized(r, owns[0], owns[1], owns[2], time.time()), kwargs
    r = receipt(observed_wall=time.time()+5)
    assert not d8_prestart_authorized(r, 100, 200, log, time.time())


@test
def t_gate_once_only():
    gate = P42Gate()
    assert not gate.attempted
    gate.attempt()
    assert gate.attempted and not gate.sent and gate.raw_rc is None
    try:
        gate.attempt()
        raise AssertionError('second attempt allowed')
    except ValueError:
        pass


@test
def t_probe_source_shape():
    src = (LAB/'p42_prestart_d8_probe.py').read_text()
    assert "'p42_prestart_d8_passive'" in src
    assert 'd8_prestart_send_enter' in src and 'd8_prestart_send_return' in src
    assert 'not args.d8_pre_start and not fake.reserved' in src
    assert 'username_authorized42' in src
    assert 'd8_prestart_gate.attempt()' in src
    assert "'--d8-pre-start'" in src and "'--p42-authorization-file'" in src


@test
def t_runner_prepared_only():
    r = subprocess.run([sys.executable, str(LAB/'p42_prestart_d8_run.py')],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out['state'] == 'prepared_only' and out['d8_prestart'] is False


@test
def t_runner_refuses_without_consent():
    r = subprocess.run([sys.executable, str(LAB/'p42_prestart_d8_run.py'), '--launch'],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and 'new_room_user_approval_required' in r.stderr


@test
def t_runner_refuses_bad_consent():
    with tempfile.TemporaryDirectory() as tmp:
        for name, value in (
                ('stale.json', {'contract': 'P42', 'phase3_confirmed': True,
                                'new_room_confirmed': True, 'user_room_report': '已建房',
                                'confirmed_wall': time.time()-601}),
                ('wrong_contract.json', {'contract': 'P35', 'phase3_confirmed': True,
                                         'new_room_confirmed': True, 'user_room_report': '已建房',
                                         'confirmed_wall': time.time()}),
                ('no_room.json', {'contract': 'P42', 'phase3_confirmed': True,
                                  'new_room_confirmed': False, 'user_room_report': '已建房',
                                  'confirmed_wall': time.time()})):
            p = Path(tmp)/name
            p.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            r = subprocess.run([sys.executable, str(LAB/'p42_prestart_d8_run.py'),
                                '--launch', '--live-authorization', str(p)],
                               capture_output=True, text=True, timeout=60)
            assert r.returncode != 0, name
            assert 'fresh_explicit_new_room_approval_required' in r.stderr, (name, r.stderr)


@test
def t_audit_of_sequence_docs():
    src = (LAB/'p42_prestart_d8_probe.py').read_text()
    assert 'No cmd1, no cmd9, no StartSync/EndSync' in src
    runner = (LAB/'p42_prestart_d8_run.py').read_text()
    assert "'cmd1_max_calls': 0" in runner and "'d8_max_calls': 1" in runner


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
