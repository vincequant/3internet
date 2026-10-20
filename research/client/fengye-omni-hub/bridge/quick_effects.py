"""One-shot, view/document-scoped native training and alms order modifiers.

Change the serialized command operand, so native projection and settlement use
the same operand. No general attributes, resource fees or limits are patched.
Code allocations live until process exit, as with quick_recruit.
"""
import struct
import time
from quick_recruit import Recruit, jump, walk
from quick_control_model import require_menu

TRAINING = {'infantry': 0, 'cavalry': 1, 'bow': 2}
TARGETS = {'infantry':300,'cavalry':300,'bow':199}
TARGET_NAMES={'infantry':'步兵','cavalry':'铁骑','bow':'弓兵'}
TOKENS = {a:-(0x514300+i) for a,i in TRAINING.items()}
SITES = {0x4a3c88: bytes.fromhex('01 45 b4 8d 45 98'),
         0x4a482c: bytes.fromhex('89 55 e0 e8 4e 1c fa ff'),
         0x4a39e2:bytes.fromhex('3d 2c 01 00 00')}
RULE_SITES = {0x4a3d91:bytes.fromhex('83 c4 0c 89 45 e8'),
              **{a:bytes.fromhex('83 c4 0c 8b ce') for a in (0x450a3b,0x450a7d,0x450abf)}}


def trampoline(base, marker, view, document, action, _fixture_delta=0):
    """Preserve flags/registers except the native command operand itself."""
    if action not in (*TRAINING, 'alms'):
        raise ValueError('不支持的增强指令')
    if any(type(x) is not int or not 0x10000 <= x < 0x7fff0000
           for x in (base, marker, view, document)):
        raise ValueError('增强指令地址异常')
    site = 0x4a482c if action == 'alms' else 0x4a3c88
    body = bytearray(b'\x9c')  # pushfd
    exits = []
    def guard(data):
        body.extend(data + b'\x0f\x85'); exits.append(len(body)); body.extend(b'\0'*4)
    guard(b'\x81\xff' + struct.pack('<I', view))
    guard(bytes.fromhex('81 7f 3c') + struct.pack('<I', document))
    # Check the bound document directly, without changing a general register.
    guard(b'\x83\x3d' + struct.pack('<I', document+0x68) + b'\x02')
    guard(b'\x66\x83\x3d' + struct.pack('<I', document+0xdea) + b'\x01')
    if action != 'alms':
        guard(bytes.fromhex('83 7d 08') + bytes([TRAINING[action]]))
    guard(b'\x83\x3d' + struct.pack('<I', marker) + b'\x00')
    register_store = b'\x89\x15' if action == 'alms' else b'\xa3'
    body.extend(register_store + struct.pack('<I', marker+4))
    if action == 'alms':
        # edx is the native remainder 0..4. Settlement adds 5, so store
        # (edx+5)*3-5 and the original add-5 becomes exactly three alms.
        body.extend(bytes.fromhex('83 c2 05 8d 14 52 83 ea 05'))
    else:
        body.extend(b'\xb8'+struct.pack('<i',TOKENS[action]))
    body.extend(register_store + struct.pack('<I', marker+8))
    body.extend(b'\xc7\x05' + struct.pack('<I', marker) + struct.pack('<I', 1))
    original = len(body)
    for at in exits: struct.pack_into('<i', body, at, original-at-4)
    body.extend(b'\x9d')  # popfd, then replay complete original instructions
    if action == 'alms':
        body.extend(SITES[site][:3])
        body.extend(b'\xe8' + struct.pack('<i', 0x446482+_fixture_delta-(base+len(body)+5)))
    else:
        body.extend(SITES[site])
    body.extend(jump(base+len(body), site+len(SITES[site])+_fixture_delta))
    hooks={site+_fixture_delta:jump(site+_fixture_delta,base)+b'\x90'*(len(SITES[site])-5)}
    if action=='bow':
        # Permit exactly this panel's bow correction even when native raw=300.
        gate=bytearray(b'\x9c');fallbacks=[]
        for data in (b'\x81\xfb'+struct.pack('<I',view),b'\x81\xfe'+struct.pack('<I',document),
                     b'\x83\x3d'+struct.pack('<I',marker)+b'\x00'):
            gate.extend(data+b'\x0f\x85');fallbacks.append(len(gate));gate.extend(b'\0'*4)
        gate.extend(bytes.fromhex('9d 85 db')) # nonzero bound EBX -> JNE native fee path
        gate.extend(jump(base+0x400+len(gate),0x4a39e7+_fixture_delta))
        fallback=len(gate)
        for at in fallbacks:struct.pack_into('<i',gate,at,fallback-at-4)
        gate.extend(b'\x9d'+SITES[0x4a39e2])
        gate.extend(jump(base+0x400+len(gate),0x4a39e7+_fixture_delta))
        body.extend(b'\x90'*(0x400-len(body)));body.extend(gate)
        hooks[0x4a39e2+_fixture_delta]=jump(0x4a39e2+_fixture_delta,base+0x400)
    return bytes(body),hooks


