"""One source-bound +60s attempt per original input stage.

SANPK 4a2c28 -> 49bccc ends exhausted civil input; 49dbd4 -> 49bccc
ends the exhausted military cursor. Preserve those normal completion paths:
never expire a timer, confirm a popup, or infer completion from lost focus.
"""
import hashlib
import json
import os
from pathlib import Path
import time

from quick_control_model import extension_remaining, extension_plan, extension_basis


class AutoTimer:
    def __init__(self,native,emit,root=None,prepare=None):
        self.n=native;self.emit=emit;self.enabled=False;self.scope=None
        self.last_poll=0;self.last_note=None;self.attempted=set();self.percent=100
        self.prepare=prepare;self.prepared=None;self.prepared_basis=None
        root=Path(root) if root is not None else Path(__file__).resolve().parents[1]
        binding=json.dumps({k:native.bound[k] for k in ('pid','created','image','core','build','source_id')},sort_keys=True)
        self.binding_sha=hashlib.sha256(binding.encode()).hexdigest()
        self.path=root/'quick-control-records'/('auto-time-'+self.binding_sha[:20]+'.jsonl')
        self.storage_error=None
        try:
            if self.path.exists():
                for line in self.path.read_text(encoding='utf8').splitlines():
                    row=json.loads(line)
                    if row['binding_sha256']!=self.binding_sha:raise ValueError('自动加时记录来源不匹配')
                    self.attempted.add(row['stage'])
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.storage_error=str(error)

    def status(self,note,**extra):
        key=(self.enabled,note)
        if key==self.last_note and not extra:return
        self.last_note=key
        self.emit(dict(kind='auto_time_status',enabled=self.enabled,note=note,**extra))

    def set_enabled(self,wanted,allowed):
        if wanted is True and not self.enabled:self.scope=None
        self.enabled=wanted is True and allowed is True
        if self.enabled and self.storage_error:
            self.enabled=False;self.status('自动加时记录不可用，未开启：'+self.storage_error);return
        self.status('自动加时已开启：先走正常倒数，剩最后1秒把回合倒数调成 %d 秒；指令完成按原版立即结束。'
                    % (self.target_ms() // 1000)
                    if self.enabled else '自动加时已关闭。')

    def set_percent(self, percent):
        try:
            percent = int(percent)
        except (TypeError, ValueError):
            percent = 100
        snapped = max(25, min(100, int(round(percent / 25.0) * 25)))
        if self.percent == snapped:
            return
        self.percent = snapped
        if self.enabled:
            self.last_note = None
            self.status('回合倒数目标改为 %d 秒。' % (self.target_ms() // 1000))

    def target_ms(self):
        # 25% = 30s, 50% = 60s, 75% = 90s, 100% = 120s.
        return 120000 * int(self.percent) // 100

    def stage_key(self,state):
        slot,force=state['player_slot_raw'],state['player_force_raw']
        if type(slot) is not int or not 0<=slot<8 or type(force) is not int or not 0<=force<32:
            raise ValueError('自动加时无法确认本机玩家势力')
        scope=(state['document'],state['view'],slot,force)
        if self.scope is not None and scope!=self.scope:raise ValueError('游戏对象／势力改变，自动加时已关闭')
        self.scope=scope
        clock=bytes.fromhex(state['round_clock'])
        if len(clock)!=18 or int.from_bytes(clock[12:14],'little',signed=True)!=state['phase']:
            raise ValueError('自动加时回合标识未确认')
        return hashlib.sha256(json.dumps((scope,clock.hex())).encode()).hexdigest()

    def poll(self):
        if not self.enabled:return
        now=time.monotonic()
        if now-self.last_poll<.05:return
        self.last_poll=now
        try:state=self.n.capture()
        except (ValueError,OSError) as error:
            self.status('自动加时保持开启，等待稳定的游戏状态：'+str(error));return
        try:stage=self.stage_key(state)
        except (ValueError,KeyError,TypeError) as error:
            self.enabled=False;self.status(str(error));return
        if state['mode']!=2 or state['ending'] or state['allowance']!=1:
            self.status('本阶段输入已结束，自动加时保持开启，等待下一阶段。');return
        if state['phase']==1 and state['orders_used']>=3:
            self.status('内政指令已用完，按原版立即结束；自动加时保持开启。');return
        if stage in self.attempted:
            self.status('本阶段已处理自动加时，不重复增加；指令完成按原版立即结束。');return
        try:remaining=extension_remaining(state,True,True,60000)
        except (ValueError,KeyError,TypeError) as error:
            self.status('自动加时保持开启：'+str(error));return
        basis=extension_basis(state)
        if basis!=self.prepared_basis:self.prepared=None;self.prepared_basis=None
        # 2026-10-22（使用者需求）：目標比剩餘小＝「縮短」→ 立即套用，不等最後 1 秒。
        #   目標比剩餘大＝「加時」→ 仍照原設計等最後 1 秒（避免全桌被拉長）。
        target = self.target_ms()
        if remaining > target:
            pass  # 縮短：立刻往下走
        elif remaining>5000:
            self.status('先走正常倒数，剩最后1秒才把回合倒数调成 %d 秒。' % (target // 1000));return
        if self.prepare and self.prepared is None:
            try:
                prepared=self.prepare(state)
                # HTTP/source preparation never writes. It can take longer
                # than the remaining time, so re-read before reserving/writing.
                fresh=self.n.capture()
                if extension_basis(fresh)!=basis or self.stage_key(fresh)!=stage:
                    self.status('回合已改变，等待下一次稳定倒数。');return
                remaining=extension_remaining(fresh,True,True,60000)
                state=fresh;self.prepared=prepared;self.prepared_basis=basis
            except (ValueError,OSError,KeyError,TypeError) as error:
                self.status('自动加时保持开启，等待来源核对：'+str(error));return
        if remaining>1000 and remaining <= target:
            self.status('先走正常倒数，剩最后1秒才把回合倒数调成 %d 秒。' % (target // 1000));return
        delta = self.target_ms() - remaining
        # 2026-10-22 安全閘：一次最多改 30 秒。避免「120 秒 → 45 秒」這種大幅寫入
        # （實測會外洩到主機、全桌一起變，且可能被重複套用出現 20 秒這種怪值）。
        if abs(delta) > 30000:
            self.status('本次需要改 %d 秒，超過單次上限 30 秒；不寫入（避免影響全桌）。' % (abs(delta)//1000)); return
        if delta == 0:
            self.attempted.add(stage)
            self.status('倒数已是 %d 秒，不改写。' % (self.target_ms() // 1000));return
        try:extension_plan(state,True,True,delta)
        except (ValueError,KeyError,TypeError) as error:
            self.status('自动加时保持开启：'+str(error));return
        # Reserve durably before any write. Reconnects and uncertain receipts
        # cannot add another minute to this same source/clock/force stage.
        self.attempted.add(stage)
        try:
            self.path.parent.mkdir(exist_ok=True)
            with self.path.open('a',encoding='utf8') as log:
                log.write(json.dumps(dict(binding_sha256=self.binding_sha,stage=stage))+'\n')
                log.flush();os.fsync(log.fileno())
            # 目标 = 120000 × percent/100；delta = 目标 - 剩余，写完后倒數等于目标。
            result=self.n.extend(state,True,True,self.prepared or self.emit,delta)
        except Exception as error:
            self.enabled=False;self.status('自动加时未完成，已停止；本阶段不重试：'+str(error));return
        if result.get('status')!='timer_field_verified':self.enabled=False
        self.status(result.get('note','自动加时结果未知，未重试'),result=result)
