"""回合跟隨判定：玩家資訊要在 120 秒內回來，240 秒沒有就判定掉隊。

使用者 2026-10-21 定案：「主要看 120 秒內有沒有返回玩家資訊，240 秒作終結。」
這裡只做純計算（不讀檔、不碰 Tk），由 Hub 的「指令」頁把風夜自己連線的
收包計數（`CommandService.wire_health()` 的 `received`）每秒餵進來。
"""
from __future__ import annotations

OK_SECONDS = 120.0
LOST_SECONDS = 240.0
RECOVER_NOTE_SECONDS = 60.0
SEASON_NAMES = '春夏秋冬'


def round_when(state):
    """把 {'year':200,'season':0} 寫成「200年春」；讀不到就回空字串（不補造）。"""
    state = state or {}
    year, season = state.get('year'), state.get('season')
    if isinstance(season, int) and 0 <= season < 4:
        if isinstance(year, int):
            return '%s年%s' % (year, SEASON_NAMES[season])
        return SEASON_NAMES[season]
    return ''


def round_shift(last, now):
    """最近一次收包時的回合 vs 現在的回合。"""
    last = (last or '').strip()
    now = (now or '').strip()
    if not last:
        return ('現在 %s' % now) if now else ''
    if not now:
        return '收包 %s' % last
    if last == now:
        return '收包 %s（現在相同）' % last
    return '收包 %s → 現在 %s' % (last, now)


def sync_phrase(sync):
    """把 sync_check() 的結果寫成一句；沒有資料就回空字串。"""
    data = sync or {}
    if data.get('ok') is True:
        return '與玩家端同步'
    if data.get('ok') is False:
        when = round_when(data.get('reference'))
        lag = data.get('lag_seasons')
        if when and isinstance(lag, int):
            return '玩家端已到 %s（風夜落後 %d 季）' % (when, lag)
        if when:
            return '玩家端已到 %s（風夜落後）' % when
        return '風夜落後玩家端'
    return ''


class TurnFollower:
    """把「received 有沒有增加」換成 ok／warn／lost 三態與一句人話。"""

    def __init__(self, ok_seconds=OK_SECONDS, lost_seconds=LOST_SECONDS):
        self.ok_seconds = float(ok_seconds)
        self.lost_seconds = float(lost_seconds)
        self.reset()

    def reset(self):
        self.run = None
        self.received = None
        self.last_at = None
        self.started_at = None
        self.connected = None
        self.recovered_at = None

    # ------------------------------------------------------------ 觀測
    def observe(self, now, received=None, run=None, connected=None):
        """餵一次觀測，回傳事件：'start'／'data'／'recovered'／None。

        `received` 是風夜自己連線的累計收包數；只要它變大就代表玩家資訊回來了。
        `run` 換了（新連線／新局）就重新計時，避免拿上一局的時間戳判這一局。
        """
        if run is not None and self.run is not None and run != self.run:
            self.reset()
        if run is not None:
            self.run = run
        if self.started_at is None:
            self.started_at = now
        if connected is not None:
            self.connected = bool(connected)
        if not isinstance(received, int):
            return None
        if self.received is None:
            self.received = received
            # 累計 0 筆代表「還沒收到任何玩家資訊」，不能算成剛剛有資料；
            # 已經有流量（>0）則以第一次觀測時間當時鐘起點（封包到達時間讀不到）。
            self.last_at = now if received > 0 else None
            return 'start'
        if received > self.received:
            previous = self.state(now)
            self.received = received
            self.last_at = now
            self.recovered_at = now if previous == 'lost' else None
            return 'recovered' if previous == 'lost' else 'data'
        self.received = received
        return None

    # ------------------------------------------------------------ 判定
    def silence(self, now):
        if self.last_at is None:
            return None
        return max(0.0, float(now) - self.last_at)

    def state(self, now):
        if self.received is None or self.last_at is None:
            return 'idle'
        silent = self.silence(now)
        if silent >= self.lost_seconds:
            return 'lost'
        if silent >= self.ok_seconds:
            return 'warn'
        return 'ok'

    def describe(self, now, context=''):
        """回傳 (state, text)。context 例如「200年春・內政」，接在句尾。"""
        state = self.state(now)
        silent = self.silence(now)
        tail = ('（%s）' % context) if context else ''
        if state == 'idle':
            if self.connected is False:
                return state, '等待風夜連線；連上後開始計時'
            if self.received == 0:
                return state, '等待玩家資訊（風夜還沒收到任何資料）'
            return state, '等待玩家資訊（還沒讀到收包計數）'
        if state == 'ok':
            head = '✓ 剛剛收到玩家資訊' if silent < 1 else '✓ %.0f 秒前收到玩家資訊' % silent
            if self.recovered_at is not None and now - self.recovered_at <= RECOVER_NOTE_SECONDS:
                head += '（先前中斷過，已恢復）'
            return state, head + tail
        if state == 'warn':
            return state, '⚠ 已 %.0f 秒沒收到玩家資訊（%.0f 秒判定掉隊）%s' % (
                silent, self.lost_seconds, tail)
        return state, '✗ 已 %.0f 秒沒收到玩家資訊 → 判定掉隊；有新資訊會自動恢復%s' % (
            silent, tail)