def target_rules(base,view,document,core,lord,_fixture_delta=0):
    """Tagged commands only: gain = requested level minus current native level.

    Scope projection by exact view/document and settlement by exact typed lord
    pointer/core. Untagged commands always execute original native formulas.
    """
    pages={};hooks={}
    for index,site in enumerate(RULE_SITES):
        address=base+index*0x200;body=bytearray(b'\x9c');fixups=[];labels={}
        def guard(data,label='original'):
            body.extend(data+b'\x0f\x85');fixups.append((len(body),label));body.extend(b'\0'*4)
        def branch(label):
            body.extend(b'\xe9');fixups.append((len(body),label));body.extend(b'\0'*4)
        if index==0:
            guard(b'\x81\xff'+struct.pack('<I',view))
            guard(bytes.fromhex('81 7f 3c')+struct.pack('<I',document))
            for action,kind in TRAINING.items():
                next_label='next'+str(kind)
                guard(bytes.fromhex('83 7d 08')+bytes([kind]),next_label)
                guard(bytes.fromhex('81 7d b4')+struct.pack('<i',TOKENS[action]),next_label)
                body.extend(b'\xb8'+struct.pack('<I',TARGETS[action])+bytes.fromhex('2b 45 f0'))
                branch('original');labels[next_label]=len(body)
        else:
            action=list(TRAINING)[index-1]
            guard(b'\x81\xfe'+struct.pack('<I',lord))
            guard(b'\x81\x3d'+struct.pack('<I',0x53bb30+_fixture_delta)+struct.pack('<I',core))
            # Original ESP + 0x1c is politics; PUSHFD moves it to +0x20.
            guard(bytes.fromhex('81 7c 24 20')+struct.pack('<i',TOKENS[action]))
            raw_offset=(0x24,0x2a,0x30)[index-1]
            body.extend(bytes.fromhex('52 0f b7 56')+bytes([raw_offset]))
            body.extend(b'\xb8'+struct.pack('<I',TARGETS[action])+bytes.fromhex('2b c2 5a'))
        labels['original']=len(body)
        for at,label in fixups:struct.pack_into('<i',body,at,labels[label]-at-4)
        body.extend(b'\x9d'+RULE_SITES[site])
        body.extend(jump(address+len(body),site+len(RULE_SITES[site])+_fixture_delta))
        pages[address]=bytes(body)
        hooks[site+_fixture_delta]=jump(site+_fixture_delta,address)+b'\x90'*(len(RULE_SITES[site])-5)
    return pages,hooks


