"""One requested switch for timer extension, original-input x3 and WASD."""


class QuickAutomation:
    def __init__(self, timer, effects, pan, emit):
        self.timer = timer; self.effects = effects; self.pan = pan; self.emit = emit
        self.enabled = False

    def stop(self, note='三项辅助已关闭。'):
        self.enabled = False
        self.timer.set_enabled(False, True)
        self.pan.update(False)
        try:
            self.effects.set_enabled(False, True)
        except Exception as error:
            self.effects.enabled = False
            note += ' 自动×3恢复未确认：' + str(error)
            self.emit(dict(kind='auto_x3_restore_error', note=str(error), enabled=False,
                           hooks_may_remain=bool(self.effects.hooks)))
        self.emit(dict(kind='automation_status', enabled=False, note=note))

    def set_enabled(self, wanted, allowed):
        # 2026-10-22 使用者定案：只保留 WASD 視角（回合倒數／指令×3 全部移除）。
        if wanted is not True or allowed is not True:
            self.stop(); return
        self.enabled = True
        self.emit(dict(kind='automation_status', enabled=True,
                       note='辅助已开启：只启用 WASD 视角（回合倒数／指令×3 已移除）。'))

    def poll(self):
        if not self.enabled:
            self.pan.update(False); return
        self.pan.update(True)
