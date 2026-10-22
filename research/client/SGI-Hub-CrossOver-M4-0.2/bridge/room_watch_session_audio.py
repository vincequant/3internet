"""List or mute SANPK's Windows audio session. No injection, no system volume."""
import ctypes
from ctypes import wintypes
import json
import sys

ole32 = ctypes.windll.ole32
ole32.CoInitialize(None)

class GUID(ctypes.Structure):
    _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

    def __init__(self, text='{00000000-0000-0000-0000-000000000000}'):
        u = text.strip('{}').split('-')
        self.Data1 = int(u[0], 16)
        self.Data2 = int(u[1], 16)
        self.Data3 = int(u[2], 16)
        blob = bytes.fromhex(u[3] + u[4])
        self.Data4 = (ctypes.c_ubyte * 8)(*blob)

def guid(text):
    return GUID(text)

CLSID_MM = guid('{BCDE0395-E52F-467C-8E3D-C4579291692E}')
IID_ENUM = guid('{A95664D2-9614-4F35-A746-DE8DB63617E6}')
IID_DEV = guid('{D666063F-1587-4E43-81F1-B948E807363F}')
IID_SM2 = guid('{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}')
IID_SE = guid('{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}')
IID_SC2 = guid('{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}')
IID_VOL = guid('{87CE5498-68D6-44E5-9215-6DA47EF883D8}')
IID_UNK = guid('{00000000-0000-0000-C000-000000000046}')

eRender = 0
eMultimedia = 1
CLSCTX_ALL = 23

class IUnknown(ctypes.Structure):
    pass

def vtable(obj, index, restype, *argtypes):
    ptr = ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))
    vt = ctypes.cast(ptr[0], ctypes.POINTER(ctypes.c_void_p))
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vt[index])
    return lambda *a: fn(obj, *a)

def com_create(clsid, iid):
    unk = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid), ctypes.byref(unk))
    return hr, unk

def release(obj):
    if obj and obj.value:
        vtable(obj, 2, ctypes.HRESULT)()

def query(obj, iid):
    out = ctypes.c_void_p()
    hr = vtable(obj, 0, ctypes.HRESULT, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(iid), ctypes.byref(out))
    return hr, out

def snapshot_processes():
    k = ctypes.windll.kernel32
    class E(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_char * 260)]
    snap = k.CreateToolhelp32Snapshot(2, 0)
    rows = {}
    if snap == ctypes.c_void_p(-1).value:
        return rows
    e = E(); e.dwSize = ctypes.sizeof(E)
    if k.Process32First(snap, ctypes.byref(e)):
        while True:
            name = e.szExeFile.split(b'\0', 1)[0].decode('ascii', 'replace')
            rows[int(e.th32ProcessID)] = name
            if not k.Process32Next(snap, ctypes.byref(e)):
                break
    k.CloseHandle(snap)
    return rows

def list_mixer():
    winmm = ctypes.windll.winmm
    n = winmm.mixerGetNumDevs()
    waves = winmm.waveOutGetNumDevs()
    caps = []
    class MIXERCAPS(ctypes.Structure):
        _fields_ = [('wMid', wintypes.WORD), ('wPid', wintypes.WORD),
                    ('vDriverVersion', wintypes.DWORD), ('szPname', wintypes.WCHAR * 32),
                    ('fdwSupport', wintypes.DWORD), ('cDestinations', wintypes.DWORD)]
    for i in range(n):
        c = MIXERCAPS()
        hr = winmm.mixerGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c))
        caps.append({'index': i, 'hr': hr, 'name': c.szPname, 'destinations': c.cDestinations})
    return {'mixer_devices': n, 'wave_out_devices': waves, 'caps': caps}

