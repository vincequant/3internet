"""Player wording for system observations. Raw records remain in their source files.

Missing evidence remains unknown. A successful helper call is never presented
as proof that the host accepted an action or that a game started successfully.
"""
import re
import time


TECHNICAL = re.compile(
    r'\b(?:rc|stderr|stdout|traceback|exception|winerror|cmd\d*|D8|SOP|'
    r'GBK|DLL|ACK|PID|JSON|SHA\d*|OpenSession|ExitSession|SANPK|SANGUO|'
    r'helper|keeper|slotkeep|run[_-]|prefix|wineserver|seq\d*)\b|'
    r'0x[0-9a-f]+|[{}]|(?:/Users/|[A-Z]:\\)|'
    r'封包|探針|补丁|補丁|代理待命|上行抑制|原生同步|席位|回執|会话|會話|'
    r'\b[a-zA-Z]+_[a-zA-Z_]+\b', re.I)


def plain_error(value, fallback='這次操作未完成。請先更新狀態，再決定下一步。'):
    text = str(value or '')
    low = text.lower()
    if any(x in low for x in ('timeout', 'timed out', '超時', '无法连接', '無法連接', 'connection refused', 'ssh')):
        return '暫時連不到風夜所在的電腦。請確認那台電腦已連上網路，再更新狀態。'
    if any(x in text for x in ('已经登录', '已登入', '已登錄')):
        return '這個帳號可能已在其他視窗登入。請先查看現有遊戲，不要重複登入。'
    if any(x in low for x in ('gbk', '字元', '字符', 'unicode')):
        return '文字中有遊戲無法顯示的字，請改用常見中文字、英文或數字。'
    if any(x in text for x in ('暱稱', '昵称')):
        return '請填寫進房暱稱；不要留空，名稱也不要太長。'
    if '120' in text or '字數' in text or '字数' in text:
        return '訊息最多可輸入 120 字。'
    if any(x in low for x in ('not_ready', 'no sanpk', '遊戲未開', '游戏未开', '尚未開局')):
        return '還沒取得可操作的遊戲資料。請先開啟遊戲並進入對局，再更新狀態。'
    if any(x in low for x in ('permission', 'denied', '權限', '权限')):
        return '目前無法讀取所需資料。請先確認遊戲與情報台已正常開啟。'
    # Never use unknown runtime text as player copy.
    return fallback


def room_fresh(state, now=None):
    now = time.time() if now is None else now
    if not state.get('fresh'):
        return False
    stamp = state.get('observed_at')
    return bool(state.get('external') or
                isinstance(stamp, (int, float)) and 0 <= now - stamp <= 20)


def room_summary(state, now=None):
    """Return current progress and a concrete next step, ignoring old success flags."""
    if not room_fresh(state, now):
        if state.get('phase') == 'stopped':
            return '風夜目前未連線。', '先請房主建好房間，再按「讓風夜進房」。'
        return '風夜狀態尚未確認。', '請按「查看風夜狀態」，先不要重複進房。'
    if not state.get('connected'):
        return '風夜還沒進入房間。', '請選擇房間，或使用「讓風夜進房」。'
    if not state.get('ghost_withdrawn'):
        return '風夜已進房，正在準備。', '先不要按遊戲的「開始」，等準備完成。'
    if (state.get('d8') or {}).get('fast') or state.get('exit_seen_wall'):
        return '風夜已藏好，正在查看本局情況。', '現在可以在遊戲中按「開始」。'
    return '風夜還在等房主確認。', '等房間名單上的風夜名字消失後，再按「開始」。'


def room_result(result):
    op = result.get('op')
    action = {'start': '登入', 'join': '進房', 'register': '報到', 'd8': '藏身',
              'leave': '離開房間', 'stop': '下線', 'search': '更新房間',
              'chat': '發言'}.get(op, '這次操作')
    status = result.get('status')
    if status in ('sent', 'pending'):
        return action + '已送出，還在等待結果。請稍候，不用重複點擊。'
    if status == 'started':
        return '風夜正在登入。登入完成後會更新房間。'
    if status == 'completed':
        if op == 'd8':
            return '藏身操作已執行；等房主確認後，才可以開始遊戲。'
        if op == 'join':
            return '進房操作已完成，請看上方是否仍在準備。'
        return action + '操作已完成。'
    if status in ('unknown', 'uncertain'):
        return action + '的結果還沒確認。請先更新狀態，不要重複操作。'
    return plain_error(result.get('error') or result.get('detail'))


