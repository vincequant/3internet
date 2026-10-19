#!/usr/bin/env python3
"""Own-window synthetic Win32 GUI test. Never discovers/opens SANPK.

PostMessage, SendMessage, PrintWindow and foreground changes target ONLY windows
created in this test process. The fixture is explicitly labelled synthetic.
"""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_p53_unit_data import Fixture, VIEW
from p53_unit_data import context, capture_map, inspect_unit, world_to_pixel
from p53_unit_inspector import InspectorUI, native_api


def own_window_bmp(u,g,hwnd,path):
    u.GetWindowDC.argtypes=[W.HWND];u.GetWindowDC.restype=W.HDC
    u.ReleaseDC.argtypes=[W.HWND,W.HDC];u.ReleaseDC.restype=C.c_int
    u.PrintWindow.argtypes=[W.HWND,W.HDC,W.UINT];u.PrintWindow.restype=W.BOOL
    g.CreateCompatibleDC.argtypes=[W.HDC];g.CreateCompatibleDC.restype=W.HDC
    g.CreateCompatibleBitmap.argtypes=[W.HDC,C.c_int,C.c_int];g.CreateCompatibleBitmap.restype=W.HBITMAP
    g.SelectObject.argtypes=[W.HDC,W.HANDLE];g.SelectObject.restype=W.HANDLE
    g.GetDIBits.argtypes=[W.HDC,W.HBITMAP,W.UINT,W.UINT,C.c_void_p,C.c_void_p,W.UINT]
    g.GetDIBits.restype=C.c_int
    g.DeleteObject.argtypes=[W.HANDLE];g.DeleteObject.restype=W.BOOL
    g.DeleteDC.argtypes=[W.HDC];g.DeleteDC.restype=W.BOOL
    rect=W.RECT()
    if not u.GetWindowRect(hwnd,C.byref(rect)):raise C.WinError(C.get_last_error())
    width,height=rect.right-rect.left,rect.bottom-rect.top
    window=u.GetWindowDC(hwnd);dc=g.CreateCompatibleDC(window)
    bitmap=g.CreateCompatibleBitmap(window,width,height);previous=g.SelectObject(dc,bitmap)
    try:
        if not u.PrintWindow(hwnd,dc,0):raise RuntimeError('own PrintWindow failed')
        g.SelectObject(dc,previous)
        pixels=C.create_string_buffer(width*height*4)
        header=struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,len(pixels),0,0,0,0)
        info=C.create_string_buffer(header)
        if g.GetDIBits(dc,bitmap,0,height,pixels,info,0)!=height:raise RuntimeError('GetDIBits failed')
        fileheader=struct.pack('<2sIHHI',b'BM',54+len(pixels),0,0,54)
        pixeldata=pixels.raw
        path.write_bytes(fileheader+header+pixeldata)
        return dict(width=width,height=height,nonblack_pixels=sum(
            any(pixeldata[i:i+3]) for i in range(0,len(pixeldata),4)))
    finally:
        g.SelectObject(dc,previous);g.DeleteObject(bitmap);g.DeleteDC(dc);u.ReleaseDC(hwnd,window)


