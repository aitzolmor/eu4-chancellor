"""Dock EU4, the Chancellor panel and Claude Desktop into one workspace (D-006, UI_DESIGN).

Build order step 4. Windows are found by their process and moved with Win32 calls
through ``ctypes`` (``SetWindowPos``); nothing is reparented or embedded.

* :func:`plan_layout` decides where each window goes from the monitors alone. It is a
  pure function, so every layout rule is tested without touching real windows.
* :class:`Docker` finds the windows, remembers where they were, applies a plan and puts
  everything back on :meth:`Docker.undock`.

Coordinates are physical pixels. The process must be per-monitor DPI aware
(:func:`enable_dpi_awareness`, called before any window exists), or Windows scales the
numbers on the 150% screen and windows land in the wrong place.
"""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any

GAME_EXE = "eu4.exe"
CLAUDE_EXE = "claude.exe"
# One-screen split: the game keeps 70% of the width; the column is shared by the panel
# (top 40%) and Claude Desktop. Two screens: the panel takes a third of the second one.
GAME_SHARE = 0.70
PANEL_HEIGHT_SHARE = 0.40
PANEL_WIDTH_SHARE = 1 / 3


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
    """Where each window goes. ``game`` is ``None`` when the game is left as it is."""

    mode: str  # "two_screens" or "one_screen"
    game: Rect | None
    panel: Rect
    chat: Rect


def plan_layout(monitors: list[Monitor], game_monitor: Monitor | None) -> Layout:
    """Decide the docked layout.

    With two or more monitors the game keeps its own monitor untouched (it runs
    borderless and full screen there) and the panel and Claude Desktop share the largest
    other monitor side by side. With one monitor the game takes the left 70% and the
    panel sits above Claude Desktop in the right-hand column.

    Args:
        monitors: Every monitor Windows reports.
        game_monitor: The monitor the game is on; the primary monitor if ``None``.

    Raises:
        ValueError: If there are no monitors.
    """
    if not monitors:
        raise ValueError("No monitors found")
    home = game_monitor or next((m for m in monitors if m.primary), monitors[0])
    others = [m for m in monitors if m.name != home.name]
    if others:
        side = max(others, key=lambda m: m.work.width * m.work.height).work
        panel_width = round(side.width * PANEL_WIDTH_SHARE)
        return Layout(
            mode="two_screens",
            game=None,
            panel=Rect(side.left, side.top, panel_width, side.height),
            chat=Rect(side.left + panel_width, side.top, side.width - panel_width, side.height),
        )
    work = home.work
    game_width = round(work.width * GAME_SHARE)
    column = Rect(work.left + game_width, work.top, work.width - game_width, work.height)
    panel_height = round(column.height * PANEL_HEIGHT_SHARE)
    return Layout(
        mode="one_screen",
        game=Rect(work.left, work.top, game_width, work.height),
        panel=Rect(column.left, column.top, column.width, panel_height),
        chat=Rect(
            column.left, column.top + panel_height, column.width, column.height - panel_height
        ),
    )


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
    """Finds the three windows, docks them and puts them back."""

    def __init__(self, panel_title: str) -> None:
        """Create a docker for the panel window with this title (in this process)."""
        if sys.platform != "win32":
            raise DockError("Docking is only available on Windows.")
        self.panel_title = panel_title
        self._saved: list[WindowState] = []
        self._api = _Win32()

    @property
    def docked(self) -> bool:
        """Whether windows are currently docked (and can be put back)."""
        return bool(self._saved)

    def dock(self) -> dict[str, Any]:
        """Dock the windows. Returns what was done, for the panel to show.

        Raises:
            DockError: If the panel or Claude Desktop cannot be found.
        """
        panel = self._api.find_window(pid=os.getpid(), title=self.panel_title)
        if panel is None:
            raise DockError("The panel window could not be found.")
        chat = self._api.find_window(exe=CLAUDE_EXE)
        if chat is None:
            raise DockError("Open Claude Desktop first, then dock again.")
        game = self._api.find_window(exe=GAME_EXE)
        monitors = self._api.monitors()
        game_monitor = monitor_at(monitors, self._api.window_rect(game)) if game else None
        layout = plan_layout(monitors, game_monitor)

        targets = [(panel, layout.panel), (chat, layout.chat)]
        if game is not None and layout.game is not None:
            targets.append((game, layout.game))
        if not self._saved:  # keep the original places across repeated docks
            self._saved = [self._api.state(hwnd) for hwnd, _ in targets]
        for hwnd, rect in targets:
            self._api.place(hwnd, rect)
        return {
            "mode": layout.mode,
            "game_found": game is not None,
            "game_moved": game is not None and layout.game is not None,
        }

    def undock(self) -> None:
        """Put every docked window back where it was."""
        for state in self._saved:
            self._api.restore(state)
        self._saved = []


class _Win32:
    """The handful of user32 / dwmapi calls docking needs."""

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
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.dwmapi = ctypes.windll.dwmapi
        self.shcore = ctypes.windll.shcore

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

    def place(self, hwnd: int, target: Rect) -> None:
        """Move a window so its visible frame fills ``target``."""
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
        outer, visible = self.window_rect(hwnd), self._visible_rect(hwnd)
        left = visible.left - outer.left
        top = visible.top - outer.top
        right = outer.right - visible.right
        bottom = outer.bottom - visible.bottom
        self.user32.SetWindowPos(
            hwnd,
            None,
            target.left - left,
            target.top - top,
            target.width + left + right,
            target.height + top + bottom,
            self.SWP_NOZORDER | self.SWP_NOACTIVATE,
        )

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

    def _visible_rect(self, hwnd: int) -> Rect:
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
