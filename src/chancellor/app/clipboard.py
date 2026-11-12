"""Copy text to the system clipboard using the platform's built-in tools."""

from __future__ import annotations

import shutil
import subprocess
import sys


class ClipboardError(RuntimeError):
    """Raised when no clipboard tool is available or copying fails."""


def copy_to_clipboard(text: str) -> None:
    """Place ``text`` on the clipboard.

    Uses the Win32 clipboard API on Windows, ``pbcopy`` on macOS and
    ``wl-copy``/``xclip``/``xsel`` on Linux, so no third-party dependency is needed.

    Args:
        text: Text to copy.

    Raises:
        ClipboardError: If no supported tool is found or it fails.
    """
    if sys.platform == "win32":
        _copy_windows(text)
        return
    if sys.platform == "darwin":
        command, data = ["pbcopy"], text.encode("utf-8")
    else:
        candidates = (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"])
        found = next((c for c in candidates if shutil.which(c[0])), None)
        if found is None:
            raise ClipboardError("No clipboard tool found (install wl-copy, xclip or xsel)")
        command, data = found, text.encode("utf-8")

    try:
        subprocess.run(command, input=data, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ClipboardError(f"Copying to the clipboard failed: {exc}") from exc


def _copy_windows(text: str) -> None:
    """Copy via the Win32 API as CF_UNICODETEXT.

    ``clip.exe`` is avoided because it either mangles non-ASCII text or, when fed UTF-16,
    keeps the byte order mark as a visible character.
    """
    import ctypes
    from ctypes import wintypes

    cf_unicodetext = 13
    gmem_moveable = 0x0002
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise ClipboardError("Could not open the clipboard (is another app using it?)")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
        if not handle:
            raise ClipboardError("Could not allocate clipboard memory")
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(cf_unicodetext, handle):
            kernel32.GlobalFree(handle)
            raise ClipboardError("Could not set clipboard data")
    finally:
        user32.CloseClipboard()
