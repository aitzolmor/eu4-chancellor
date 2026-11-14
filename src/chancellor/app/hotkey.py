"""A system-wide keyboard shortcut for the panel (UI_DESIGN, build order step 5).

Windows delivers a hotkey registered with ``RegisterHotKey`` as a ``WM_HOTKEY`` message
to the thread that registered it, whichever window is in front, so the shortcut works
while the game has the keyboard. The registering thread therefore runs its own message
loop; :meth:`GlobalHotkey.stop` ends it.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable

DEFAULT_HOTKEY = "ctrl+shift+space"

_MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
_MOD_NOREPEAT = 0x4000  # one message per press, not one per auto-repeat
_NAMED_KEYS = {
    "space": 0x20,
    "tab": 0x09,
    "home": 0x24,
    "end": 0x23,
    "insert": 0x2D,
    "pause": 0x13,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
}
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_HOTKEY_ID = 1


class HotkeyError(ValueError):
    """A shortcut that cannot be read or registered."""


def parse_hotkey(text: str) -> tuple[int, int]:
    """Turn ``ctrl+shift+space`` into Win32 ``(modifiers, virtual key)``.

    Args:
        text: Modifiers and one key joined by ``+``: ``alt``, ``ctrl``, ``shift``,
            ``win``; a letter, a digit, ``f1``-``f12`` or a named key such as ``space``.

    Raises:
        HotkeyError: If the text has no key, two keys or an unknown name.
    """
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    modifiers, keys = 0, []
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
        else:
            keys.append(part)
    if len(keys) != 1:
        raise HotkeyError(f"'{text}' needs exactly one key besides the modifiers.")
    key = keys[0]
    if key in _NAMED_KEYS:
        return modifiers, _NAMED_KEYS[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return modifiers, ord(key.upper())
    raise HotkeyError(f"Unknown key '{key}' in '{text}'.")


def describe_hotkey(text: str) -> str:
    """``ctrl+shift+space`` → ``Ctrl+Shift+Space``, for the page."""
    return "+".join(part.strip().capitalize() for part in text.split("+"))


class GlobalHotkey:
    """Calls ``action`` whenever the shortcut is pressed, until :meth:`stop`."""

    def __init__(self, text: str, action: Callable[[], object]) -> None:
        """Prepare the shortcut (nothing is registered until :meth:`start`).

        Raises:
            HotkeyError: If ``text`` is not a valid shortcut.
        """
        self.text = text
        self._modifiers, self._key = parse_hotkey(text)
        self._action = action
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.registered = False

    def start(self, timeout: float = 2.0) -> bool:
        """Register the shortcut on a background thread.

        Returns:
            Whether Windows accepted it; another program may already use it.
        """
        if sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.registered

    def stop(self) -> None:
        """Unregister the shortcut and end the message loop."""
        if self._thread_id:
            user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
            user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)

    def _run(self) -> None:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._thread_id = kernel32.GetCurrentThreadId()
        self.registered = bool(
            user32.RegisterHotKey(None, _HOTKEY_ID, self._modifiers | _MOD_NOREPEAT, self._key)
        )
        self._ready.set()
        if not self.registered:
            return
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == _WM_HOTKEY and message.wParam == _HOTKEY_ID:
                    try:
                        self._action()
                    except Exception:  # noqa: BLE001 - a failed action must not end the loop
                        continue
        finally:
            user32.UnregisterHotKey(None, _HOTKEY_ID)
