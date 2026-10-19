"""Read visible monitor-prefix windows; optional single verified start-button click."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
import sys

assert os.environ.get('WINEPREFIX') == '/Users/vkquant/Library/Application Support/SGI-Wine/prefix-monitor', 'Remote monitor prefix only'

u=c.WinDLL('user32',use_last_error=True)
k=c.WinDLL('kernel32',use_last_error=True)
CB=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
u.EnumWindows.argtypes=[CB,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,CB,w.LPARAM]
u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
u.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,c.c_int]
u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,c.c_int]
u.IsWindowVisible.argtypes=[w.HWND]
u.IsWindowEnabled.argtypes=[w.HWND]
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]
k.OpenProcess.restype=w.HANDLE
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
k.CloseHandle.argtypes=[w.HANDLE]
u.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
rows=[]
buttons=[]

def label(hwnd,cls=False):
    b=c.create_unicode_buffer(512)
    (u.GetClassNameW if cls else u.GetWindowTextW)(hwnd,b,len(b))
    return b.value

@CB
def visit(hwnd,_):
    if not u.IsWindowVisible(hwnd):return True
    pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,c.byref(pid))
    h=k.OpenProcess(0x1000,False,pid.value)
    if not h:return True
    b=c.create_unicode_buffer(32768);n=w.DWORD(len(b))
    try:
        if not k.QueryFullProcessImageNameW(h,0,b,c.byref(n)):return True
    finally:k.CloseHandle(h)
    exe=b.value
    if not exe.lower().endswith(('\\sanguo.exe','\\sanpk.exe')):return True
    row={'hwnd':hwnd,'pid':pid.value,'exe':exe,'title':label(hwnd),'controls':[]}
    @CB
    def child(ch,_):
        if not u.IsWindowVisible(ch):return True
        cls=label(ch,True)
        if 'edit' in cls.lower():return True
        title=label(ch)
        if title:row['controls'].append({'hwnd':ch,'class':cls,'title':title})
        if exe.lower().endswith('\\sanguo.exe') and title=='启动游戏' and u.IsWindowEnabled(ch):
            buttons.append(ch)
        return True
    u.EnumChildWindows(hwnd,child,0);rows.append(row)
    return True

u.EnumWindows(visit,0)
print(json.dumps({'windows':rows},ensure_ascii=False),flush=True)
if '--close-alt-lobby' in sys.argv:
    assert not any(r['exe'].lower().endswith('\\sanpk.exe') for r in rows), 'Game must already be closed'
    own=[r for r in rows if r['exe'].lower()=='c:\\sgi\\run-3.5\\sanguo.exe'
         and r['title']=='三国志Internet对战平台 6.2 [当前用户: vinceost]']
    assert len(own)==1, 'Expected exact second-Mac alt account'
    assert u.PostMessageW(own[0]['hwnd'],0x10,0,0)
    print(json.dumps({'close_requested_alt_lobby':own[0]['pid']}),flush=True)
if '--start' in sys.argv:
    assert len(buttons)==1, 'Requires exactly one enabled monitor start button'
    assert u.PostMessageW(buttons[0],0xf5,0,0)
    print(json.dumps({'clicked_start':buttons[0]}),flush=True)
if '--close-test-pid' in sys.argv:
    pid=int(sys.argv[sys.argv.index('--close-test-pid')+1])
    own=[r for r in rows if r['pid']==pid and r['exe'].lower().endswith('\\sanpk.exe')]
    assert any(r['title']=='游戏选择' for r in own), 'Refuse to close an instance outside game selection'
    targets=[r for r in own if r['title']=='三国志Internet联机版3.5']
    assert len(targets)==1
    assert u.PostMessageW(targets[0]['hwnd'],0x10,0,0)
    print(json.dumps({'close_requested_test_pid':pid}),flush=True)
