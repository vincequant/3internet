"""Ordinary training using our officer's politics times 3; no target-level rules.

Only the native training command operand changes. No target-level settlement
rules, general attributes, inventory, caps, fees or recruitment are changed.
Use arm() with a fresh bound game, then invoke training in the original UI.
"""
import struct
import time
from quick_effects import Effects, TRAINING, TOKENS, trampoline
from quick_control_model import TRAINING_POLITICS_FACTOR, require_menu, training_operand


class PlainTraining(Effects):
    uses_training_targets = False

    def arm(self, action, politics=300):
        limit = 255 * TRAINING_POLITICS_FACTOR
        if action not in TRAINING or type(politics) is not int or not 1 <= politics <= limit:
            raise ValueError('训练政治须为所属将政治的3倍，且在1到%d之间' % limit)
        self.politics = politics
        state = self.n.capture()
        if self.values(state)['armaments'][TRAINING[action]] >= 300:
            raise ValueError('训练已满，实验不绕过原版满值限制')
        self.install(action, state)
        self.emit(dict(kind='plain_training_armed', action=action, politics_operand=politics,
                       target_level_rules=False, game_order_sent=False,
                       note='请在游戏原版界面提交本军种训练；费用／次数／结算不变。'))

    def ensure_rules(self, state):
        if self.rule_hooks or self.pending:
            raise ValueError('普通参数实验不得与满值训练补丁混用')

    def input_trampoline(self, base, marker, view, document, action, _fixture_delta=0):
        code, hooks = trampoline(base, marker, view, document, action, _fixture_delta)
        if action == 'alms':
            return code, hooks
        old = b'\xb8' + struct.pack('<i', TOKENS[action])
        if code.count(old) != 1:
            raise ValueError('训练参数入口不唯一')
        code = code.replace(old, b'\xb8' + struct.pack('<i', self.politics))
        if action == 'bow':
            # The historical bow correction bypassed the full-level gate.
            # This ordinary parameter experiment must retain the native cap.
            hooks.pop(0x4a39e2+_fixture_delta)
            code = code[:0x400]
        return code, hooks

    def execute(self, action, enabled, allow_write, intent, hotkey=False):
        if action == 'alms':
            return super().execute(action, enabled, allow_write, intent, hotkey)
        if action not in TRAINING or not enabled or not allow_write:
            raise ValueError('所属将政治训练尚未启用')
        if hotkey and self.n.owner(self.n.u.GetForegroundWindow()) != self.n.bound['pid']:
            return dict(status='ignored', note='快捷键仅在游戏置前时生效')
        if time.monotonic()-self.n.last_input < .35:
            raise ValueError('操作太快，请稍候')
        require_menu(self.n.capture(), action, enabled)
        row = current_training_operand()
        self.arm(action, row['operand'])
        try:
            result = self.n.execute(action, enabled, allow_write, intent, hotkey)
        except Exception:
            self.restore(); self.active=None; self.n.effects_pending=False
            raise
        result['note'] = '已打开原版训练确认；%s 政治%d×3＝%d，原版费用／次数／训练上限300。' % (
            row['name'], row['politics'], row['operand'])
        result['politics_operand'] = row['operand']
        result['trainer'] = row['name']
        result['trainer_politics'] = row['politics']
        result['target_level_rules'] = False
        return result


def current_training_operand():
    import json
    import urllib.request
    with urllib.request.urlopen('http://127.0.0.1:8769/api/state', timeout=8) as response:
        payload = json.load(response)
    return training_operand(payload)