class Effects:
    uses_training_targets = True

    def input_trampoline(self, base, marker, view, document, action, _fixture_delta=0):
        return trampoline(base, marker, view, document, action, _fixture_delta)

    def __init__(self, native, emit):
        self.n = native; self.emit = emit; self.patch = Recruit(native, emit)
        self.active = None; self.hooks = None
        self.rule_hooks=None;self.rule_lord=None;self.pending={};self.last_poll=0

    def values(self, state):
        doc = state['document']
        return dict(gold=self.n.number(doc+0x795), rice=self.n.number(doc+0x799),
                    prestige=self.n.number(doc+0x791),
                    armaments=[self.n.number(doc+a) for a in (0x7bd,0x7c9,0x7d5)])

    def ensure_rules(self,state):
        if self.rule_hooks:
            core=self.n.bound['core'];slot=self.n.number(core+0x6c0)
            if (not 0<=slot<8 or self.n.number(core+slot*0x87+0x4a)!=self.rule_force
                    or state['view']!=self.rule_view or state['document']!=self.rule_doc
                    or self.n.number(self.rule_lord)!=0x506660
                    or self.n.number(self.rule_lord+8,'<H')!=self.rule_force):
                raise ValueError('本机势力／视图改变；请结算后重新连接，未提交训练')
            if any(self.n.read(a,len(b))!=b for a,b in self.rule_hooks.items()):
                raise ValueError('训练结算代码已改变')
            return
        core=self.n.bound['core'];slot=self.n.number(core+0x6c0)
        if not 0<=slot<8:raise ValueError('本机玩家槽位异常')
        force=self.n.number(core+slot*0x87+0x4a)
        if not 0<=force<32:raise ValueError('本机势力身份异常')
        rows=[a for a in walk(self.n,core+0x4f4,32,0x503be0)
              if self.n.number(a)==0x506660 and self.n.number(a+8,'<H')==force]
        if len(rows)!=1:raise ValueError('找不到唯一的本机势力结算对象')
        lord=rows[0]
        with self.patch.writer() as handle,self.patch.frozen(RULE_SITES):
            fresh=self.n.capture();require_menu(fresh,'bow',True)
            if fresh['view']!=state['view'] or fresh['document']!=state['document']:
                raise ValueError('训练结算来源改变')
            if any(self.n.read(a,len(b))!=b for a,b in RULE_SITES.items()):
                raise ValueError('训练结算入口已有其他补丁')
            base=self.n.k.VirtualAllocEx(handle,None,4096,0x3000,4)
            if not base:raise ValueError('无法分配训练结算代码')
            pages,hooks=target_rules(base,state['view'],state['document'],core,lord)
            for a,b in pages.items():self.patch.code(handle,a,b,'training_rule_code_write')
            self.rule_hooks=hooks;self.rule_lord=lord
            self.rule_force=force;self.rule_view=state['view'];self.rule_doc=state['document']
            try:
                for a,b in hooks.items():self.patch.code(handle,a,b,'training_rule_hook_write')
            except Exception:
                for a,b in hooks.items():
                    current=self.n.read(a,len(b));old=RULE_SITES[a]
                    if any(current==b[:i]+old[i:] for i in range(len(b)+1)):
                        self.patch.code(handle,a,old,'training_rule_restore_write')
                    else:raise ValueError('训练结算补丁恢复冲突，请保留面板核对')
                self.rule_hooks=None;self.rule_lord=None;raise
        self.emit(dict(kind='training_target_rules_armed',lord=lord,force_id=force,targets=TARGETS))

    def install(self, action, state):
        if self.active: raise ValueError('请先完成或取消游戏内的训练／施舍确认')
        site = 0x4a482c if action == 'alms' else 0x4a3c88
        original = SITES[site]
        before = self.values(state)
        if any(not 0<=v<=300 for v in before['armaments']) or not 0<=before['prestige']<=200:
            raise ValueError('本机训练度／民望超出原版范围')
        if action in TRAINING:self.ensure_rules(state)
        expected={site:original,**({0x4a39e2:SITES[0x4a39e2]} if action=='bow' else {})}
        with self.patch.writer() as handle, self.patch.frozen(expected):
            fresh = self.n.capture(); require_menu(fresh, action, True)
            if self.n.number(0x53bb30) != self.n.bound['core']:
                raise ValueError('结算核心与当前游戏不一致')
            if fresh['view'] != state['view'] or fresh['document'] != state['document']:
                raise ValueError('增强指令来源改变')
            if any(self.n.read(a,len(b))!=b for a,b in expected.items()):
                raise ValueError('训练／施舍代码已被其他工具修改')
            # Persist the per-force marker before allocation or any patch write.
            # Failed/cancelled attempts stay conservatively marked; success is
            # recorded separately by the existing native command receipts.
            if getattr(self, 'before_modify', None):
                self.before_modify(action, fresh)
            base = self.n.k.VirtualAllocEx(handle,None,4096,0x3000,4)
            if not base: raise ValueError('无法分配增强指令代码')
            marker = base+0x800
            code,hooks = self.input_trampoline(base,marker,state['view'],state['document'],action)
            self.patch.code(handle,base,code,'effect_code_write')
            self.active = dict(action=action,marker=marker,state=state,before=before,
                               at=time.monotonic(),operand=None)
            self.hooks=hooks; self.n.effects_pending=True
            try:
                for address,data in hooks.items(): self.patch.code(handle,address,data,'effect_hook_write')
            except Exception:
                # A failed/partial write can only be restored if its bytes are
                # an original/hook prefix; don't overwrite an unrelated patch.
                for address,data in hooks.items():
                    current=self.n.read(address,len(data)); old=SITES[address]
                    if any(current==data[:i]+old[i:] for i in range(len(data)+1)):
                        self.patch.code(handle,address,old,'effect_restore_write')
                    else: raise ValueError('增强补丁恢复冲突，请保留面板核对')
                self.hooks=None;self.active=None;self.n.effects_pending=False
                raise
        self.emit(dict(kind='effect_armed',action=action,before=before,state=state))

    def restore(self):
        if not self.hooks: return
        with self.patch.writer() as handle, self.patch.frozen({a:SITES[a] for a in self.hooks}):
            for address,data in self.hooks.items():
                current=self.n.read(address,len(data))
                if current not in (data,SITES[address]): raise ValueError('增强补丁恢复冲突')
            for address in self.hooks: self.patch.code(handle,address,SITES[address],'effect_restore_write')
        self.hooks=None
        self.emit(dict(kind='effect_hooks_restored'))

    def poll(self):
        now=time.monotonic()
        if now-self.last_poll<.15:return
        self.last_poll=now
        if self.pending:
            state=self.n.capture()
            if self.n.number(self.rule_lord)!=0x506660 or self.n.number(0x53bb30)!=self.n.bound['core']:
                raise ValueError('训练结算对象／核心已改变')
            for action,row in list(self.pending.items()):
                ended=state['phase']!=1 or state['start_tick']!=row['start_tick']
                actual=self.n.number(self.rule_lord+(0x24,0x2a,0x30)[TRAINING[action]],'<H')
                if ended and actual==TARGETS[action]:
                    self.emit(dict(kind='training_target_settled',action=action,target=TARGETS[action],actual=actual,
                                   core_level_verified=True,server_result_verified=False,note=f'{TARGET_NAMES[action]}训练结算已核验：{actual}。'))
                    self.pending.pop(action)
            self.n.training_pending=list(self.pending)
        if not self.active: return
        row=self.active
        hit,before,after=struct.unpack('<III',self.n.read(row['marker'],12))
        if hit and row['operand'] is None:
            row['operand']=dict(before=before,after=after)
            row['prepared_at']=now
            if row['action'] in TRAINING and self.uses_training_targets:
                self.pending[row['action']]=dict(start_tick=row['state']['start_tick'])
                self.n.training_pending=list(self.pending)
            self.emit(dict(kind='effect_operand_prepared',action=row['action'],operand=row['operand']))
            self.restore()  # serialized/native stack operand no longer needs a hook
        state=self.n.capture()
        idle=not state['modal'] and not state['native_dialogs'] and not state['widget_count']
        if not idle: return  # keep the native fee/feedback dialog user-controlled
        if state['orders_used']==row['state']['orders_used']+1 and state['phase']==1:
            self.restore()
            values=self.values(state)
            verified=row['operand'] is not None
            self.emit(dict(kind='effect_command_queued' if verified else 'effect_command_uncommitted',action=row['action'],operand=row['operand'],
                           before=row['before'],after=values,state=state,
                           note='增强指令已入队；费用与次数沿用原版，正常结束战略回合后结算。' if verified else '指令次数已改变，但增强参数未核准；请核对游戏，程序不会重发。'))
        elif hit and state['phase']==1 and state['start_tick']==row['state']['start_tick'] and now-row.get('prepared_at',now)<30:
            # Native feedback/animation can briefly have modal=0 before fee
            # deduction and the command counter update. This is not a cancel.
            return
        elif time.monotonic()-row['at']>=2:
            self.restore()
            self.emit(dict(kind='effect_command_uncommitted',action=row['action'],operand=row['operand'],
                           state=state,note='增强确认已结束；未核准入队，请核对游戏，程序不会重发。' if hit else '本次训练／施舍未确认，未增加效果。'))
        else: return
        self.active=None;self.n.effects_pending=False

    def execute(self,action,enabled,allow_write,intent,hotkey=False):
        if not enabled or not allow_write: raise ValueError('增强指令未启用')
        if hotkey and self.n.owner(self.n.u.GetForegroundWindow())!=self.n.bound['pid']:
            return dict(status='ignored',note='快捷键仅在游戏置前时生效')
        if time.monotonic()-self.n.last_input<.35: raise ValueError('操作太快，请稍候')
        state=self.n.capture();require_menu(state,action,enabled)
        self.install(action,state)
        try:
            result=self.n.execute(action,enabled,allow_write,intent,hotkey)
        except Exception:
            self.restore();self.active=None;self.n.effects_pending=False
            raise
        result['note']=f'已打开原版费用确认；确认后训练设到{TARGETS[action]}，保持面板开启至回合结算。' if action in TRAINING else '已打开原版施舍确认；按这次随机加值的3倍，原版上限200。'
        return result

    def close(self):
        self.restore()
        if self.rule_hooks:
            with self.patch.writer() as handle,self.patch.frozen(RULE_SITES):
                for a,b in self.rule_hooks.items():
                    if self.n.read(a,len(b)) not in (b,RULE_SITES[a]):raise ValueError('训练结算恢复冲突')
                for a in self.rule_hooks:self.patch.code(handle,a,RULE_SITES[a],'training_rule_restore_write')
            self.rule_hooks=None
            self.emit(dict(kind='training_target_rules_restored',pending=list(self.pending)))
        self.active=None;self.pending.clear();self.n.effects_pending=False;self.n.training_pending=[]
