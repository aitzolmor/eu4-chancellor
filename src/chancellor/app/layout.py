"""Arrange the Chancellor panel and Claude Desktop around the game (D-006, D-022).

Build order step 4. Windows are found by their process and moved with Win32 calls
through ``ctypes`` (``SetWindowPos``); nothing is reparented or embedded, and the game's
window is never moved: EU4 runs borderless at its own resolution and ignores resizing.

* With two screens the panel and Claude Desktop are **docked** on the screen the game is
  not on.
* With one screen they form an **overlay** column on top of the game, on the side of the
  floating icon (:mod:`chancellor.app.icon_window`), and are put away again when the
  player closes it.

:func:`plan_layout` decides where each window goes from the monitors alone. It is a pure
function, so every layout rule is tested without touching real windows. :class:`Docker`
finds the windows, remembers where they were, applies a plan and puts everything back.

Coordinates are physical pixels. The process must be per-monitor DPI aware
(:func:`enable_dpi_awareness`, called before any window exists), or Windows scales the
numbers on the 150% screen and windows land in the wrong place.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any

GAME_EXE = "eu4.exe"
CLAUDE_EXE = "claude.exe"
# Two screens: the panel takes a third of the second one, Claude Desktop the rest.
PANEL_WIDTH_SHARE = 1 / 3
# One screen: an overlay column of 40% of the width, the panel on top (40% of the
# height) and Claude Desktop below. Claude Desktop will not go narrower than about 600
# logical pixels, so the column widens to whatever it accepts (Docker measures it).
OVERLAY_WIDTH_SHARE = 0.40
PANEL_HEIGHT_SHARE = 0.40


@dataclass(frozen=True)
class Rect:
    """A screen rectangle in physical pixels."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        """One past the last column."""
        return self.left + self.width

    @property
    def bottom(self) -> int:
        """One past the last row."""
        return self.top + self.height

    def contains(self, x: int, y: int) -> bool:
        """Whether a point lies inside the rectangle."""
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass(frozen=True)
class Monitor:
    """One display as Windows reports it.

    Attributes:
        name: Windows device name of the display (its ``szDevice``).
        area: The whole monitor.
        work: The monitor without the taskbar.
        dpi: Effective DPI (96 = 100% scaling, 144 = 150%).
        primary: Whether it is the primary monitor.
    """

    name: str
    area: Rect
    work: Rect
    dpi: int
    primary: bool


@dataclass(frozen=True)
class Layout:
    """Where the panel and Claude Desktop go.

    Attributes:
        mode: ``two_screens`` (docked on the other screen) or ``overlay`` (a column on
            top of the game, one screen).
        panel: The Chancellor panel.
        chat: Claude Desktop.
    """

    mode: str
    panel: Rect
    chat: Rect


def plan_layout(
    monitors: list[Monitor], game_monitor: Monitor | None, side: str = "right"
) -> Layout:
    """Decide where the panel and Claude Desktop go. The game is never moved.

    With two or more monitors the panel and Claude Desktop share the largest monitor the
    game is not on, side by side. With one monitor they form an overlay column on the
    ``side`` of the game's monitor, the panel above Claude Desktop.

    Args:
        monitors: Every monitor Windows reports.
        game_monitor: The monitor the game is on; the primary monitor if ``None``.
        side: ``left`` or ``right``, for the overlay column.

    Raises:
        ValueError: If there are no monitors.
    """
    if not monitors:
        raise ValueError("No monitors found")
    home = game_monitor or next((m for m in monitors if m.primary), monitors[0])
    others = [m for m in monitors if m.name != home.name]
    if others:
        area = max(others, key=lambda m: m.work.width * m.work.height).work
        panel_width = round(area.width * PANEL_WIDTH_SHARE)
        return Layout(
            mode="two_screens",
            panel=Rect(area.left, area.top, panel_width, area.height),
            chat=Rect(area.left + panel_width, area.top, area.width - panel_width, area.height),
        )
    return overlay_layout(home.work, round(home.work.width * OVERLAY_WIDTH_SHARE), side)


def overlay_layout(work: Rect, width: int, side: str) -> Layout:
    """The overlay column of ``width`` pixels against the ``side`` edge of ``work``."""
    width = min(width, work.width)
    left = work.left if side == "left" else work.right - width
    panel_height = round(work.height * PANEL_HEIGHT_SHARE)
    return Layout(
        mode="overlay",
        panel=Rect(left, work.top, width, panel_height),
        chat=Rect(left, work.top + panel_height, width, work.height - panel_height),
    )


def side_of(monitor: Monitor, rect: Rect) -> str:
    """``left`` or ``right``: the half of the monitor holding the centre of ``rect``."""
    centre = rect.left + rect.width // 2
    return "left" if centre < monitor.area.left + monitor.area.width // 2 else "right"


def monitor_at(monitors: Iterable[Monitor], rect: Rect) -> Monitor | None:
    """The monitor holding the centre of ``rect``."""
    x, y = rect.left + rect.width // 2, rect.top + rect.height // 2
    return next((m for m in monitors if m.area.contains(x, y)), None)


# --- Win32 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowState:
    """A window's place before docking, to restore it on undock."""

    hwnd: int
    rect: Rect
    maximized: bool


