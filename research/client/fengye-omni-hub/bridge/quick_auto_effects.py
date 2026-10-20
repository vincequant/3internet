"""Explicit toggle for original-UI training/alms x3, scoped to one local game.

Two input hooks only. No target-level, cost, cap, settlement or recruitment
patches. Native commands are selected/confirmed by the player; no input sent.
"""
import struct
import time

from quick_effects import SITES
from quick_recruit import Recruit, jump
from quick_control_model import require_menu

AUTO_SITES = {a:SITES[a] for a in (0x4a3c88, 0x4a482c)}
ACTIONS = ('infantry', 'cavalry', 'bow', 'alms')


def auto_trampoline(base, marker, view, document, core, slot, force, alms=False, _fixture_delta=0):
    if (any(type(v) is not int or not 0x10000 <= v < 0x7fff0000 for v in (base,marker,view,document,core))
            or type(slot) is not int or not 0 <= slot < 8 or type(force) is not int or not 0 <= force < 32):
        raise ValueError('自动×3来源身份异常')
    site = 0x4a482c if alms else 0x4a3c88
    body=bytearray(b'\x9c');fixups=[];labels={}
    def branch(op,label):
        body.extend(op);fixups.append((len(body),label));body.extend(b'\0'*4)
    def guard(data,op=b'\x0f\x85'):
        body.extend(data);branch(op,'original')
    guard(b'\x81\xff'+struct.pack('<I',view))
    guard(b'\x81\x7f\x3c'+struct.pack('<I',document))
    for address,value in ((document+0x68,2),(view+0x8a6,0),(view+0x896,1),
                          (0x53bb30+_fixture_delta,core),(core+0x6c0,slot),(core+slot*0x87+0x4a,force)):
        guard(b'\x81\x3d'+struct.pack('<II',address,value))
    guard(b'\x66\x83\x3d'+struct.pack('<I',document+0xdea)+b'\x01')
    if alms:
        guard(b'\x83\xfa\x04',b'\x0f\x87')  # unsigned native random remainder 0..4
        body.extend(b'\x89\x15'+struct.pack('<I',marker+3*12+4))
        body.extend(bytes.fromhex('83 c2 05 8d 14 52 83 ea 05'))
        body.extend(b'\x89\x15'+struct.pack('<I',marker+3*12+8))
        body.extend(b'\xff\x05'+struct.pack('<I',marker+3*12))
    else:
        guard(b'\x83\xf8\x01',b'\x0f\x8c')
        guard(b'\x3d\xff\x00\x00\x00',b'\x0f\x8f')
        for index in range(3):
            body.extend(b'\x83\x7d\x08'+bytes([index]));branch(b'\x0f\x84','kind'+str(index))
        branch(b'\xe9','original')
        for index in range(3):
            labels['kind'+str(index)]=len(body);address=marker+index*12
            body.extend(b'\xa3'+struct.pack('<I',address+4))
            body.extend(bytes.fromhex('8d 04 40'))  # eax = original politics * 3
            body.extend(b'\xa3'+struct.pack('<I',address+8))
            body.extend(b'\xff\x05'+struct.pack('<I',address))
            branch(b'\xe9','original')
    labels['original']=len(body)
    for at,label in fixups:struct.pack_into('<i',body,at,labels[label]-at-4)
    body.extend(b'\x9d')
    if alms:
        body.extend(AUTO_SITES[site][:3])
        body.extend(b'\xe8'+struct.pack('<i',0x446482+_fixture_delta-(base+len(body)+5)))
    else:body.extend(AUTO_SITES[site])
    body.extend(jump(base+len(body),site+len(AUTO_SITES[site])+_fixture_delta))
    return bytes(body),jump(site+_fixture_delta,base)+b'\x90'*(len(AUTO_SITES[site])-5)