def main():
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    u,k,g=native_api();fixture=Fixture();events=[]
    k.GetCurrentProcessId.restype=W.DWORD
    class SyntheticReader:
        identity=dict(pid=int(k.GetCurrentProcessId()),source='synthetic_own_window_fixture')
        def geometry(self):return context(fixture.read)
        def capture(self):return capture_map(fixture.read)
        def inspect(self,snap,row):return inspect_unit(fixture.read,snap,row)
    class SmokeUI(InspectorUI):
        mock=0;mock_clicks=0
        def window_proc(self,hwnd,msg,wp,lp):
            if self.mock and hwnd==self.mock and msg in (0x201,0x203,0x204,0x20a):
                self.mock_clicks+=1
            if hwnd==self.panel and msg==0x8001:
                try:
                    self.started_disarmed=not self.armed
                    u.SetForegroundWindow(self.mock)
                    self.set_armed(True)
                    if not self.last_geometry:raise RuntimeError('own fixture overlay did not arm')
                    dims=self.last_geometry['context']['dimensions']
                    p=world_to_pixel(8,17,dims)
                    self.point=[p[0]+dims[2]//2-120,p[1]+dims[3]//4-210]
                    origin=self.last_geometry['origin']
                    screen=W.POINT(origin[0]+self.point[0],origin[1]+self.point[1])
                    u.WindowFromPoint.argtypes=[W.POINT];u.WindowFromPoint.restype=W.HWND
                    self.physical_hit=int(u.WindowFromPoint(screen) or 0)
                    self.hit_client=int(u.SendMessageW(self.overlay,0x84,0,
                                          (screen.y<<16)|(screen.x & 65535)))
                    u.PostMessageW(self.overlay,0x201,0,(self.point[1]<<16)|self.point[0])
                    for message in (0x203,0x204,0x20a):
                        u.PostMessageW(self.overlay,message,0,(self.point[1]<<16)|self.point[0])
                    rect=W.RECT();u.GetWindowRect(self.panel,C.byref(rect))
                    (out/'gui-ready.json').write_text(json.dumps(dict(
                        rect=[rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top],
                        own_windows_only=True)),encoding='utf-8')
                    # A short finite hold also permits a macOS backing-store
                    # screenshot; Wine PrintWindow can return a black bitmap.
                    u.SetTimer(self.panel,2,6000,None)
                except BaseException as exc:
                    self.failure=str(exc);u.PostMessageW(self.panel,0x8002,0,0)
                return 0
            if hwnd==self.panel and ((msg==0x113 and wp==2) or msg==0x8002):
                u.KillTimer(self.panel,2)
                try:
                    u.GetWindowTextLengthW.argtypes=[W.HWND];u.GetWindowTextLengthW.restype=C.c_int
                    u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int];u.GetWindowTextW.restype=C.c_int
                    length=u.GetWindowTextLengthW(self.edit);buf=C.create_unicode_buffer(length+1)
                    u.GetWindowTextW(self.edit,buf,length+1)
                    inspection=[e for e in events if e.get('kind')=='unit_inspection']
                    u.GetWindowLongW.argtypes=[W.HWND,C.c_int];u.GetWindowLongW.restype=W.LONG
                    evidence=dict(schema='p53-inspector-gui-smoke-1',source='synthetic_own_window_fixture',
                        game_opened=False,started_disarmed=getattr(self,'started_disarmed',False),
                        overlay=int(self.overlay),physical_hit=getattr(self,'physical_hit',None),
                        hit_is_overlay=getattr(self,'physical_hit',None)==self.overlay,
                        hit_client=getattr(self,'hit_client',None),
                        edit_readonly=bool(u.GetWindowLongW(self.edit,-16)&0x800),
                        click_count_in_mock_game=self.mock_clicks,
                        inspections=len(inspection),panel_text=buf.value,
                        errors=[e for e in events if e.get('kind')=='inspector_error'],failure=getattr(self,'failure',None))
                    u.UpdateWindow.argtypes=[W.HWND];u.UpdateWindow.restype=W.BOOL
                    for owned in (self.panel,self.edit,self.button,self.refresh):u.UpdateWindow(owned)
                    evidence['capture']=own_window_bmp(u,g,self.panel,out/'synthetic-panel.bmp')
                    self.set_armed(False)
                    evidence['overlay_hidden_on_stop']=not bool(u.IsWindowVisible(self.overlay))
                    evidence['passed']=bool(evidence['started_disarmed'] and evidence['hit_is_overlay'] and
                        evidence['hit_client']==1 and evidence['edit_readonly'] and self.mock_clicks==0 and
                        len(inspection)==1 and not evidence['errors'] and not evidence['failure'] and
                        '12345' in buf.value and '合成敌方' in buf.value and evidence['overlay_hidden_on_stop'])
                    evidence['win32_printwindow_has_pixels']=evidence['capture']['nonblack_pixels']>10000
                    (out/'gui-smoke.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                except BaseException as exc:
                    (out/'gui-smoke-error.txt').write_text(str(exc),encoding='utf-8')
                self.close();u.DestroyWindow(self.mock);return 0
            return super().window_proc(hwnd,msg,wp,lp)
    try:
        app=SmokeUI(SyntheticReader(),events.append,u,k,g)
    except BaseException:
        (out/'constructor-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    app.mock=app.create(0,app.class_name,'P53 合成地图 · 不连接游戏',0x00cf0000,60,60,980,680)
    fixture.put(VIEW+0x1c,app.mock)
    u.ShowWindow(app.mock,5)
    u.PostMessageW(app.panel,0x8001,0,0)
    app.loop()
    evidence=json.loads((out/'gui-smoke.json').read_text(encoding='utf-8'))
    print(json.dumps({key:evidence[key] for key in ('source','game_opened','passed','inspections','click_count_in_mock_game')},ensure_ascii=False))
    if not evidence['passed']:raise SystemExit(1)


if __name__=='__main__':main()