def sessions():
    procs = snapshot_processes()
    hr, enum = com_create(CLSID_MM, IID_ENUM)
    if hr or not enum.value:
        return {'ok': False, 'step': 'CoCreateInstance IMMDeviceEnumerator', 'hr': hr, 'mixer': list_mixer()}
    get_default = vtable(enum, 4, ctypes.HRESULT, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    dev = ctypes.c_void_p()
    hr = get_default(eRender, eMultimedia, ctypes.byref(dev))
    if hr or not dev.value:
        release(enum)
        return {'ok': False, 'step': 'GetDefaultAudioEndpoint', 'hr': hr, 'mixer': list_mixer()}
    activate = vtable(dev, 3, ctypes.HRESULT, ctypes.POINTER(GUID), ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    mgr = ctypes.c_void_p()
    hr = activate(ctypes.byref(IID_SM2), CLSCTX_ALL, None, ctypes.byref(mgr))
    if hr or not mgr.value:
        release(dev); release(enum)
        return {'ok': False, 'step': 'Activate IAudioSessionManager2', 'hr': hr, 'mixer': list_mixer()}
    get_enum = vtable(mgr, 5, ctypes.HRESULT, ctypes.POINTER(ctypes.c_void_p))
    sess_enum = ctypes.c_void_p()
    hr = get_enum(ctypes.byref(sess_enum))
    if hr or not sess_enum.value:
        release(mgr); release(dev); release(enum)
        return {'ok': False, 'step': 'GetSessionEnumerator', 'hr': hr, 'mixer': list_mixer()}
    get_count = vtable(sess_enum, 3, ctypes.HRESULT, ctypes.POINTER(ctypes.c_int))
    count = ctypes.c_int()
    hr = get_count(ctypes.byref(count))
    rows = []
    get_session = vtable(sess_enum, 4, ctypes.HRESULT, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    for i in range(count.value):
        ctl = ctypes.c_void_p()
        if get_session(i, ctypes.byref(ctl)):
            continue
        hr2, ctl2 = query(ctl, IID_SC2)
        target = ctl2 if not hr2 and ctl2.value else ctl
        display = ctypes.c_wchar_p()
        # IAudioSessionControl GetDisplayName is index 4 on v1; on v2 inherited
        get_name = vtable(target, 4, ctypes.HRESULT, ctypes.POINTER(ctypes.c_wchar_p))
        get_name(ctypes.byref(display))
        pid = wintypes.DWORD(0)
        # IAudioSessionControl2 GetProcessId is typically vtable 14 after IAudioSessionControl
        get_pid = vtable(target, 14, ctypes.HRESULT, ctypes.POINTER(wintypes.DWORD))
        phr = get_pid(ctypes.byref(pid))
        vol = None
        muted = None
        hr3, simple = query(target, IID_VOL)
        if not hr3 and simple.value:
            get_mute = vtable(simple, 5, ctypes.HRESULT, ctypes.POINTER(ctypes.c_int))
            flag = ctypes.c_int()
            if not get_mute(ctypes.byref(flag)):
                muted = bool(flag.value)
            release(simple)
        rows.append({
            'index': i, 'pid': int(pid.value), 'pid_hr': phr,
            'exe': procs.get(int(pid.value), ''),
            'name': display.value if display else '',
            'muted': muted,
        })
        if target is not ctl:
            release(ctl2)
        release(ctl)
    release(sess_enum); release(mgr); release(dev); release(enum)
    return {'ok': True, 'count': count.value, 'sessions': rows, 'processes': procs, 'mixer': list_mixer()}

def set_sanpk_mute(mute):
    info = sessions()
    if not info.get('ok'):
        return info
    changed = []
    # Re-open and mute matching sessions. Compact: reuse listing then second pass.
    hr, enum = com_create(CLSID_MM, IID_ENUM)
    dev = ctypes.c_void_p()
    vtable(enum, 4, ctypes.HRESULT, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(eRender, eMultimedia, ctypes.byref(dev))
    mgr = ctypes.c_void_p()
    vtable(dev, 3, ctypes.HRESULT, ctypes.POINTER(GUID), ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(IID_SM2), CLSCTX_ALL, None, ctypes.byref(mgr))
    sess_enum = ctypes.c_void_p()
    vtable(mgr, 5, ctypes.HRESULT, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(sess_enum))
    count = ctypes.c_int()
    vtable(sess_enum, 3, ctypes.HRESULT, ctypes.POINTER(ctypes.c_int))(ctypes.byref(count))
    get_session = vtable(sess_enum, 4, ctypes.HRESULT, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    for i in range(count.value):
        ctl = ctypes.c_void_p()
        if get_session(i, ctypes.byref(ctl)):
            continue
        hr2, ctl2 = query(ctl, IID_SC2)
        target = ctl2 if not hr2 and ctl2.value else ctl
        pid = wintypes.DWORD(0)
        vtable(target, 14, ctypes.HRESULT, ctypes.POINTER(wintypes.DWORD))(ctypes.byref(pid))
        exe = info['processes'].get(int(pid.value), '').lower()
        if exe == 'sanpk.exe':
            hr3, simple = query(target, IID_VOL)
            if not hr3 and simple.value:
                hr4 = vtable(simple, 3, ctypes.HRESULT, ctypes.c_int, ctypes.c_void_p)(1 if mute else 0, None)
                changed.append({'pid': int(pid.value), 'set_mute': mute, 'hr': hr4})
                release(simple)
        if target is not ctl:
            release(ctl2)
        release(ctl)
    release(sess_enum); release(mgr); release(dev); release(enum)
    info['changed'] = changed
    info['action'] = 'mute' if mute else 'unmute'
    return info

if __name__ == '__main__':
    action = 'list'
    if '--mute' in sys.argv:
        action = 'mute'
    elif '--unmute' in sys.argv:
        action = 'unmute'
    try:
        if action == 'list':
            result = sessions()
        else:
            result = set_sanpk_mute(action == 'mute')
        result['status'] = 'ok' if result.get('ok') else 'unavailable'
    except Exception as error:
        result = {'status': 'unavailable', 'message': str(error)}
    print(json.dumps(result, ensure_ascii=False))
