"""Fengye-only application branding; never changes the other SGI apps' icons.

Call ``apply(root)`` after creating Tk. A header can use
``photo = logo_photo(parent, 44)`` and retain ``photo`` on its label.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys

ASSETS = Path(__file__).resolve().parent / 'assets'
ICON = ASSETS / 'fengye-icon.png'
SMALL_ICON = ASSETS / 'fengye-icon-256.png'
APP_ID = 'com.vk.sgi.fengye-omni-hub'


def logo_photo(master, size=44):
    """Return a size-only derivative for a Tk header, or None if unavailable."""
    try:
        from PIL import Image, ImageTk
        with Image.open(ICON) as image:
            image = image.convert('RGBA').resize(
                (int(size), int(size)), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image, master=master)
    except Exception:
        return None


def apply(root):
    """Apply Fengye's icon to this Tk app and its native Dock/taskbar identity."""
    try:
        import tkinter as tk
        # An independent PNG works for Windows/Linux too; retain its Tk object.
        photo = tk.PhotoImage(master=root, file=str(SMALL_ICON))
        root.iconphoto(True, photo)
        root._fengye_icon_photo = photo
    except Exception:
        pass
    if sys.platform == 'win32':
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                ctypes.c_wchar_p(APP_ID))
        except Exception:
            pass
    elif sys.platform == 'darwin':
        try:
            # Reuse the existing NSApp-safe setter only. Never create an NSApp
            # before Tk (Tk 9 aborts), and do not mutate shared icon assets.
            from dock_icon import _macos_dock_icon
            _macos_dock_icon(ICON)
        except Exception:
            pass
