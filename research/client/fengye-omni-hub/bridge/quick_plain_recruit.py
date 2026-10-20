"""One native city recruit order. No filtering, probability hooks or guarantees."""
import time
from quick_recruit import Recruit, SITES


class PlainRecruit(Recruit):
    def __init__(self,native,emit):
        self.n=native;self.emit=emit;self.pending={};self.last_poll=0

    def restore(self):
        # This class never installs hooks, including on shutdown.
        pass

    def original_rules(self):
        if any(self.n.read(a,len(b))!=b for a,b in SITES.items()):
            raise ValueError('招揽判定仍被其他工具修改，请先关闭旧面板；未提交普通招揽')

    def submit_ordinary(self,row,enabled,open_menu):
        if not enabled:raise ValueError('快捷指令未启用')
        city=row['city_id']
        if city in self.pending:raise ValueError('该城本回合已提交招揽，请先结算')
        self.original_rules()
        self.target(row['id'],city)  # typed target belongs to this current pool
        before=self.n.capture();clock=self.n.read(self.n.bound['core']+0x4cc,18)
        result=open_menu()
        if result.get('status')!='dialog_observed':raise ValueError('未核准录用窗口，未选城；不重发')
        opened=self.n.capture();hwnd,point=self.city_point(opened,city)
        self.point(hwnd,*point,'ordinary_recruit_city_click')
        for _ in range(100):
            time.sleep(.1);state=self.n.capture()
            if state['confirmation_typed']:
                if not state['recruit_dialog'] or self.n.number(state['recruit_dialog']+0x208)!=city:
                    raise ValueError('费用确认的城市改变，未确认')
                yes=self.yes_point(state);fresh=self.n.capture()
                if fresh['recruit_dialog']!=state['recruit_dialog'] or not fresh['confirmation_typed'] or self.yes_point(fresh)!=yes:
                    raise ValueError('费用确认已改变，未确认')
                self.original_rules()
                self.point(fresh['hwnd'],*yes,'ordinary_recruit_fee_yes')
                break
        else:raise ValueError('选城结果未知；未重发，请检查游戏窗口')
        for _ in range(100):
            time.sleep(.1);after=self.n.capture()
            if after['orders_used']==before['orders_used']+1 and not after['modal'] and not after['recruit_dialog']:
                self.original_rules()
                self.pending[city]=dict(row,clock=clock.hex())
                self.emit(dict(kind='ordinary_recruit_queued',city_id=city,predicted=row,after=after,
                               native_rules_original=True,target_guaranteed=False))
                return dict(status='ordinary_recruit_queued',after=after,
                            note=f"{row['city']}普通招揽已入队；预计{row['name']}，实际录用由原版结算。",recruitment_succeeded=None)
        raise ValueError('确认结果未知；未重发，请检查原版指令次数')

    def poll(self):
        if not self.pending or time.monotonic()-self.last_poll<.5:return
        self.last_poll=time.monotonic();state=self.n.capture()
        clock=self.n.read(self.n.bound['core']+0x4cc,18).hex()
        if state['phase']!=1 or any(row['clock']!=clock for row in self.pending.values()):
            finished=list(self.pending.values());self.pending.clear()
            self.emit(dict(kind='ordinary_recruit_round_finished',predictions=finished,
                           note='招揽回合已推进；请以两端将领归属核验实际结果。'))
