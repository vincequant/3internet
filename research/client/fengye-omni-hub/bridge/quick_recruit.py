"""Hash-locked, up-to-three-target recruitment modification for the local client.

Two scoped trampolines preserve native command queuing/ownership settlement.
No remote threads, disk patches, saves, authentication or server writes.
Allocated code pages live until SANPK exits so restoring a hook cannot free
code beneath a thread returning from it.
"""
import ctypes as C
from ctypes import wintypes as W
import struct
import time
from contextlib import contextmanager


STATUS_TEST=bytes.fromhex('66 83 78 21 01')
AFFINITY_TEST=bytes.fromhex('66 8b 46 42 66 3b 47 12 74 44')
SITES = {0x46888b:STATUS_TEST,0x4688cf:AFFINITY_TEST}


def jump(origin, destination):
    return b'\xe9' + struct.pack('<i', destination-origin-5)


def trampolines(base, force, city, general, _fixture_delta=0):
    return multi_trampolines(base, [dict(force_id=force, city_id=city, general_id=general)], _fixture_delta)


def multi_trampolines(base, targets, _fixture_delta=0):
    """Unrolled x86 filters for up to three native recruitment orders."""
    if not 1 <= len(targets) <= 3:
        raise ValueError('每回合最多三笔指定招揽')
    identities = [(t['force_id'], t['city_id'], t['general_id']) for t in targets]
    if any(type(v) is not int or not 0 <= v <= 0x7fff for row in identities for v in row):
        raise ValueError('指定招揽身份超出范围')
    if len({g for f,c,g in identities}) != len(identities) or len({f for f,c,g in identities}) != 1:
        raise ValueError('招揽目标重复或势力不一致')
    # Only relative conditional jumps and comparisons: all registers preserved.
    class Code:
        def __init__(self, address):self.address=address;self.body=bytearray();self.labels={};self.fixups=[]
        def emit(self, data):self.body.extend(data)
        def label(self, name):self.labels[name]=len(self.body)
        def branch(self, op, label):
            self.emit(op);self.fixups.append((len(self.body),label));self.emit(b'\0'*4)
        def out(self, address):self.emit(jump(self.address+len(self.body),address+_fixture_delta))
        def finish(self):
            for at,label in self.fixups:struct.pack_into('<i',self.body,at,self.labels[label]-at-4)
            return bytes(self.body)
    first=Code(base)
    groups={}
    for force,city,general in identities:groups.setdefault((force,city),[]).append(general)
    for index,((force,city),generals) in enumerate(groups.items()):
        next_group='group'+str(index)
        first.emit(bytes.fromhex('66 81 7f 08')+struct.pack('<H',force));first.branch(b'\x0f\x85',next_group)
        first.emit(b'\x81\xfb'+struct.pack('<I',city));first.branch(b'\x0f\x85',next_group)
        for general in generals:
            first.emit(bytes.fromhex('66 81 78 0a')+struct.pack('<H',general));first.branch(b'\x0f\x84','original')
        first.branch(b'\xe9','exclude')
        first.label(next_group)
    # Reserve each selected wild general against other forces / cities.
    for force,city,general in identities:
        first.emit(bytes.fromhex('66 81 78 0a')+struct.pack('<H',general));first.branch(b'\x0f\x84','exclude')
    first.label('original');first.emit(STATUS_TEST);first.out(0x468890)
    first.label('exclude');first.emit(b'\x85\xff');first.out(0x468890)
    second=Code(base+0x400)
    for index,(force,city,general) in enumerate(identities):
        next_target='target'+str(index)
        for prefix,value in [('66 81 7f 08',force),('66 81 7e 0a',general),('66 81 7e 34',city)]:
            second.emit(bytes.fromhex(prefix)+struct.pack('<H',value));second.branch(b'\x0f\x85',next_target)
        second.out(0x468925);second.label(next_target)
    second.emit(AFFINITY_TEST[:8])
    second.emit(b'\x0f\x84'+struct.pack('<i',0x46891d+_fixture_delta-(second.address+len(second.body)+6)))
    second.out(0x4688d9)
    return {base:first.finish(),base+0x400:second.finish()}, {
        0x46888b+_fixture_delta:jump(0x46888b+_fixture_delta,base),
        0x4688cf+_fixture_delta:jump(0x4688cf+_fixture_delta,base+0x400)+b'\x90'*5}


