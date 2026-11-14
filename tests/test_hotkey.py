import sys

import pytest

from chancellor.app.hotkey import GlobalHotkey, HotkeyError, describe_hotkey, parse_hotkey


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ctrl+shift+space", (0x0002 | 0x0004, 0x20)),
        ("Alt + F9", (0x0001, 0x78)),
        ("win+c", (0x0008, ord("C"))),
        ("ctrl+alt+1", (0x0002 | 0x0001, ord("1"))),
    ],
)
def test_parse_hotkey(text: str, expected: tuple[int, int]):
    assert parse_hotkey(text) == expected


@pytest.mark.parametrize("text", ["ctrl+shift", "ctrl+a+b", "ctrl+ñ", "ctrl+banana"])
def test_parse_hotkey_rejects_bad_shortcuts(text: str):
    with pytest.raises(HotkeyError):
        parse_hotkey(text)


def test_describe_hotkey():
    assert describe_hotkey("ctrl+shift+space") == "Ctrl+Shift+Space"


def test_hotkey_is_not_registered_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    hotkey = GlobalHotkey("ctrl+shift+space", lambda: None)
    assert hotkey.start() is False
    assert hotkey.registered is False


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 hotkeys")
def test_hotkey_registers_and_stops_on_windows():
    # An unusual combination, so it does not clash with a shortcut on the machine.
    hotkey = GlobalHotkey("ctrl+alt+shift+f12", lambda: None)
    try:
        assert hotkey.start() is True
    finally:
        hotkey.stop()
    assert hotkey._thread is not None
    hotkey._thread.join(2)
    assert not hotkey._thread.is_alive()
