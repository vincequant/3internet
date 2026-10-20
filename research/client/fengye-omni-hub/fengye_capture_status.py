"""Freshness and observed-frame count for the actual shadow Collector stream."""
from datetime import datetime, timezone
from fengye_battle_panel import SHADOW_PREFIX, capture_time


class CaptureStatus:
    def __init__(self):
        self.game_key = None
        self.sample = None
        self.captured_at = None
        self.frames = 0
        self.failed = False

    def observe(self, payload):
        if not payload.get('ok') or payload.get('source_prefix') != SHADOW_PREFIX:
            return False
        state = payload.get('state') or {}
        when = capture_time(payload)
        if state.get('readonly') is not True or when is None:
            return False
        game = payload.get('game_key')
        sample = (state.get('snapshot_id'), when.isoformat())
        if game != self.game_key:
            self.frames, self.sample = 0, None
            self.captured_at = None
            self.game_key = game
        if self.captured_at and game == self.game_key and when < self.captured_at:
            return False
        changed = sample != self.sample
        if changed:
            self.frames += 1
        self.sample, self.captured_at = sample, when
        self.failed = False
        return changed

    def text(self, error=False, now=None, replay=False):
        prefix = '本機・風夜'
        if replay:
            return prefix + '・樣本回放'
        if self.captured_at is None:
            return prefix + '・等待開局資料（自動讀取）'
        age = ((now or datetime.now(timezone.utc))-self.captured_at).total_seconds()
        status = '採集暫時中斷，自動重試' if error or self.failed else '資料已過期，自動重試' if not -2 <= age <= 15 else '實時採集'
        return '%s・%s・本次讀取 %d 幀・%s' % (
            prefix, status, self.frames, self.captured_at.astimezone().strftime('%H:%M:%S'))
