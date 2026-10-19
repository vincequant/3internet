#!/usr/bin/env python3
"""One-command per-element UI toggle, with process-bound state and a lock.

The normal launch/arming scripts never call this. 'check' and 'plan' do not
write target memory. B is a native, targeted-receipt feature, not a fake switch.
"""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p52_shadow_ui import SITES
from p53_hidden_draw_build import GROUPS

ELEMENTS = tuple(SITES)+tuple(GROUPS)


def mode_for(element):
    if element in SITES:
        return 'ui'
    if element in GROUPS:
        return 'hidden-ui'
    raise ValueError('unknown optional UI element')


def desired_action(action, status):
    if status not in ('enabled', 'sealed_or_original'):
        raise ValueError('unexpected entry bytes; preserve evidence before recovery')
    if action == 'toggle':
        return 'revert' if status == 'enabled' else 'install'
    return {'on': 'install', 'off': 'revert', 'plan': 'plan'}[action]


def invoke(mode, action, state, pid, creation, element=None):
    import p53_ui_inject
    argv = ['p53_ui_inject.py', '--mode', mode, '--ui-action', action,
            '--state', str(state), '--expected-pid', str(pid), '--expected-creation', str(creation)]
    if element:
        argv += ['--ui-element', element]
    old = sys.argv; output = io.StringIO()
    try:
        sys.argv = argv
        with redirect_stdout(output):
            p53_ui_inject.main()
    finally:
        sys.argv = old
    return json.loads(output.getvalue())


class Control:
    def __init__(self, directory):
        from p51_shadow_inject import find_process, process_creation
        if Path(os.environ.get('WINEPREFIX', '').rstrip('/\\')).name != 'prefix-fengye-shadow':
            raise ValueError('explicit prefix-fengye-shadow required')
        targets = find_process('SANPK.exe')
        if len(targets) != 1:
            raise ValueError('need exactly one shadow SANPK process')
        self.pid = targets[0][0]; self.creation = process_creation(self.pid)
        if not self.creation:
            raise ValueError('process creation time unavailable')
        self.root = Path(directory)/('%s-%s' % (self.pid, self.creation))
        self.root.mkdir(parents=True, exist_ok=True)
        self.states = {mode: self.root/(mode+'.json') for mode in ('ui', 'hidden-ui')}

    def check(self):
        return {mode: invoke(mode, 'check', path, self.pid, self.creation)
                for mode, path in self.states.items()}

    def change(self, action, element):
        mode = mode_for(element); lock = self.root/'switch.lock'
        fd = os.open(str(lock), os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(dict(controller_pid=os.getpid(), target_pid=self.pid,
                               creation=self.creation, wall=time.time()), stream)
            before = invoke(mode, 'check', self.states[mode], self.pid, self.creation)
            status = next(row['status'] for row in before['elements'] if row['element'] == element)
            selected = desired_action(action, status)
            result = invoke(mode, selected, self.states[mode], self.pid, self.creation, element)
            receipt = dict(schema='p53-ui-switch-receipt-1', wall=time.time(),
                           pid=self.pid, creation=self.creation, element=element,
                           requested_action=action, actual_action=selected,
                           before=before, result=result, live_acceptance=False)
            with (self.root/'switches.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(receipt, ensure_ascii=False)+'\n')
            return receipt
        finally:
            lock.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--action', choices=('list', 'check', 'on', 'off', 'toggle', 'plan', 'menu'), default='menu')
    ap.add_argument('--element', choices=ELEMENTS)
    ap.add_argument('--state-dir', default=str(Path(__file__).resolve().parent.parent/'logs'/'ui-switches'))
    args = ap.parse_args()
    if args.action == 'list':
        print(json.dumps(dict(elements=ELEMENTS, B='native targeted receipt only; no optional patch'), ensure_ascii=False)); return
    try:
        control = Control(args.state_dir)
    except (ValueError, OSError) as error:
        print(json.dumps(dict(status='preflight_unavailable', message=str(error),
                              activation=False, target_memory_written=False), ensure_ascii=False))
        raise SystemExit(2)
    if args.action == 'check':
        print(json.dumps(control.check(), ensure_ascii=False)); return
    if args.action != 'menu':
        if not args.element:
            raise SystemExit('choose exactly one --element')
        print(json.dumps(control.change(args.action, args.element), ensure_ascii=False)); return
    while True:
        state = control.check()
        statuses = {row['element']: row['status'] for part in state.values() for row in part['elements']}
        print('\n影子 UI · PID %s / %s · 每次仅切一个元素' % (control.pid, control.creation))
        for index, name in enumerate(ELEMENTS, 1):
            print('%2d  [%s] %s' % (index, statuses[name], name))
        print('B：原生已收到聊天；定向私聊未投递时不补造。D：另启只读查阅窗口。')
        choice = input('输入编号切换；p 编号只看计划；q 退出：').strip()
        if choice.lower() == 'q': return
        try:
            plan_only = choice.startswith('p ')
            index = int(choice[2:] if plan_only else choice)-1
            if not 0 <= index < len(ELEMENTS): raise ValueError('编号超出范围')
            print(json.dumps(control.change('plan' if plan_only else 'toggle', ELEMENTS[index]), ensure_ascii=False))
        except (ValueError, OSError, SystemExit) as error:
            print('未完成：'+str(error))


if __name__ == '__main__':
    main()