def operation_result(label, result):
    status = result.get('status')
    if status in ('error', 'failed', 'unknown', 'aborted') or result.get('rc') not in (None, 0):
        return label + '\n' + plain_error(result.get('error') or result.get('stderr'))
    if status == 'already_online':
        return '遊戲已開啟。請切回現有遊戲，不用重新登入。'
    if status == 'started':
        return '正在進入遊戲。首次開啟約需十幾秒，請稍候。'
    return label + '\n已執行這項操作；請更新狀態，確認目前情況。'


def local_state(result):
    states = {
        'not_started': ('風雲尚未開啟', '按「進入遊戲」，就可以開始。'),
        'logging_in': ('風雲正在登入', '首次開啟約需十幾秒，請稍候，不用重複點擊。'),
        'holding': ('風雲已連上伺服器', '不用重複登入。請查看遊戲視窗目前停在哪個畫面。'),
        'already_logged': ('風雲可能已在其他視窗登入', '請先查看現有遊戲，不要重複登入。'),
        'aborted': ('這次登入沒有完成', '請先確認目前遊戲狀態，再重新嘗試。'),
        'stopping': ('正在結束風雲遊戲', '請稍候，先不要重複點擊。'),
        'exited': ('風雲已下線', '需要遊玩時，再按「進入遊戲」。'),
        'running_unknown': ('風雲遊戲已開啟', '是否已進入房間，請以遊戲畫面為準。'),
    }
    title, hint = states.get(result.get('state'), ('正在確認風雲狀態', '請稍候再按「更新狀態」。'))
    title = title.replace('風雲', result.get('display_name') or '風雲')
    rooms = result.get('rooms') or []
    if rooms and result.get('state') == 'holding':
        hint += '\n目前找到的房間：' + '、'.join(str(x) for x in rooms)
    return title, hint


def control_event(event):
    kind = event.get('ev') or event.get('event')
    if event.get('rc') not in (None, 0):
        return '這次操作沒有確認完成。請更新狀態，不要重複送出。'
    if kind in ('control_done', 'control_executed', 'chat_sent', 'stop_done'):
        op = event.get('op')
        if kind == 'chat_sent' or op == 'chat':
            return '已收到發言操作的結果；是否出現在聊天室，請看聊天記錄。'
        if kind == 'stop_done' or op == 'stop':
            return '已收到下線操作的結果，請更新狀態確認。'
        return '已收到操作結果。'
    if kind in ('control_received', 'control_pending', 'control_sent'):
        return '操作已送出，正在等結果。'
    if kind in ('control_error', 'control_rejected') or event.get('reason'):
        return plain_error(event.get('reason'))
    return '收到一則操作記錄，目前還無法確認結果。'


def force_choices(payload, seats):
    choices = {}
    for i in range(8):
        fid = (payload.get('slot_forces') or {}).get(str(i))
        if fid in (-1, '-1', None, '?'):
            continue
        name, faction = seats.get(i, (None, None))
        if not name or name in ('電腦', '电脑', '空席', '未命名'):
            continue
        choices[i] = str(name) + ('・' + str(faction) if faction and faction != '—' else '')
    return choices


def force_summary(payload, seats):
    choices = force_choices(payload, seats)
    def who(index):
        try:
            return choices.get(int(index))
        except (TypeError, ValueError):
            return None
    current = who(payload.get('slot_now'))
    title = '目前對應玩家：' + (current or '尚未確認')
    if payload.get('action') == 'written':
        if payload.get('now') == payload.get('requested') and who(payload.get('now')):
            title = '已切換為：' + who(payload['now'])
        else:
            title = '已執行切換，但結果還沒確認。請更新狀態。'
    elif payload.get('action') == 'restored':
        title = '已執行還原。目前對應玩家：' + (current or '尚未確認')
    if not choices:
        return title + '\n還沒取得可切換的玩家名單。開局後請按「更新可選玩家」。'
    return title + '\n可選玩家：' + '、'.join(choices.values())


def lab_result(label, result):
    if result.get('rc') != 0:
        return label + '\n' + plain_error(result.get('stderr'))
    if '進房' in label:
        return '進房準備已執行。\n請查看上方準備狀態；確認可以開始後，再按遊戲的「開始」。'
    if '下線' in label or '強制結束' in label:
        return '已執行下線操作。請按「查看風夜狀態」，確認是否已離開。'
    return '已取得風夜檢查結果。\n目前是否在房間及是否準備完成，請以上方最新狀態為準。'