class DockError(RuntimeError):
    """Docking cannot be done, with a message for the player."""


def enable_dpi_awareness() -> None:
    """Make this process per-monitor DPI aware (v2). Safe to call more than once."""
    if sys.platform != "win32":
        return
    per_monitor_v2 = ctypes.c_void_p(-4)
    ctypes.windll.user32.SetProcessDpiAwarenessContext(per_monitor_v2)


class Docker:
    """Finds the panel and Claude Desktop, arranges them and puts them back."""

    def __init__(self, panel_title: str) -> None:
        """Create a docker for the panel window with this title (in this process)."""
        if sys.platform != "win32":
            raise DockError("Docking is only available on Windows.")
        self.panel_title = panel_title
        self._saved: list[WindowState] = []
        self._api = _Win32()

    @property
    def docked(self) -> bool:
        """Whether windows are currently arranged (and can be put back)."""
        return bool(self._saved)

    def screens(self) -> int:
        """How many monitors Windows reports."""
        return len(self._api.monitors())

    def dock(self, side: str = "right") -> dict[str, Any]:
        """Dock on the second screen, or open the overlay column on one screen.

        Args:
            side: ``left`` or ``right``, for the overlay column.

        Returns:
            ``{"mode": "two_screens" | "overlay", "game_found": bool}``.

        Raises:
            DockError: If the panel or Claude Desktop cannot be found.
        """
        panel = self._api.find_window(pid=os.getpid(), title=self.panel_title)
        if panel is None:
            raise DockError("The panel window could not be found.")
        chat = self._api.find_window(exe=CLAUDE_EXE)
        if chat is None:
            raise DockError("Open Claude Desktop first, then try again.")
        game = self._api.find_window(exe=GAME_EXE)
        monitors = self._api.monitors()
        game_monitor = monitor_at(monitors, self._api.window_rect(game)) if game else None
        layout = plan_layout(monitors, game_monitor, side)
        if not self._saved:  # keep the original places across repeated docks
            self._saved = [self._api.state(chat), self._api.state(panel)]

        overlay = layout.mode == "overlay"
        self._api.place(chat, layout.chat, topmost=overlay)
        if overlay:
            # Claude Desktop has a minimum width; widen the column to what it accepted.
            accepted = self._api.visible_rect(chat).width
            if accepted > layout.chat.width:
                home = game_monitor or monitors[0]
                layout = overlay_layout(home.work, accepted, side)
                self._api.place(chat, layout.chat, topmost=True)
        self._api.place(panel, layout.panel, topmost=overlay)
        return {"mode": layout.mode, "game_found": game is not None}

    def put_away(self) -> None:
        """Close the overlay: Claude Desktop drops behind the game (the panel is hidden)."""
        chat = self._api.find_window(exe=CLAUDE_EXE)
        if chat is not None:
            self._api.send_to_back(chat)
        panel = self._api.find_window(pid=os.getpid(), title=self.panel_title)
        if panel is not None:
            self._api.clear_topmost(panel)

    def undock(self) -> None:
        """Put every arranged window back where it was."""
        for state in self._saved:
            self._api.clear_topmost(state.hwnd)
            self._api.restore(state)
        self._saved = []

    def icon_home(self, size: int) -> Rect:
        """Where the floating icon first appears: right edge of the game's screen, mid-height.

        ``size`` is in logical pixels; the returned rectangle is in physical pixels.
        """
        monitors = self._api.monitors()
        game = self._api.find_window(exe=GAME_EXE)
        home = (monitor_at(monitors, self._api.window_rect(game)) if game else None) or next(
            (m for m in monitors if m.primary), monitors[0]
        )
        work = home.work
        scaled = round(size * home.dpi / 96)
        margin = round(16 * home.dpi / 96)
        return Rect(work.right - scaled - margin, work.top + work.height // 2, scaled, scaled)

    def keep_icon_in_view(
        self,
        title: str,
        stop: threading.Event,
        keep_visible: Callable[[], bool] = lambda: False,
    ) -> None:
        """Show the floating icon only while it is useful, until ``stop`` is set.

        It is visible when the game is the active window (or the game is not running),
        when one of this app's windows is active, or while ``keep_visible`` says so (the
        overlay is open). Otherwise it is hidden, so it does not float over the browser
        when the game is minimised.
        """
        icon: int | None = None
        while icon is None and not stop.wait(0.05):  # the window appears after loading
            icon = self._api.find_window(pid=os.getpid(), title=title)
        if icon is None:
            return
        shown = True
        while not stop.wait(0.15):
            if not self._api.is_window(icon):
                return
            wanted = keep_visible() or self._game_in_front()
            if wanted != shown:
                self._api.set_visible(icon, wanted)
                shown = wanted

    def _game_in_front(self) -> bool:
        """The game (or this app) is the active window, or the game is not running."""
        _, pid = self._api.foreground()
        if pid == os.getpid():
            return True
        if self._api.exe_name(pid) == GAME_EXE:
            return True
        return self._api.find_window(exe=GAME_EXE) is None

    def wait_visible(self, title: str, timeout: float = 2.0) -> bool:
        """Wait until a window of this process with this title is visible."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._api.find_window(pid=os.getpid(), title=title) is not None:
                return True
            time.sleep(0.02)
        return False

    def focus_chat(self) -> None:
        """Bring Claude Desktop to the front and give it the keyboard.

        Windows only lets the process that received the last input make another window
        active; a click in the panel or the app's hotkey counts.

        Raises:
            DockError: If Claude Desktop is not running.
        """
        chat = self._api.find_window(exe=CLAUDE_EXE)
        if chat is None:
            raise DockError("Open Claude Desktop first, then try again.")
        self._api.activate(chat)

    def raise_icon(self, title: str) -> None:
        """Keep the floating icon above the overlay column, so it can close it again."""
        icon = self._api.find_window(pid=os.getpid(), title=title)
        if icon is not None:
            self._api.bring_to_top(icon)

    def icon_side(self, title: str) -> str:
        """``left`` or ``right``: the half of its screen the floating icon is on."""
        icon = self._api.find_window(pid=os.getpid(), title=title)
        if icon is None:
            return "right"
        rect = self._api.window_rect(icon)
        monitor = monitor_at(self._api.monitors(), rect)
        return side_of(monitor, rect) if monitor else "right"


class _Win32:
    """The handful of user32 / dwmapi calls docking needs."""

    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    HWND_BOTTOM = 1
    SWP_NOMOVE = 0x0002
    SW_HIDE = 0
    SW_SHOWNOACTIVATE = 4
    SW_RESTORE = 9
    SW_MAXIMIZE = 3
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self) -> None:
        from ctypes import wintypes

        self.wintypes = wintypes
        # Private library handles: declaring argtypes on the shared ctypes.windll objects
        # would change them for pywebview too. Window handles are pointer-sized, so the
        # special values (HWND_TOPMOST = -1) must not be passed as 32-bit ints.
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi")
        self.shcore = ctypes.WinDLL("shcore")
        hwnd, uint, i = wintypes.HWND, wintypes.UINT, ctypes.c_int
        signatures = {
            "SetWindowPos": ([hwnd, hwnd, i, i, i, i, uint], wintypes.BOOL),
            "ShowWindow": ([hwnd, i], wintypes.BOOL),
            "IsZoomed": ([hwnd], wintypes.BOOL),
            "IsIconic": ([hwnd], wintypes.BOOL),
            "IsWindow": ([hwnd], wintypes.BOOL),
            "IsWindowVisible": ([hwnd], wintypes.BOOL),
            "GetWindowRect": ([hwnd, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "GetWindowTextLengthW": ([hwnd], i),
            "GetWindowTextW": ([hwnd, wintypes.LPWSTR, i], i),
            "GetWindowThreadProcessId": ([hwnd, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "GetWindowLongW": ([hwnd, i], ctypes.c_long),
            "GetClientRect": ([hwnd, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "GetForegroundWindow": ([], hwnd),
            "SetForegroundWindow": ([hwnd], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user32, name)
            function.argtypes, function.restype = arguments, result
        self.dwmapi.DwmGetWindowAttribute.argtypes = [
            hwnd,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]

    # monitors
    def monitors(self) -> list[Monitor]:
        wt = self.wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.DWORD),
                ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD),
                ("szDevice", wt.WCHAR * 32),
            ]

        found: list[Monitor] = []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
        def callback(handle: Any, _dc: Any, _clip: Any, _data: Any) -> bool:
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            self.user32.GetMonitorInfoW(handle, ctypes.byref(info))
            dpi_x, dpi_y = wt.UINT(), wt.UINT()
            self.shcore.GetDpiForMonitor(handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
            found.append(
                Monitor(
                    name=info.szDevice,
                    area=_rect(info.rcMonitor),
                    work=_rect(info.rcWork),
                    dpi=dpi_x.value,
                    primary=bool(info.dwFlags & 1),
                )
            )
            return True

        self.user32.EnumDisplayMonitors(None, None, callback, 0)
        return found

    # windows
    def find_window(
        self, exe: str | None = None, pid: int | None = None, title: str | None = None
    ) -> int | None:
        """The largest visible top-level window matching the process and title."""
        wt = self.wintypes
        matches: list[tuple[int, int]] = []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def callback(hwnd: Any, _data: Any) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            if title is not None:
                text = ctypes.create_unicode_buffer(length + 1)
                self.user32.GetWindowTextW(hwnd, text, length + 1)
                if text.value != title:
                    return True
            owner = wt.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if pid is not None and owner.value != pid:
                return True
            if exe is not None and self._exe_name(owner.value) != exe.lower():
                return True
            rect = self.window_rect(int(hwnd))
            matches.append((rect.width * rect.height, int(hwnd)))
            return True

        self.user32.EnumWindows(callback, 0)
        return max(matches)[1] if matches else None

    def window_rect(self, hwnd: int) -> Rect:
        rect = self.wintypes.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return _rect(rect)

    def state(self, hwnd: int) -> WindowState:
        return WindowState(hwnd, self.window_rect(hwnd), bool(self.user32.IsZoomed(hwnd)))

    def place(self, hwnd: int, target: Rect, topmost: bool = False, frame: bool = True) -> None:
        """Move a window so its visible frame fills ``target``.

        Args:
            hwnd: The window.
            target: Where its visible frame should end up.
            topmost: Keep it above other windows (the game included).
            frame: Compensate for invisible resize borders (off for frameless windows).
        """
        if self.user32.IsZoomed(hwnd) or self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, self.SW_RESTORE)
        # Moving to a monitor with another scaling makes the window rescale itself
        # (WM_DPICHANGED), which would undo a size set in the same call. So first bring
        # it onto the target monitor, then size it with the borders of its new DPI.
        self.user32.SetWindowPos(
            hwnd,
            None,
            target.left,
            target.top,
            0,
            0,
            self.SWP_NOZORDER | self.SWP_NOACTIVATE | self.SWP_NOSIZE,
        )
        # Windows 10/11 frames have invisible resize borders inside GetWindowRect; grow
        # the rectangle by them so the visible edges meet the target exactly.
        outer, visible = self.window_rect(hwnd), self.visible_rect(hwnd)
        left = visible.left - outer.left if frame else 0
        top = visible.top - outer.top if frame else 0
        right = outer.right - visible.right if frame else 0
        bottom = outer.bottom - visible.bottom if frame else 0
        order = self.SWP_NOACTIVATE if topmost else self.SWP_NOZORDER | self.SWP_NOACTIVATE
        self.user32.SetWindowPos(
            hwnd,
            self.HWND_TOPMOST if topmost else None,
            target.left - left,
            target.top - top,
            target.width + left + right,
            target.height + top + bottom,
            order,
        )

    def clear_topmost(self, hwnd: int) -> None:
        """Let a window be covered by others again."""
        if self.user32.IsWindow(hwnd):
            flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE
            self.user32.SetWindowPos(hwnd, self.HWND_NOTOPMOST, 0, 0, 0, 0, flags)

    def foreground(self) -> tuple[int, int]:
        """The active window and the process that owns it."""
        hwnd = self.user32.GetForegroundWindow()
        owner = self.wintypes.DWORD()
        if hwnd:
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        return int(hwnd or 0), owner.value

    def set_visible(self, hwnd: int, visible: bool) -> None:
        """Show (without activating) or hide a window."""
        self.user32.ShowWindow(hwnd, self.SW_SHOWNOACTIVATE if visible else self.SW_HIDE)

    def exe_name(self, pid: int) -> str:
        """Lower-case executable name of a process, or an empty string."""
        return self._exe_name(pid)

    def is_window(self, hwnd: int) -> bool:
        """Whether the handle still names a window."""
        return bool(self.user32.IsWindow(hwnd))

    def bring_to_top(self, hwnd: int) -> None:
        """Put a window at the top of the always-on-top windows, without activating it."""
        flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE
        self.user32.SetWindowPos(hwnd, self.HWND_TOPMOST, 0, 0, 0, 0, flags)

    def activate(self, hwnd: int) -> None:
        """Restore a window if minimised, then make it the active window."""
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, self.SW_RESTORE)
        self.user32.SetForegroundWindow(hwnd)

    def send_to_back(self, hwnd: int) -> None:
        """Drop a window behind every other one (behind the game)."""
        self.clear_topmost(hwnd)
        flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE
        self.user32.SetWindowPos(hwnd, self.HWND_BOTTOM, 0, 0, 0, 0, flags)

    def restore(self, state: WindowState) -> None:
        if not self.user32.IsWindow(state.hwnd):
            return
        rect = state.rect
        if self.user32.IsZoomed(state.hwnd):
            self.user32.ShowWindow(state.hwnd, self.SW_RESTORE)
        self.user32.SetWindowPos(
            state.hwnd,
            None,
            rect.left,
            rect.top,
            rect.width,
            rect.height,
            self.SWP_NOZORDER | self.SWP_NOACTIVATE,
        )
        if state.maximized:
            self.user32.ShowWindow(state.hwnd, self.SW_MAXIMIZE)

    def visible_rect(self, hwnd: int) -> Rect:
        """The window's visible frame, without the invisible resize borders."""
        rect = self.wintypes.RECT()
        result = self.dwmapi.DwmGetWindowAttribute(
            hwnd, self.DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        return _rect(rect) if result == 0 else self.window_rect(hwnd)

    def _exe_name(self, pid: int) -> str:
        handle = self.kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = self.wintypes.DWORD(1024)
            self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            return PureWindowsPath(buffer.value).name.lower()
        finally:
            self.kernel32.CloseHandle(handle)


def _rect(native: Any) -> Rect:
    return Rect(native.left, native.top, native.right - native.left, native.bottom - native.top)
