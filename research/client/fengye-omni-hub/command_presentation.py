"""Player-facing command names and progress, separate from diagnostic records."""
from datetime import datetime

BUILD_CHOICES = ((7, '兵營'), (8, '馬房'), (9, '弓房'), (6, '陷阱'))
TRAIN_CHOICES = ((0, '步兵'), (1, '騎兵'), (2, '弓兵'))
STATUS = {
    'held': '等待前筆確認', 'pending': '已排隊', 'validating': '核對可否執行',
    'waiting_phase_exit': '等下一個內政回合', 'switching_slot': '準備下令',
    'arming': '準備下令', 'waiting_phase': '等內政回合執行',
    'awaiting_receipt': '正在下令', 'fired': '已下令，等待變化',
    'verifying': '等待實際變化', 'restoring': '正在完成下令',
    'completed': '已完成', 'cancelled': '已撤回', 'error': '未能執行',
    'send_failed': '下令失敗', 'unknown': '結果待確認',
    'restore_failed': '執行狀態待確認', 'waiting_effect': '等前筆訓練完成',
}
PROGRESS = {
    'held': '前一筆結果尚未確認；這筆還沒送出，可以撤回。',
    'pending': '已加入隊列，輪到這筆就會處理；尚可撤回。',
    'validating': '正在確認所屬勢力及位置；尚可撤回。',
    'waiting_phase_exit': '目前不是內政階段；等內政階段（phase 1）再切席發送。這筆還沒送出，可以撤回。',
    'switching_slot': '正在準備讓選定的勢力執行指令。',
    'arming': '正在準備這筆指令，請等候下令結果。',
    'waiting_phase': '已武裝；內政階段一到就會發送（通常數秒內）。',
    'awaiting_receipt': '正在下令，尚未確認遊戲中的變化。',
    'fired': '已下令，等待遊戲數值或地圖物件更新。',
    'verifying': '已下令，等待訓練值增加或新建物出現。',
    'restoring': '正在完成本批下令，接著繼續核對遊戲變化。',
    'completed': '已讀到這筆指令對應的實際變化。',
    'cancelled': '已撤回，這筆沒有送出。',
    'error': '這筆未能執行，沒有列為完成。',
    'send_failed': '下令未成功，沒有列為完成。',
    'unknown': '還不能確定是否生效；保留記錄，避免重複下令。',
    'restore_failed': '目前無法確認執行狀態，後續指令暫停。',
    'waiting_effect': '等前一筆同兵種訓練的數值更新；這筆還沒送出，可以撤回。',
}


def _name(value):
    text = str(value or '').strip()
    return text if text and not text.isdecimal() and text not in ('—', '城池', 'None') else None


def actor_text(job, snapshot=None):
    snapshot = snapshot or {}
    actor = job.get('actor', (job.get('params') or {}).get('actor'))
    label = _name(job.get('actor_label'))
    # Newly queued labels freeze the actual player/faction names at that time.
    if label and '・' in label:
        player_label, force_label = label.split('・', 1)
        if _name(player_label) and _name(force_label):
            return '%s・%s' % (player_label.strip(), force_label.strip())
    slots = snapshot.get('player_slots') or []
    forces = snapshot.get('forces') or []
    player = next((_name(s.get('nickname')) for s in slots if s.get('force_id') == actor), None)
    force = next((_name(f.get('name')) for f in forces if f.get('force_id') == actor), None)
    return '%s・%s' % (player or '未知玩家', force or '未知勢力')


def city_text(job, snapshot=None):
    name = _name(job.get('city_name'))
    if name:
        return name
    city_id = (job.get('params') or {}).get('city')
    return next((_name(c.get('name')) or '未知城池' for c in (snapshot or {}).get('cities', [])
                 if c.get('city_id') == city_id), '未知城池')


