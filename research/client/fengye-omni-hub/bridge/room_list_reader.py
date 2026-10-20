"""Scoped Windows/Wine room reader. No memory writes, injection or joining.

--refresh uses ONLY the existing Refresh and its exact Search-confirm buttons.
Unknown binaries, ambiguous windows, and other dialogs fail closed.
--quiet hides SANPK wait windows without activating them or sending global input.
--reveal shows previously hidden SANPK windows after an explicit user request.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe import MBI
from network_payloads import is_supported_network_sha
from room_instance import choose_instances, parse_target_argv
from room_list_model import apply_layout_freshness, compare_record, decode_room, listbox_agreement, ui_list_agreement

GAME_SHA = '1cc8bb686f63d32eb1f2a4107374a0a60927d1ea7f9a7b0652245ef7e7bd35a2'
GAME_SHAS = (GAME_SHA, 'df9b52251ff1d7bbbcae04defb31f489c77d4fca9d9059c1841df93a20da8eea')
NETWORK_SHA = '629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
TITLE = '游戏选择'
CONFIRM = '按【确认】搜寻服务器'
SW_HIDE = 0
SW_SHOW = 5
SWP_NOACTIVATE = 0x0010
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOREDRAW = 0x0008
SWP_HIDEWINDOW = 0x0080
u = c.WinDLL('user32', use_last_error=True)
k = c.WinDLL('kernel32', use_last_error=True)
CB = c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
u.EnumWindows.argtypes=[CB,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,CB,w.LPARAM]
for fn in ('GetWindowTextW','GetClassNameW'):
    getattr(u,fn).argtypes=[w.HWND,w.LPWSTR,c.c_int]
for fn in ('IsWindowVisible','IsWindowEnabled','GetDlgCtrlID','IsWindow'):
    getattr(u,fn).argtypes=[w.HWND]
u.EnableWindow.argtypes=[w.HWND,w.BOOL]
u.EnableWindow.restype=w.BOOL
u.GetParent.argtypes=[w.HWND];u.GetParent.restype=w.HWND
u.GetWindowLongW.argtypes=[w.HWND,c.c_int];u.GetWindowLongW.restype=c.c_long
u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
u.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
u.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,c.POINTER(c.c_size_t)]
u.SendMessageTimeoutW.restype=w.LPARAM
u.SendMessageTimeoutA.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,c.POINTER(c.c_size_t)]
u.SendMessageTimeoutA.restype=w.LPARAM
u.IsWindowUnicode.argtypes=[w.HWND]
LB_GETCOUNT=0x018B
LB_GETTEXT=0x0189
LB_GETTEXTLEN=0x018A
SMTO_ABORTIFHUNG=0x0002
u.ShowWindow.argtypes=[w.HWND,c.c_int]
u.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.CloseHandle.argtypes=[w.HANDLE]
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
k.ReadProcessMemory.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
k.VirtualQueryEx.argtypes=[w.HANDLE,c.c_void_p,c.POINTER(MBI),c.c_size_t];k.VirtualQueryEx.restype=c.c_size_t

def label(hwnd, cls=False):
    b=c.create_unicode_buffer(256)
    (u.GetClassNameW if cls else u.GetWindowTextW)(hwnd,b,len(b))
    return b.value

def process_id(hwnd):
    pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,c.byref(pid));return pid.value

def process_image(pid):
    handle=k.OpenProcess(0x1000,False,pid)
    if not handle:
        return ''
    path=c.create_unicode_buffer(32768);n=w.DWORD(len(path))
    ok=k.QueryFullProcessImageNameW(handle,0,path,c.byref(n));k.CloseHandle(handle)
    return path.value if ok else ''

def process_command(pid):
    if sys.platform=='win32':
        return process_image(pid)
    try:
        import subprocess
        text=subprocess.check_output(['/bin/ps','-p',str(int(pid)),'-ww','-o','command='],
                                     text=True,errors='replace').strip()
        return text
    except Exception:
        return ''

def window_candidate(hwnd):
    pid=process_id(hwnd)
    command=process_command(pid)
    return {
        'hwnd':int(hwnd),'pid':pid,'title':label(hwnd),'class':label(hwnd,True),
        'exe_win':process_image(pid),'exe_unix':command,'command':command,
        'prefix':'',
    }

def windows(pid=None, visible_only=True):
    found=[]
    @CB
    def visit(hwnd,_):
        if visible_only and not u.IsWindowVisible(hwnd):
            return True
        if pid is None:
            if label(hwnd)==TITLE and label(hwnd,True)=='#32770':
                found.append(hwnd)
        elif process_id(hwnd)==pid:
            found.append(hwnd)
        return True
    u.EnumWindows(visit,0)
    return found

def hide_window(hwnd, offscreen=False):
    u.ShowWindow(hwnd, SW_HIDE)
    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOREDRAW | SWP_HIDEWINDOW
    if offscreen:
        u.SetWindowPos(hwnd, None, -32000, -32000, 1, 1, flags)
    else:
        u.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                       flags | SWP_NOMOVE | SWP_NOSIZE)

def reveal_window(hwnd):
    u.ShowWindow(hwnd, SW_SHOW)

WAIT_TITLES = (CONFIRM,)
NETHOOK_TITLE = 'NetHookCoreWindow2012'

def is_wait_dialog(hwnd):
    return label(hwnd, True) == '#32770' and label(hwnd) in WAIT_TITLES

def hide_wait_windows(pid, offscreen=False):
    for hwnd in windows(pid, visible_only=False):
        name = label(hwnd)
        if is_wait_dialog(hwnd) or name == NETHOOK_TITLE:
            hide_window(hwnd, offscreen=offscreen and is_wait_dialog(hwnd))

def reveal_select_window(pid):
    found = [hwnd for hwnd in windows(pid, visible_only=False)
             if label(hwnd) == TITLE and label(hwnd, True) == '#32770']
    if len(found) != 1:
        raise RuntimeError('无法唯一恢复游戏选择窗口')
    reveal_window(found[0])

def button(parent, control_id, caption, allow_hidden=False):
    found=[]
    @CB
    def visit(hwnd,_):
        if (u.GetParent(hwnd)==parent and (allow_hidden or u.IsWindowVisible(hwnd)) and
            u.GetDlgCtrlID(hwnd)==control_id and label(hwnd,True)=='Button' and label(hwnd)==caption):
            found.append(hwnd)
        return True
    u.EnumChildWindows(parent,visit,0)
    if len(found)!=1: raise RuntimeError('窗口布局不匹配，已停止刷新')
    return found[0]

def click(parent, pid, title, control_id, caption, allow_hidden=False):
    if process_id(parent)!=pid or label(parent)!=title or not u.IsWindowEnabled(parent):
        raise RuntimeError('窗口已变化，已停止刷新')
    target=button(parent,control_id,caption,allow_hidden=allow_hidden)
    if not u.IsWindowEnabled(target) or not u.PostMessageW(target,0xf5,0,0):
        raise RuntimeError('刷新按钮不可用')

def restore_select_if_modal_hidden(hwnd, pid):
    """Hidden search-confirm stays modal and leaves 游戏选择 disabled."""
    if u.IsWindowEnabled(hwnd):
        return False
    confirms=[h for h in windows(pid, visible_only=False) if label(h)==CONFIRM]
    if len(confirms)!=1:
        return False
    hide_window(confirms[0], offscreen=True)
    click(confirms[0], pid, CONFIRM, 1, '确定', allow_hidden=True)
    until=time.monotonic()+2
    while time.monotonic()<until and not u.IsWindowEnabled(hwnd):
        time.sleep(.02)
    if not u.IsWindowEnabled(hwnd):
        u.EnableWindow(hwnd, True)
    return True

def refresh(hwnd,pid,quiet=False):
    extras=[h for h in windows(pid) if label(h,True)=='#32770' and h!=hwnd]
    if extras and not quiet:
        raise RuntimeError('有其他游戏对话框，暂停自动刷新')
    if quiet:
        hide_wait_windows(pid)
        restore_select_if_modal_hidden(hwnd, pid)
    click(hwnd,pid,TITLE,1006,'刷新列表(&S)',allow_hidden=quiet)
    deadline=time.monotonic()+4
    dialog=None
    confirm_first_visible=None
    spin=time.monotonic()+0.5
    while time.monotonic()<deadline:
        extras=[h for h in windows(pid, visible_only=False)
                if label(h,True)=='#32770' and h!=hwnd]
        matches=[h for h in extras if label(h)==CONFIRM]
        if quiet:
            for extra in extras:
                name=label(extra)
                if name not in (CONFIRM, NETHOOK_TITLE, ''):
                    continue
                if confirm_first_visible is None and name==CONFIRM:
                    confirm_first_visible=bool(u.IsWindowVisible(extra))
                hide_window(extra, offscreen=(name!=NETHOOK_TITLE))
        if len(matches)==1:
            dialog=matches[0]
            if confirm_first_visible is None:
                confirm_first_visible=bool(u.IsWindowVisible(dialog))
            break
        if quiet:
            hide_wait_windows(pid, offscreen=True)
        if time.monotonic()<spin:
            continue
        time.sleep(.02 if quiet else .1)
    if dialog is None: raise RuntimeError('未出现已核验的搜索确认框；本轮数据不标为实时')
    if quiet:
        hide_window(dialog, offscreen=True)
    click(dialog,pid,CONFIRM,1,'确定',allow_hidden=quiet)
    if quiet:
        hide_window(dialog, offscreen=True)
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        gone = (not u.IsWindow(dialog)) if quiet else (not u.IsWindowVisible(dialog) and u.IsWindowEnabled(hwnd))
        if gone:
            time.sleep(2)
            if label(hwnd)!=TITLE or not u.IsWindow(hwnd):
                raise RuntimeError('已离开游戏选择，观察已暂停')
            return {'confirm_first_visible': confirm_first_visible}
        if quiet:
            hide_window(dialog, offscreen=True)
            hide_wait_windows(pid, offscreen=True)
        time.sleep(.02 if quiet else .1)
    raise RuntimeError('游戏搜索尚未完成，暂停刷新')

def read(h,address,size):
    if not 0x10000<=address<0x80000000 or not 0<size<=1024*1024:
        return b''
    b=c.create_string_buffer(size);got=c.c_size_t()
    if k.ReadProcessMemory(h,address,b,size,c.byref(got)) and got.value==size:return b.raw
    return b''

def records(h,hwnd):
    a=0;scanned=0;objects=[];signature=struct.pack('<I',0x500c68)
    while a<0x80000000 and scanned<128*1024*1024:
        m=MBI()
        if not k.VirtualQueryEx(h,a,c.byref(m),c.sizeof(m)):break
        base=m.BaseAddress or 0;size=m.RegionSize
        if not size or base+size<=a:break
        a=base+size
        if m.State!=0x1000 or m.Type!=0x20000 or m.Protect&0xff not in (4,8,0x40,0x80) or m.Protect&0x100:continue
        for start in range(base,base+size,1024*1024):
            data=read(h,start,min(1024*1024,base+size-start));scanned+=len(data)
            if scanned>128*1024*1024:raise RuntimeError('房间对象读取超过安全范围')
            at=data.find(signature)
            while at>=0:
                obj=read(h,start+at,0xc0)
                if len(obj)==0xc0 and struct.unpack_from('<I',obj,0x1c)[0]==hwnd:
                    objects.append((start+at,obj))
                at=data.find(signature,at+4)
    if len(objects)!=1:raise RuntimeError('无法唯一识别房间列表对象')
    address,obj=objects[0]
    pointer,count=struct.unpack_from('<II',obj,0xb0)
    if count>100:raise RuntimeError('房间列表长度异常')
    result=[]
    for i in range(count):
        p1=read(h,pointer+4*i,4)
        p2=read(h,struct.unpack('<I',p1)[0],4) if p1 else b''
        raw=read(h,struct.unpack('<I',p2)[0],80) if p2 else b''
        result.append(decode_room(raw))
    if read(h,address+0xb0,8)!=obj[0xb0:0xb8]:raise RuntimeError('列表刷新中，请稍候')
    if not u.IsWindow(hwnd) or label(hwnd)!=TITLE:raise RuntimeError('已离开游戏选择')
    return result

def open_game(target=None):
    matches=windows(visible_only=False)
    if target:
        found=choose_instances([window_candidate(hwnd) for hwnd in matches],target)
        if len(found)!=1:
            raise RuntimeError('无法定位指定实例的游戏选择窗口')
        hwnd=found[0]['hwnd']
        if not u.IsWindow(hwnd) or label(hwnd)!=TITLE or label(hwnd,True)!='#32770':
            raise RuntimeError('指定实例窗口已失效')
        if process_id(hwnd)!=found[0]['pid']:
            raise RuntimeError('指定实例进程已变化')
    else:
        visible=[h for h in matches if u.IsWindowVisible(h)]
        if len(visible)==1:
            hwnd=visible[0]
        elif len(matches)==1:
            hwnd=matches[0]
        elif not matches:
            raise RuntimeError('已离开游戏选择，观察已暂停')
        else:
            raise RuntimeError('请只打开一个游戏选择窗口')
    pid=process_id(hwnd)
    h=k.OpenProcess(0x410,False,pid)
    if not h:raise RuntimeError('无法只读访问游戏进程')
    return hwnd,pid,h

def send_timeout(hwnd, msg, wparam=0, lparam=0, ms=800, tries=3, ansi=False):
    fn=u.SendMessageTimeoutA if ansi else u.SendMessageTimeoutW
    for attempt in range(tries):
        out=c.c_size_t()
        if fn(hwnd,msg,wparam,lparam,SMTO_ABORTIFHUNG,ms,c.byref(out)):
            return int(out.value)
        if attempt+1<tries:
            time.sleep(.12)
    return None


def listbox_snapshot(parent):
    found=[]
    @CB
    def visit(hwnd,_):
        if u.GetParent(hwnd)==parent and u.GetDlgCtrlID(hwnd)==1007 and label(hwnd,True)=='ListBox':
            found.append(hwnd)
        return True
    u.EnumChildWindows(parent,visit,0)
    if len(found)!=1:
        return {'items':None,'count':None,'style':None,'unicode':None,'error':'listbox_count=%s'%len(found)}
    box=found[0]
    style=int(u.GetWindowLongW(box,-16))
    unicode=bool(u.IsWindowUnicode(box))
    ansi=not unicode
    count=send_timeout(box,LB_GETCOUNT,ansi=ansi)
    if count is None or count<0 or count>100:
        return {'items':None,'count':None,'style':style,'unicode':unicode,'error':'lb_getcount_failed'}
    items=[]
    for index in range(count):
        length=send_timeout(box,LB_GETTEXTLEN,index,ansi=ansi)
        if length is None or length<0 or length>255:
            return {'items':None,'count':count,'style':style,'unicode':unicode,'error':'lb_gettextlen_failed'}
        if ansi:
            # LB_GETTEXTLEN may count characters; GBK room titles need 2 bytes each.
            buf=c.create_string_buffer(512)
            got=send_timeout(box,LB_GETTEXT,index,c.addressof(buf),ansi=True)
            if got is None or got<0:
                return {'items':None,'count':count,'style':style,'unicode':unicode,'error':'lb_gettext_failed'}
            items.append(buf.value.decode('gbk','replace'))
        else:
            buf=c.create_unicode_buffer(length+1)
            got=send_timeout(box,LB_GETTEXT,index,c.addressof(buf))
            if got is None or got<0:
                return {'items':None,'count':count,'style':style,'unicode':unicode,'error':'lb_gettext_failed'}
            items.append(buf.value)
    return {'items':items,'count':count,'style':style,'unicode':unicode,'error':None}


def game_select_hints(hwnd):
    hints=[]
    @CB
    def visit(child,_):
        if u.GetParent(child)==hwnd and label(child,True)=='Static':
            text=label(child)
            if text:
                hints.append(text)
        return True
    u.EnumChildWindows(hwnd,visit,0)
    return hints

def control_visible(parent, control_id):
    found=[]
    @CB
    def visit(hwnd,_):
        if u.GetParent(hwnd)==parent and u.GetDlgCtrlID(hwnd)==control_id:
            found.append(bool(u.IsWindowVisible(hwnd)))
        return True
    u.EnumChildWindows(parent,visit,0)
    return found[0] if len(found)==1 else None


def game_select_layout(hwnd, pid):
    confirm_visible=False
    nethook_visible=False
    for top in windows(pid, visible_only=False):
        name=label(top)
        vis=bool(u.IsWindowVisible(top))
        if is_wait_dialog(top):
            confirm_visible=vis
        if name==NETHOOK_TITLE:
            nethook_visible=vis
    return {
        'select_visible': bool(u.IsWindowVisible(hwnd)),
        'join_visible': control_visible(hwnd, 1024),
        'create_visible': control_visible(hwnd, 1005),
        'refresh_visible': control_visible(hwnd, 1006),
        'confirm_visible': confirm_visible,
        'nethook_visible': nethook_visible,
    }


def with_ui_hints(result, hwnd, pid=None):
    hints=game_select_hints(hwnd)
    result['ui_hints']=hints
    result['ui_list']=ui_list_agreement(result.get('rooms') or [], hints)
    box=listbox_snapshot(hwnd)
    result['ui_listbox_items']=box['items']
    result['ui_listbox_count']=box['count']
    result['ui_listbox_style']=box['style']
    if box.get('unicode') is not None:
        result['ui_listbox_unicode']=box['unicode']
    if box.get('error'):
        result['ui_listbox_error']=box['error']
    result['ui_listbox']=listbox_agreement(result.get('rooms') or [], box['items'], box['count'])
    if pid is not None:
        result['ui_layout']=game_select_layout(hwnd, pid)
    result=apply_layout_freshness(result)
    if result.get('status')=='fresh' and result.get('ui_listbox')=='rooms_agree':
        result['message']=(result.get('message') or '')+'；与游戏列表人数一致'
    elif result.get('status')=='fresh' and result.get('ui_listbox')=='count_agree':
        result['message']=(result.get('message') or '')+'；与游戏列表行数一致'
    persist_compare(result)
    return result


def persist_compare(result):
    record=compare_record(result)
    if not record:
        return
    path=Path(__file__).resolve().parent.parent/'logs'/'room-watch-compare.jsonl'
    try:
        path.parent.mkdir(exist_ok=True)
        with path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n')
    except OSError:
        return

def verify_binaries(h):
    path=c.create_unicode_buffer(32768);n=w.DWORD(len(path))
    if not k.QueryFullProcessImageNameW(h,0,path,c.byref(n)):raise RuntimeError('无法验证游戏路径')
    exe=Path(path.value)
    if exe.name.lower()!='sanpk.exe' or hashlib.sha256(exe.read_bytes()).hexdigest() not in GAME_SHAS:
        raise RuntimeError('游戏版本未核验，不读取人数')
    if not is_supported_network_sha(hashlib.sha256((exe.parent/'Koeinm.dll').read_bytes()).hexdigest()):
        raise RuntimeError('联网模块版本未核验')
    return str(exe)

def snapshot(do_refresh=False, quiet=False, reveal=False, target=None):
    hwnd,pid,h=open_game(target)
    try:
        exe=verify_binaries(h)
        if reveal:
            reveal_select_window(pid)
            return with_ui_hints({'status':'cached','rooms':records(h,hwnd),'observed_at':time.time(),
                    'message':'已按请求显示游戏窗口，未重新搜索','exe':exe,
                    'scheme':'sanpk_background','quiet':False}, hwnd, pid)
        extra={}
        if do_refresh:
            extra=refresh(hwnd,pid,quiet=quiet) or {}
        rooms=records(h,hwnd)
        if quiet:
            hide_wait_windows(pid)
        result={'status':'fresh' if do_refresh else 'cached','rooms':rooms,
                'observed_at':time.time(),
                'message':('后台搜索回复人数（含房主）' if quiet else '搜索回复人数（含房主）') if do_refresh else '仅列表缓存；更新时间未知',
                'exe':exe,'scheme':'sanpk_background','quiet':bool(quiet)}
        if extra.get('confirm_first_visible') is not None:
            result['confirm_first_visible']=bool(extra['confirm_first_visible'])
        return with_ui_hints(result, hwnd, pid)
    finally:k.CloseHandle(h)

def inspect_ui(target=None):
    hwnd,pid,h=open_game(target)
    try:
        exe=verify_binaries(h)
        rows=[]
        for top in windows(pid, visible_only=False):
            children=[]
            @CB
            def visit(child,_):
                if u.GetParent(child)==top:
                    children.append({'hwnd':int(child),'id':u.GetDlgCtrlID(child),
                                     'title':label(child),'class':label(child,True),
                                     'visible':bool(u.IsWindowVisible(child)),
                                     'enabled':bool(u.IsWindowEnabled(child))})
                return True
            u.EnumChildWindows(top,visit,0)
            rows.append({'hwnd':int(top),'title':label(top),'class':label(top,True),
                         'visible':bool(u.IsWindowVisible(top)),
                         'enabled':bool(u.IsWindowEnabled(top)),'children':children})
        result={'status':'inspect','rooms':[],'observed_at':time.time(),'exe':exe,
                'scheme':'sanpk_background','windows':rows,
                'message':'只列出本进程窗口，未点击、未改声音'}
        try:
            result['rooms']=records(h,hwnd)
        except Exception as error:
            result['rooms_error']=str(error)
            result['ui_hints']=game_select_hints(hwnd)
            result['ui_layout']=game_select_layout(hwnd, pid)
            result['ui_list']='unknown'
            result['ui_listbox']='unknown'
            return result
        return with_ui_hints(result, hwnd, pid)
    finally:k.CloseHandle(h)

if __name__=='__main__':
    try:
        target=parse_target_argv(sys.argv[1:])
        if '--inspect' in sys.argv:
            result=inspect_ui(target)
        else:
            result=snapshot('--refresh' in sys.argv, quiet='--quiet' in sys.argv, reveal='--reveal' in sys.argv,
                            target=target)
        if target:
            result['instance_target']={key:target[key] for key in target}
    except Exception as error:
        result={'status':'unavailable','rooms':[], 'observed_at':time.time(),'message':str(error),
                'scheme':'sanpk_background'}
    print(json.dumps(result,ensure_ascii=False))
