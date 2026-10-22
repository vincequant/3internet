"""Dock / taskbar icons for Hub, Wine navigation, and panorama. Never raises."""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path

NAMES = ('hub', 'wine', 'map')
ICONS = Path(__file__).resolve().parent / 'assets' / 'icons'
_PHOTOS = []


def icon_path(name='hub'):
    if name not in NAMES:
        return None
    path = ICONS / f'{name}.png'
    return path if path.is_file() else None


def apply(root=None, name='hub'):
    try:
        _apply(root, name)
    except Exception:
        return


def _apply(root, name):
    if name not in NAMES:
        return
    if sys.platform == 'win32':
        _windows_app_id(name)
    path = icon_path(name)
    if root is not None and path is not None:
        _iconphoto(root, path)
    if path is None:
        return
    if sys.platform == 'darwin':
        _macos_dock_icon(path)  # uses existing NSApp only; never sharedApplication before Tk


def _iconphoto(root, path):
    import tkinter as tk
    try:
        photo = tk.PhotoImage(master=root, file=str(path))
    except tk.TclError:
        from PIL import Image, ImageTk
        photo = ImageTk.PhotoImage(Image.open(path), master=root)
    root.iconphoto(True, photo)
    root._sgi_dock_icon = photo
    _PHOTOS.append(photo)


def _windows_app_id(name):
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        ctypes.c_wchar_p(f'com.vk.sgi.{name}'))


def _existing_nsapp():
    try:
        appkit = ctypes.CDLL('/System/Library/Frameworks/AppKit.framework/AppKit')
        return ctypes.c_void_p.in_dll(appkit, 'NSApp').value
    except (OSError, ValueError, AttributeError):
        return None


def _macos_dock_icon(path):
    # Do not call +[NSApplication sharedApplication] ourselves: a vanilla
    # NSApplication created before Tk() makes Tk 9 abort (macOSVersion).
    app = _existing_nsapp()
    if not app:
        return
    objc_path = ctypes.util.find_library('objc')
    if not objc_path:
        return
    objc = ctypes.cdll.LoadLibrary(objc_path)
    ctypes.CDLL('/System/Library/Frameworks/Foundation.framework/Foundation')
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def cls(name):
        return objc.objc_getClass(name.encode('ascii'))

    def sel(name):
        return objc.sel_registerName(name.encode('ascii'))

    send0 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
    send1 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
    sendp = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)(('objc_msgSend', objc))
    ns_path = sendp(cls('NSString'), sel('stringWithUTF8String:'), os.fsencode(os.fsdecode(path)))
    image = send1(send0(cls('NSImage'), sel('alloc')), sel('initWithContentsOfFile:'), ns_path)
    if image:
        send1(app, sel('setApplicationIconImage:'), image)