def action_text(job, snapshot=None):
    params = job.get('params') or {}
    if job.get('preset') == 'train':
        return '練兵 · %s' % dict(TRAIN_CHOICES).get(params.get('troop'), '未知兵種')
    if job.get('preset') == 'build':
        return '%s · %s (%s,%s)' % (dict(BUILD_CHOICES).get(params.get('build_type'), '建設'),
                                    city_text(job, snapshot), params.get('x', '未知'), params.get('y', '未知'))
    return '未知指令'


def progress_text(job, snapshot=None):
    effect = job.get('effect') or job.get('effect_check') or {}
    before, after = effect.get('before') or {}, effect.get('after') or {}
    status = job.get('status')
    text = PROGRESS.get(status, '狀態待確認。')
    if status == 'unknown' and job.get('stall_note'):
        # Explain a receipt timeout with the observed round state instead of
        # leaving the row at the generic "結果待確認".
        text = job['stall_note']
    if status in ('error', 'send_failed'):
        reason = str(job.get('error') or '') + ' ' + str(job.get('note') or '')
        for needles, explanation in (
            (('當局', '跨局', '局面身分'), '對局已變更或目前無法確認，請在目前對局重新下令。'),
            (('不屬於', '失去歸屬'), '這座城池已不屬於所選勢力，請重新選址。'),
            (('佔用', '已有物件', '可建', '已在佇列', '已排隊'), '這個格位已被佔用或無法建設，請另選綠框位置。'),
            (('階段', '等候回合'), '未能等到可執行的回合，這筆沒有完成。'),
            (('快照', '狀態讀取', '狀態不足', '完整的風夜'), '暫時讀不到足夠的遊戲資料，請等讀取恢復後再下令。'),
            (('保存', '執行記錄'), '未能保存這筆指令，請先檢查本機儲存空間。'),
            (('席位', '借用'), '暫時無法讓選定勢力執行，請等資料更新後再試。'),
        ):
            if any(needle in reason for needle in needles):
                text = explanation
                break
    if job.get('preset') == 'train':
        old, new = before.get('training_raw'), after.get('training_raw')
        if type(old) is int and type(new) is int:
            troop = dict(TRAIN_CHOICES).get((job.get('params') or {}).get('troop'), '此兵種')
            text = '%s訓練度 %d → %d' % (troop, old, new)
            text += '，已確認增加。' if effect.get('confirmed') is True else '，尚未確認完成。'
    elif job.get('preset') == 'build' and effect.get('confirmed') is True:
        params = job.get('params') or {}
        text = '%s (%s,%s) 已出現新的%s。' % (city_text(job, snapshot), params.get('x'), params.get('y'),
                    dict(BUILD_CHOICES).get(params.get('build_type'), '建物'))
    if effect.get('confirmed') is True:
        gold = (effect.get('evidence') or {}).get('gold_change') or {}
        if type(gold.get('before')) is int and type(gold.get('after')) is int:
            text += ' 金 %s → %s。' % (gold['before'], gold['after'])
    elif job.get('verification_exhausted'):
        text += ' 暫未讀到可確認的變化，保留這筆記錄。'
    return text


def job_detail(job, snapshot=None):
    lines = ['%s · %s · %s' % (actor_text(job, snapshot), action_text(job, snapshot),
                                STATUS.get(job.get('status'), '狀態待確認')),
             progress_text(job, snapshot)]
    if job.get('sender_label'):
        lines.append('送出：%s' % job['sender_label'])
    if job.get('eta_text'):
        lines.append('預計執行：%s' % job['eta_text'])
    # Diagnostics stay in the local audit journal; the timeline explains the
    # game action without exposing transport return codes or implementation.
    for event in (job.get('events') or [])[-8:]:
        if event.get('status') not in STATUS:
            continue
        try:
            stamp = datetime.fromtimestamp(event['at']).strftime('%H:%M:%S')
        except (ValueError, TypeError, KeyError, OSError, OverflowError):
            continue
        lines.append('%s　%s' % (stamp, STATUS[event['status']]))
    return '\n'.join(lines)
