import subprocess
import sys

import pytest

from chancellor.app import clipboard
from chancellor.app.clipboard import ClipboardError, copy_to_clipboard


def test_windows_uses_native_api(monkeypatch):
    copied = []
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    monkeypatch.setattr(clipboard, "_copy_windows", copied.append)

    copy_to_clipboard("Castilla á")

    assert copied == ["Castilla á"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows clipboard only")
def test_windows_round_trip():
    import ctypes

    text = "# Campaign briefing: Castilla, católico"
    copy_to_clipboard(text)

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_wchar_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    assert user32.OpenClipboard(None)
    try:
        assert kernel32.GlobalLock(user32.GetClipboardData(13)) == text
    finally:
        user32.CloseClipboard()


def test_linux_without_tools_raises(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)

    with pytest.raises(ClipboardError):
        copy_to_clipboard("x")


def test_failure_is_wrapped(monkeypatch):
    def fail(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    monkeypatch.setattr(clipboard.subprocess, "run", fail)

    with pytest.raises(ClipboardError):
        copy_to_clipboard("x")