def walk(native, root, limit, vtable):
    header=native.read(root,28)
    if struct.unpack_from('<I',header)[0]!=vtable:raise ValueError('名单容器类型不匹配')
    node,tail,count=struct.unpack_from('<III',header,4)
    if not 0<=count<=limit:raise ValueError('名单数量异常')
    result=[];seen=set();previous=0
    for _ in range(count):
        if node in seen:raise ValueError('名单循环')
        seen.add(node);nxt,back,obj=struct.unpack('<III',native.read(node,12))
        if back!=previous:raise ValueError('名单关系改变')
        result.append(obj);previous,node=node,nxt
    if node or previous!=tail or native.read(root,28)!=header:raise ValueError('名单读取不稳定')
    return result


class Recruit:
    def __init__(self,native,emit):
        self.n=native;self.emit=emit;self.pending={};self.hooks=None;self.last_poll=0
        k=native.k
        specs={'VirtualAllocEx':([W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD,W.DWORD],C.c_void_p),
               'VirtualProtectEx':([W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD,C.POINTER(W.DWORD)],W.BOOL),
               'FlushInstructionCache':([W.HANDLE,C.c_void_p,C.c_size_t],W.BOOL),
               'CreateToolhelp32Snapshot':([W.DWORD,W.DWORD],W.HANDLE),
               'Thread32First':([W.HANDLE,C.c_void_p],W.BOOL),
               'Thread32Next':([W.HANDLE,C.c_void_p],W.BOOL),
               'OpenThread':([W.DWORD,W.BOOL,W.DWORD],W.HANDLE),
               'SuspendThread':([W.HANDLE],W.DWORD),'ResumeThread':([W.HANDLE],W.DWORD)}
        for name,(args,ret) in specs.items():fn=getattr(k,name);fn.argtypes=args;fn.restype=ret
        self.context=k.Wow64GetThreadContext if C.sizeof(C.c_void_p)==8 else k.GetThreadContext
        self.context.argtypes=[W.HANDLE,C.c_void_p];self.context.restype=W.BOOL

    @contextmanager
    def frozen(self, sites=None):
        sites = SITES if sites is None else sites
        class Entry(C.Structure):
            _fields_=[('size',W.DWORD),('usage',W.DWORD),('tid',W.DWORD),('pid',W.DWORD),
                      ('base_priority',W.LONG),('delta_priority',W.LONG),('flags',W.DWORD)]
        k=self.n.k;snapshot=k.CreateToolhelp32Snapshot(4,0);handles=[]
        if snapshot in (None,C.c_void_p(-1).value):raise C.WinError(C.get_last_error())
        try:
            row=Entry();row.size=C.sizeof(row);ok=k.Thread32First(snapshot,C.byref(row))
            tids=[]
            while ok:
                if row.pid==self.n.bound['pid']:tids.append(row.tid)
                ok=k.Thread32Next(snapshot,C.byref(row))
            if not tids:raise ValueError('游戏线程已结束')
            for tid in tids:
                handle=k.OpenThread(0xa,False,tid)
                if not handle:raise C.WinError(C.get_last_error())
                if k.SuspendThread(handle)==0xffffffff:
                    k.CloseHandle(handle);raise C.WinError(C.get_last_error())
                handles.append(handle)
                context=C.create_string_buffer(716);struct.pack_into('<I',context,0,0x10001)
                if not self.context(handle,context):raise C.WinError(C.get_last_error())
                ip=struct.unpack_from('<I',context,184)[0]
                if any(a<ip<a+len(data) for a,data in sites.items()):
                    raise BlockingIOError('游戏线程正在通过补丁，稍后恢复')
            self.n.check_identity(self.n.handle)
            yield
        finally:
            for handle in reversed(handles):
                resumed=k.ResumeThread(handle);k.CloseHandle(handle)
                if resumed==0xffffffff:self.emit(dict(kind='thread_resume_error',error=C.get_last_error()))
            k.CloseHandle(snapshot)

    @contextmanager
    def writer(self):
        h=self.n.k.OpenProcess(0x438,False,self.n.bound['pid'])
        if not h:raise C.WinError(C.get_last_error())
        try:self.n.check_identity(h);yield h
        finally:self.n.k.CloseHandle(h)

    def write(self,h,address,data,kind):
        self.emit(dict(kind=kind+'_intent',address=hex(address),before=self.n.read(address,len(data)).hex(),after=data.hex()))
        got=C.c_size_t();buf=C.create_string_buffer(data)
        ok=self.n.k.WriteProcessMemory(h,address,buf,len(data),C.byref(got))
        self.emit(dict(kind=kind+'_receipt',address=hex(address),api_ok=bool(ok),bytes_written=got.value))
        if not ok or got.value!=len(data) or self.n.read(address,len(data))!=data:
            raise ValueError('修改结果未知；本次不重发招揽')

    def code(self,h,address,data,kind='recruit_code_write'):
        old=W.DWORD()
        if not self.n.k.VirtualProtectEx(h,address,len(data),0x40,C.byref(old)):raise C.WinError(C.get_last_error())
        try:
            self.write(h,address,data,kind)
            if not self.n.k.FlushInstructionCache(h,address,len(data)):raise C.WinError(C.get_last_error())
        finally:
            ignored=W.DWORD()
            if not self.n.k.VirtualProtectEx(h,address,len(data),old.value,C.byref(ignored)):
                raise C.WinError(C.get_last_error())

    def target(self,general,city):
        n=self.n;core=n.bound['core']
        if n.number(0x53bb30)!=core:raise ValueError('结算核心与当前游戏不一致')
        slot=n.number(core+0x6c0)
        if not 0<=slot<8:raise ValueError('本机玩家槽位异常')
        force=n.number(core+slot*0x87+0x4a)
        if not 0<=force<32:raise ValueError('本机势力身份异常')
        generals=walk(n,core+0x514,1024,0x4fd698)
        rows=[]
        for obj in generals:
            raw=n.read(obj,0x60)
            if struct.unpack_from('<I',raw)[0]!=0x5056f0:raise ValueError('武将类型不匹配')
            if struct.unpack_from('<H',raw,0xa)[0]==general:rows.append((obj,raw))
        if len(rows)!=1:raise ValueError('找不到唯一指定武将')
        obj,raw=rows[0]
        if (struct.unpack_from('<H',raw,8)[0]!=65535 or struct.unpack_from('<H',raw,0x21)[0]!=1
                or struct.unpack_from('<h',raw,0x34)[0]!=city):raise ValueError('指定武将已改变归属／城池／在野状态')
        return dict(general_id=general,city_id=city,force_id=force,address=obj,raw_before=raw.hex())

    def install(self,target):
        if target['general_id'] in self.pending or len(self.pending)>=3:raise ValueError('目标已入队或已达到三笔招揽上限')
        previous_hooks=self.hooks
        targets=[*self.pending.values(),target]
        with self.writer() as h,self.frozen():
            doc=self.n.bound['core']-0x912
            if self.n.number(doc+0xdea,'<h')!=1 or self.n.number(doc+0x68)!=2:
                raise ValueError('游戏已离开战略输入阶段，未安装招揽修改')
            fresh=self.target(target['general_id'],target['city_id'])
            if 'selection_attributes' in target and bytes.fromhex(fresh['raw_before'])[37:42]!=bytes.fromhex(target['raw_before'])[37:42]:
                raise ValueError('选将能力值在打开菜单后改变，未安装招揽修改')
            expected=previous_hooks or SITES
            if any(self.n.read(a,len(b))!=b for a,b in expected.items()):raise ValueError('招揽代码已被其他工具修改')
            base=self.n.k.VirtualAllocEx(h,None,4096,0x3000,4)
            if not base or not 0x10000<=base<0x7fff0000:raise ValueError('无法分配本局招揽代码页')
            bodies,hooks=multi_trampolines(base,targets)
            for address,data in bodies.items():self.write(h,address,data,'recruit_scoped_code')
            old=W.DWORD()
            if not self.n.k.VirtualProtectEx(h,base,4096,0x20,C.byref(old)):raise C.WinError(C.get_last_error())
            if not self.n.k.FlushInstructionCache(h,base,4096):raise C.WinError(C.get_last_error())
            self.hooks=hooks
            try:
                for address,data in hooks.items():self.code(h,address,data)
            except Exception:
                # Roll back verified partial hooks before resuming any thread.
                for address,original in expected.items():self.code(h,address,original)
                self.hooks=previous_hooks;raise
        self.pending[target['general_id']]=target
        self.emit(dict(kind='target_recruit_armed',target=target,code_page=hex(base),server_result_verified=False))

    def restore(self):
        if not self.hooks:return
        for attempt in range(30):
            try:self.restore_once();return
            except BlockingIOError:
                if attempt==29:raise
                time.sleep(.02)

    def restore_once(self):
        with self.writer() as h,self.frozen():
            for address,data in self.hooks.items():
                if self.n.read(address,len(data))!=data:raise ValueError('招揽代码被外部修改，未覆盖')
            for address,original in SITES.items():self.code(h,address,original)
        self.hooks=None
        self.emit(dict(kind='target_recruit_hooks_restored',pending=self.pending))

    def point(self,hwnd,x,y,kind):
        n=self.n
        if n.owner(hwnd)!=n.bound['pid'] or not 0<=x<32768 or not 0<=y<32768:raise ValueError('招揽输入窗口／坐标异常')
        self.emit(dict(kind=kind+'_intent',hwnd=hwnd,point=[x,y]))
        for message,buttons in ((0x200,0),(0x201,1),(0x202,0)):
            ok=n.u.PostMessageW(hwnd,message,buttons,x|(y<<16))
            self.emit(dict(kind=kind+'_receipt',hwnd=hwnd,message=message,posted=bool(ok)))
            if not ok:raise ValueError('招揽输入回执未知，未重试')

    def city_point(self,state,city):
        n=self.n;p=state['recruit_dialog'];raw=n.read(p,0x214);m=raw[0xb0:0x20c]
        if (not state['recruit_visible'] or struct.unpack_from('<I',m)[0]!=0x4fc990
                or struct.unpack_from('<I',m,0x3c)[0]!=n.bound['core']):raise ValueError('录用地图来源异常')
        hwnd=struct.unpack_from('<I',m,0x1c)[0];count=struct.unpack_from('<I',m,0x80)[0]
        if (n.owner(hwnd)!=n.bound['pid'] or not n.u.IsWindowVisible(hwnd)
                or n.u.GetDlgCtrlID(hwnd)!=1057 or n.u.GetParent(hwnd)!=n.number(p+0x1c)):
            raise ValueError('录用地图窗口关系改变')
        rows=walk(n,n.bound['core']+0x554,128,0x503b68)
        if len(rows)!=count:raise ValueError('录用城池数量异常')
        flags=n.read(struct.unpack_from('<I',m,0x7c)[0],count);ox,oy=struct.unpack_from('<ii',m,0x40)
        if not 0<=ox<=4096 or not 0<=oy<=4096:raise ValueError('录用地图偏移异常')
        rectangles=[];matches=[]
        for index,obj in enumerate(rows):
            data=n.read(obj,0x1e);vt=struct.unpack_from('<I',data)[0]
            if vt not in (0x503688,0x5037d0):raise ValueError('城池类型异常')
            ident=struct.unpack_from('<H',data,0xa)[0];x,y=struct.unpack_from('<ii',data,0x16)
            if not 0<=x<=4096 or not 0<=y<=4096:raise ValueError('城池图标像素异常')
            size=16 if vt==0x503688 else 12
            point=(x+ox+8,y+oy+8);rectangles.append((ident,x+ox,y+oy,size))
            if ident==city and vt==0x503688 and not flags[index]&1:matches.append(point)
        if len(matches)!=1:raise ValueError('城池不可录用或图标不唯一')
        px,py=matches[0]
        hits=[cid for cid,x,y,size in rectangles if x<=px<x+size and y<=py<y+size]
        if hits!=[city] or n.read(p,0x214)!=raw:raise ValueError('录用图标重叠或地图已改变')
        return hwnd,matches[0]

    def yes_point(self,state):
        n=self.n;view=state['view']
        if not state['confirmation_typed']:raise ValueError('没有唯一原生费用确认')
        head=n.number(view+0x7fe);obj=n.number(head+8);buttons=walk(n,obj,8,0x5059d0)
        points={};ox,oy=struct.unpack('<ii',n.read(view+0x54,8))
        for button in buttons:
            raw=n.read(button,0x44)
            if struct.unpack_from('<I',raw)[0]!=0x505950:continue
            code=struct.unpack_from('<i',raw,0x3c)[0]
            if code not in (6,7):continue
            ptr=struct.unpack_from('<I',raw,0x38)[0];length=n.number(ptr-8,'<i')
            if not 0<length<16:raise ValueError('确认文字异常')
            text=n.read(ptr,length+1)
            if text[-1]!=0 or text[:-1].decode('gbk').strip()!=('是' if code==6 else '否'):
                raise ValueError('费用确认文字不匹配')
            image=n.read(struct.unpack_from('<I',raw,0x10)[0],0x34)
            if struct.unpack_from('<I',image)[0]!=0x50cad8:raise ValueError('确认按钮图像未知')
            info=n.read(struct.unpack_from('<I',image,4)[0],12);w,h=struct.unpack_from('<ii',info,4)
            x,y=struct.unpack_from('<ii',raw,4)
            if not 4<w<=512 or not 4<h<=512 or code in points:raise ValueError('确认按钮尺寸异常')
            points[code]=(x-ox+w//2,y-oy+h//2)
        if set(points)!={6,7}:raise ValueError('确认按钮不完整')
        return points[6]

    def submit(self,general,city,enabled,allow,open_menu,expected_attributes=None):
        if not enabled or not allow:raise ValueError('请启用快捷修改和指定武将招揽')
        if general in self.pending or len(self.pending)>=3:raise ValueError('目标已入队或已达到三笔招揽上限')
        target=self.target(general,city);before=self.n.capture()
        if expected_attributes is not None:
            actual=dict(zip(('lead','war','intel','pol','cha'),bytes.fromhex(target['raw_before'])[37:42]))
            if (not isinstance(expected_attributes,dict) or not {'lead','war','pol'}<=expected_attributes.keys()
                    or any(k not in actual or type(v) is not int or actual[k]!=v for k,v in expected_attributes.items())):
                raise ValueError('选将能力值已改变；未打开菜单，请重新点击选将按钮')
            target['selection_attributes']=expected_attributes
        result=open_menu()
        if result.get('status')!='dialog_observed':raise ValueError('未核准录用窗口；没有选城或修改判定')
        opened=self.n.capture();hwnd,point=self.city_point(opened,city)
        previous_hooks=self.hooks
        self.install(target)
        try:
            self.point(hwnd,*point,'recruit_city_click')
            for attempt in range(250):
                time.sleep(.1);state=self.n.capture()
                if attempt%15==0:self.emit(dict(kind='target_recruit_observation',state=state))
                if state['confirmation_typed']:
                    # Exact opening, selected city and same single pending operation.
                    if not state['recruit_dialog'] or self.n.number(state['recruit_dialog']+0x208)!=city:
                        raise ValueError('费用确认选城不匹配')
                    yes=self.yes_point(state)
                    fresh=self.n.capture()
                    if (fresh['recruit_dialog']!=state['recruit_dialog'] or not fresh['confirmation_typed']
                            or self.yes_point(fresh)!=yes):raise ValueError('费用确认已改变')
                    # Populate the same typed YES result consumed by the native
                    # widget loop; no callback execution or duplicate mouse input.
                    head=self.n.number(state['view']+0x7fe);widget=self.n.number(head+8)
                    if self.n.number(widget+0x50,'<i')!=-1:raise ValueError('费用确认结果已改变')
                    with self.writer() as h:
                        self.write(h,widget+0x50,struct.pack('<i',6),'recruit_fee_yes_result')
                    break
                if state['orders_used']==before['orders_used']+1 and not state['recruit_dialog']:break
            else:raise ValueError('选城结果未知，未重发')
            for attempt in range(250):
                time.sleep(.1);state=self.n.capture()
                if attempt%15==0:self.emit(dict(kind='target_recruit_observation',state=state))
                if state['orders_used']==before['orders_used']+1 and not state['modal'] and not state['recruit_dialog']:
                    self.pending[general]['order_submitted']=True
                    return dict(status='target_recruit_queued',after=state,target=target,
                                note='指定招揽已入队；可以继续选择下一名，结束战略回合后核验归属。',pending_count=len(self.pending),recruitment_succeeded=None)
            raise ValueError('提交结果未知；不重发，请检查原生窗口与指令')
        except Exception:
            # Restore only the failed new submission's filter, retaining prior
            # queued targets. Never replay its menu / city / fee input.
            self.pending.pop(general,None)
            if previous_hooks:
                with self.writer() as h,self.frozen():
                    if any(self.n.read(a,len(b))!=b for a,b in self.hooks.items()):raise ValueError('招揽代码改变，未覆盖')
                    for address,data in previous_hooks.items():self.code(h,address,data)
                self.hooks=previous_hooks
            else:self.restore()
            raise

    def poll(self):
        if not self.pending or time.monotonic()-self.last_poll<.25:return
        self.last_poll=time.monotonic();n=self.n
        terminal=[]
        for general,t in list(self.pending.items()):
            raw=n.read(t['address'],0x60)
            if (struct.unpack_from('<I',raw)[0]!=0x5056f0 or struct.unpack_from('<H',raw,0xa)[0]!=general):
                self.restore();self.pending.clear();raise ValueError('待结算武将对象改变')
            owner=struct.unpack_from('<H',raw,8)[0];status=struct.unpack_from('<H',raw,0x21)[0]
            if owner==t['force_id'] and status in (9,0):
                terminal.append(dict(kind='target_recruit_settled',target=t,owner=owner,status_code=status,
                    recruitment_ownership_verified=True,standby_verified=status==0,server_result_verified=False,
                    note='指定武将归属已核验；'+('已待命。' if status==0 else '等待下季转为待命。')))
            elif owner!=65535 or status!=1:
                terminal.append(dict(kind='target_recruit_failed',target=t,owner=owner,status_code=status,
                    note='武将状态已被其他结算改变；未宣称必得，未重复招揽。'))
        for event in terminal:self.pending.pop(event['target']['general_id'])
        if terminal and not self.pending:self.restore()
        for event in terminal:self.emit(dict(event,pending_count=len(self.pending)))
