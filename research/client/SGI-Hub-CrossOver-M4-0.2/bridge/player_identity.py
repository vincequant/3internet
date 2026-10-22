"""Explicit player attribution; numerical resemblance is only a suggestion.

Verified SANPK 3.5 player context is preferred. Manual fallbacks are ephemeral and
revoked on capture gaps, root/process changes, roster changes or clock rollback.
"""
from uuid import uuid4

FIELDS = ('gold', 'rice', 'troop_stock', 'armament_raw')


def candidates(doc):
    local = doc.get('current_local_projection') or {}
    if any(k not in local for k in FIELDS):
        return []
    return [f['force_id'] for f in doc['entities']['lords']
            if all(k in f and f[k] == local[k] for k in FIELDS)]


class PlayerIdentity:
    def __init__(self):
        self.context = None
        self.session = uuid4().hex
        self.force_id = None
        self.source = 'unknown'
        self.reason = '请对照游戏确认我方势力'
        self.clock = None
        self.live = False

    def reset(self, reason):
        self.session = uuid4().hex
        self.force_id = None
        self.source = 'unknown'
        self.reason = reason

    def observe(self, payload):
        doc = payload.get('state')
        live = bool(payload.get('fresh') and not payload.get('error') and doc)
        if not live:
            if self.live:
                self.reset('采集已中断，恢复后请重新确认我方')
            self.live = False
            return self.apply(payload)
        ident = doc.get('identity') or {}
        context = (ident.get('pid'), ident.get('path'), ident.get('creation_filetime'),
                   doc.get('core_address'),
                   tuple(sorted((f['force_id'], f.get('name'), f.get('ruler_general_id'))
                                for f in doc['entities']['lords'])))
        clock = doc.get('clock_candidates') or {}
        clock = (clock.get('year_u16'), clock.get('season_u16'))
        rollback = (self.clock and all(isinstance(x, int) for x in clock + self.clock)
                    and clock < self.clock)
        if context != self.context or rollback:
            self.reset('实例、地图或时间基线变化，请重新确认我方')
        self.context, self.clock, self.live = context, clock, True
        context = doc.get('player_context') or {}
        fid = context.get('force_id')
        automatic = (context.get('source') == 'game_player_context' and
                     context.get('status') == 'verified' and context.get('stable') is True and
                     type(fid) is int and sum(f['force_id'] == fid for f in doc['entities']['lords']) == 1)
        if automatic:
            if self.force_id != fid or self.source != 'game_player_context':
                self.reset('游戏玩家上下文已自动识别')
            self.force_id, self.source = fid, 'game_player_context'
            self.reason = '随每次采集重新读取游戏玩家上下文'
            return self.apply(payload)
        if self.source == 'game_player_context':
            self.reset('游戏玩家上下文暂不可用，等待重新识别')
        matches = candidates(doc)
        if self.force_id is not None and matches and self.force_id not in matches:
            self.reset('操作投影与已确认势力冲突，请重新确认')
        return self.apply(payload)

    def confirm(self, payload, session, force_id, source='user_confirmed'):
        if session != self.session or not self.live or not payload.get('fresh'):
            raise ValueError('采集会话已变化或过期，请等待实时数据后重选')
        doc = payload['state']
        ids = [f['force_id'] for f in doc['entities']['lords']]
        if force_id is not None and (type(force_id) is not int or ids.count(force_id) != 1):
            raise ValueError('势力不存在或标识不唯一')
        ctx = doc.get('player_context') or {}
        if ctx.get('status') == 'verified' and force_id is not None and force_id != ctx.get('force_id'):
            raise ValueError('与游戏当前玩家上下文冲突，不能改成正在查看的其他势力')
        matches = candidates(doc)
        if force_id is not None and matches and force_id not in matches:
            raise ValueError('该势力与当前操作投影冲突；请先核对游戏')
        if source not in ('user_confirmed', 'screenshot_verified'):
            raise ValueError('无效确认来源')
        if force_id != self.force_id:
            self.session = uuid4().hex
        self.force_id = force_id
        self.source = source if force_id is not None else 'unknown'
        self.reason = '仅本次连续采集有效；读档后请重新确认' if force_id is not None else '我方未确认'
        return self.apply(payload)

    def apply(self, payload):
        result = dict(payload)
        fid = self.force_id if self.live and payload.get('fresh') else None
        meta = {'force_id': fid, 'source': self.source if fid is not None else 'unknown',
                'status': 'confirmed' if fid is not None else 'unknown',
                'session_id': self.session, 'reason': self.reason,
                'candidate_force_ids': candidates(payload['state']) if payload.get('state') else [],
                'context_offset_verified': self.source == 'game_player_context',
                'same_address_reload_detection': 'player_context_rechecked_each_capture; identical_state_reload_not_observable'}
        result.update(player_force_id=fid, player_identity=meta,
                      semantic_verification='partial; military_fields_not_fully_GUI_verified')
        if payload.get('state'):
            doc = dict(payload['state'])
            local = dict(doc.get('current_local_projection') or {})
            local.update(player_force_id=fid, player_identity_source=meta['source'])
            force = next((f for f in doc['entities']['lords'] if f['force_id'] == fid), None)
            doc.update(player_force_id=fid, player_identity=meta,
                       current_local_projection=local,
                       core_projection_divergence={k: {'core': force.get(k), 'local_projection': local.get(k)}
                                                  for k in FIELDS if force and force.get(k) != local.get(k)})
            # The old producer had no reliable match/owner identity for history.
            history = doc.get('history') or {}
            if history.get('player_session_id') != self.session:
                doc.pop('history', None)
            result['state'] = doc
        return result
