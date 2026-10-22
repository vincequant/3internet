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
        if wanted is not True or allowed is not True:
            self.stop(); return
        try:
            self.effects.set_enabled(True, True)
            self.timer.set_enabled(True, True)
            if not self.timer.enabled or not self.effects.enabled:
                raise ValueError('辅助未能全部启用，请查看状态')
        except Exception as error:
            self.stop('三项辅助未开启：' + str(error)); return
        self.enabled = True
        self.emit(dict(kind='automation_status', enabled=True,
                       note='三项辅助已开启：剩1秒把回合倒数调成所选秒数、游戏内指令×3、WASD移动视角。'))

    def poll(self):
        if not self.enabled:
            self.pan.update(False); return
        try:
            self.timer.poll()
            if not self.timer.enabled:
                raise ValueError('自动加时已停止')
            self.effects.poll()
            if not self.effects.enabled:
                raise ValueError('自动×3已停止')
            self.pan.update(True)
        except Exception as error:
            self.stop('三项辅助已停止：' + str(error))
