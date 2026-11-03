"""Copying secrets to the Windows clipboard without leaving copies behind.

Tk's clipboard puts plain text there, which Windows then keeps in the
clipboard history (Win+V) and may sync to other devices (cloud clipboard).
For passwords we write the text ourselves and add the formats Windows and
clipboard managers honour to skip it:

- ExcludeClipboardContentFromMonitorProcessing: clipboard managers ignore it,
- CanIncludeInClipboardHistory = 0: not stored in the Win+V history,
- CanUploadToCloudClipboard = 0: not synced to other devices.

https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats#cloud-clipboard-and-clipboard-history-formats
"""

from __future__ import annotations

import sys
import time

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def copy_private(text: str) -> bool:
    """Puts text on the clipboard, hidden from history and cloud sync.

    Returns False when this is not possible (not Windows, clipboard busy);
    the caller then falls back to the normal clipboard."""
    if sys.platform != "win32":
        return False
    try:
        return _copy_private_win32(text)
    except OSError:
        return False


def _copy_private_win32(text: str) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    def global_bytes(data: bytes):
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise OSError("GlobalAlloc failed")
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            raise OSError("GlobalLock failed")
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        return handle

    def put(fmt: int, data: bytes) -> None:
        handle = global_bytes(data)
        if not user32.SetClipboardData(fmt, handle):
            kernel32.GlobalFree(handle)  # only freed by us when the clipboard did not take it
            raise OSError("SetClipboardData failed")

    # Another program may hold the clipboard for a moment.
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return False
    try:
        if not user32.EmptyClipboard():
            return False
        put(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
        zero = (0).to_bytes(4, "little")
        for name, data in (
            ("ExcludeClipboardContentFromMonitorProcessing", zero),
            ("CanIncludeInClipboardHistory", zero),
            ("CanUploadToCloudClipboard", zero),
        ):
            fmt = user32.RegisterClipboardFormatW(name)
            if fmt:
                put(fmt, data)
        return True
    finally:
        user32.CloseClipboard()