class AutoEffects:
    def __init__(self,native,emit,effects,before_modify):
        self.n=native;self.emit=emit;self.effects=effects;self.before_modify=before_modify
        self.patch=Recruit(native,emit);self.enabled=False;self.hooks=None;self.context=None;self.scope=None
        self.marker=None;self.counts=[0]*4;self.last_poll=0;self.last_status=None

    def status(self,note):
        value=(self.enabled,bool(self.hooks),note)
        if value!=self.last_status:
            self.emit(dict(kind='auto_x3_status',enabled=self.enabled,armed=bool(self.hooks),note=note))
            self.last_status=value

    def set_enabled(self,value,allowed):
        if type(value) is not bool:raise ValueError('自动×3开关值无效')
        if value and (not allowed or self.effects.active):
            raise ValueError('请先完成或取消当前增强确认，再开启自动×3')
        if not value:
            self.restore();self.enabled=False;self.scope=None
            self.status('游戏内自动×3已关闭；已确认的指令保留其提交参数')
        else:
            if not self.enabled:self.scope=None
            self.enabled=True
            self.status('游戏内自动×3已开启，等待无弹窗的内政输入阶段')

    def identity(self,state):
        core=self.n.bound['core'];slot=self.n.number(core+0x6c0)
        if not 0<=slot<8:raise ValueError('自动×3玩家槽位不明')
        force=self.n.number(core+slot*0x87+0x4a)
        if not 0<=force<32 or self.n.number(0x53bb30)!=core:
            raise ValueError('自动×3势力／核心已改变')
        return (state['view'],state['document'],core,slot,force)

    def install(self,state):
        require_menu(state,'infantry',True)
        context=self.identity(state)
        with self.patch.writer() as handle,self.patch.frozen(AUTO_SITES):
            fresh=self.n.capture();require_menu(fresh,'infantry',True)
            if self.identity(fresh)!=context or self.effects.active:
                raise ValueError('自动×3来源或增强状态改变')
            if any(self.n.read(a,len(b))!=b for a,b in AUTO_SITES.items()):
                raise ValueError('自动×3入口已有其他修改，未覆盖')
            self.before_modify('auto_x3',fresh)
            base=self.n.k.VirtualAllocEx(handle,None,4096,0x3000,4)
            if not base:raise ValueError('无法分配自动×3输入入口')
            marker=base+0x800;hooks={}
            for index,site in enumerate(AUTO_SITES):
                address=base+index*0x400
                code,hook=auto_trampoline(address,marker,*context,alms=index==1)
                self.patch.code(handle,address,code,'auto_x3_code_write');hooks[site]=hook
            # VirtualAllocEx returns zeroed memory; counters start at zero.
            self.context=context;self.scope=context;self.marker=marker;self.counts=[0]*4;self.hooks=hooks
            try:
                for address,data in hooks.items():self.patch.code(handle,address,data,'auto_x3_hook_write')
            except Exception:
                for address,data in hooks.items():
                    current=self.n.read(address,len(data));old=AUTO_SITES[address]
                    if not any(current==data[:i]+old[i:] for i in range(len(data)+1)):
                        raise ValueError('自动×3部分安装恢复冲突，请保留面板核对')
                    self.patch.code(handle,address,old,'auto_x3_restore_write')
                self.hooks=None;raise
        self.status('游戏内自动×3生效：施舍、步／骑／弓训练；在游戏内正常选令及确认')

    def observe(self):
        if not self.hooks:return
        raw=self.n.read(self.marker,48)
        if self.n.read(self.marker,48)!=raw:return
        for index,action in enumerate(ACTIONS):
            count,before,after=struct.unpack_from('<III',raw,index*12)
            if count!=self.counts[index]:
                delta=(count-self.counts[index]) & 0xffffffff;self.counts[index]=count
                verified=(after==(before+5)*3-5 if action=='alms' else after==before*3)
                self.emit(dict(kind='auto_x3_operand',action=action,count=count,new_hits=delta,
                               operand_before=before,operand_after=after,operand_verified=verified,
                               omitted_intermediate_operands=max(0,delta-1),command_committed=None,
                               server_result_verified=False,game_order_sent=False,
                               note=f'游戏内自动×3：{action} 参数 {before}→{after}；入队／结算另行核对'))

    def restore(self):
        if not self.hooks:return
        try:self.observe()
        except (ValueError,OSError) as error:
            self.emit(dict(kind='auto_x3_observation_error',note=str(error)))
        with self.patch.writer() as handle,self.patch.frozen(AUTO_SITES):
            for address,data in self.hooks.items():
                if self.n.read(address,len(data)) not in (data,AUTO_SITES[address]):
                    raise ValueError('自动×3恢复冲突，请保留面板核对')
            for address in self.hooks:self.patch.code(handle,address,AUTO_SITES[address],'auto_x3_restore_write')
        self.hooks=None;self.context=None

    def poll(self):
        if not self.enabled:return
        now=time.monotonic()
        if now-self.last_poll<.15:return
        self.last_poll=now
        state=self.n.capture()
        if self.hooks:
            self.observe()
            if self.identity(state)!=self.context:
                self.restore();self.enabled=False;self.scope=None;self.status('游戏对象／势力改变，自动×3已关闭');return
            # +8a6 is also set when a normal phase ends. Exhausted orders,
            # phase transitions and temporary non-input modes pause the hooks,
            # not the user's persistent switch.
            if state['phase']!=1 or state['ending'] or state['mode']!=2 or state['orders_used']>=3:
                self.emit(dict(kind='auto_x3_stage_wait',phase=state['phase'],phase_end_flag=state['ending'],
                               mode=state['mode'],orders_used=state['orders_used'],enabled=True))
                self.restore();self.status('自动×3保持开启，等待下次内政输入阶段')
            return
        if self.scope is not None and self.identity(state)!=self.scope:
            self.enabled=False;self.scope=None;self.status('游戏对象／势力改变，自动×3已关闭');return
        try:require_menu(state,'infantry',True)
        except ValueError:
            self.status('自动×3已开启，等待有剩余次数且无弹窗的内政输入阶段');return
        if self.effects.active:return
        try:self.install(state)
        except Exception:
            self.enabled=False
            self.status('自动×3安装未完成，已停止自动重试；请核对回执')
            raise

    def close(self):
        self.restore();self.enabled=False;self.scope=None
