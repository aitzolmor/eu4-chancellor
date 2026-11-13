"""The floating icon: a native, truly round window over the game (D-022, D-023).

A web view cannot be round: WebView2 paints outside a window region, leaving square
corners. This icon is a plain Win32 *layered* window instead, whose pixels carry their
own transparency (``UpdateLayeredWindow``), so only the circle shows. It also costs far
less than a web view (no browser process) and handles the mouse itself:

* left button: drag the icon, or a click (no movement) opens or closes the overlay;
* right button: a menu with "Close Chancellor".

Mouse messages reach our own window even while the game runs as administrator, unlike
the global button state (D-022).

:func:`render_icon` draws the picture in pure Python, so it is tested on any platform;
:class:`FloatingIcon` is the Windows-only window around it.
"""

from __future__ import annotations

import ctypes
import functools
import math
import sys
import threading
from collections.abc import Callable
from typing import Any

from chancellor.app.layout import Rect

NAVY = (15, 23, 38)
NAVY_HOVER = (28, 42, 71)
GOLD = (201, 162, 74)
RING = 3 / 64  # gold ring width, as a share of the icon's size
CROWN_STROKE = 1.8 / 24 * 30 / 64  # the crown's line width, as a share of the size
# The crown, in a 24-unit box drawn 30/64 of the icon wide and centred (as the old SVG).
CROWN = [(3, 8), (7.5, 12), (12, 5), (16.5, 12), (21, 8), (19, 18), (5, 18), (3, 8)]
CROWN_BASE = [(5, 21), (19, 21)]
DRAG_THRESHOLD = 4  # pixels the pointer moves before a press counts as a drag


@functools.lru_cache(maxsize=16)  # three states per size; drawing one takes ~0.1 s
def render_icon(size: int, open_: bool = False, hover: bool = False) -> bytes:
    """Draw the icon as premultiplied BGRA pixels, top row first.

    A navy disc with a gold ring and a gold crown; when ``open_`` the disc is gold and the
    crown navy. Edges are anti-aliased from the exact distance to each shape, so the
    circle blends into whatever is behind it.

    Args:
        size: Width and height in physical pixels.
        open_: Draw the "overlay open" state.
        hover: Draw the lighter hover state (closed icon only).

    Returns:
        ``size * size * 4`` bytes, ready for a 32-bit top-down DIB.
    """
    fill = GOLD if open_ else (NAVY_HOVER if hover else NAVY)
    crown_colour = NAVY if open_ else GOLD
    centre = size / 2
    radius = size / 2 - 0.5
    ring = max(1.0, RING * size)
    half_stroke = max(0.6, CROWN_STROKE * size / 2)
    scale = 30 / 64 * size / 24
    offset = (size - 30 / 64 * size) / 2
    lines = _segments(CROWN, scale, offset) + _segments(CROWN_BASE, scale, offset)

    pixels = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            distance = math.hypot(px - centre, py - centre)
            alpha = _clamp(radius - distance + 0.5)
            if alpha <= 0:
                continue  # stays fully transparent
            colour = fill
            ring_cover = _clamp(distance - (radius - ring) + 0.5)
            if ring_cover > 0:
                colour = _mix(colour, GOLD, ring_cover)
            crown_cover = _clamp(half_stroke - _distance_to(lines, px, py) + 0.5)
            if crown_cover > 0:
                colour = _mix(colour, crown_colour, crown_cover)
            index = (y * size + x) * 4
            red, green, blue = (round(c * alpha) for c in colour)
            pixels[index : index + 4] = bytes((blue, green, red, round(255 * alpha)))
    return bytes(pixels)


def _segments(
    points: list[tuple[float, float]], scale: float, offset: float
) -> list[tuple[float, float, float, float]]:
    placed = [(offset + x * scale, offset + y * scale) for x, y in points]
    return [(*a, *b) for a, b in zip(placed, placed[1:], strict=False)]


def _distance_to(lines: list[tuple[float, float, float, float]], px: float, py: float) -> float:
    """Shortest distance from a point to any of the segments."""
    best = math.inf
    for x1, y1, x2, y2 in lines:
        dx, dy = x2 - x1, y2 - y1
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length))
        best = min(best, math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)))
    return best


def _clamp(value: float) -> float:
    return 0.0 if value <= 0 else 1.0 if value >= 1 else value


def _mix(a: tuple[int, ...], b: tuple[int, ...], amount: float) -> tuple[float, ...]:
    return tuple(x + (y - x) * amount for x, y in zip(a, b, strict=True))


class FloatingIcon:
    """The native floating icon, on its own thread with its own message loop."""

    def __init__(
        self,
        title: str,
        home: Rect,
        on_click: Callable[[], Any],
        on_quit: Callable[[], Any],
    ) -> None:
        """Create the icon; nothing appears until :meth:`start`.

        Args:
            title: Window title (lets the layout code find the icon).
            home: Where it first appears, in physical pixels; its width is the size.
            on_click: Called (on a worker thread) when the icon is clicked.
            on_quit: Called (on a worker thread) when "Close Chancellor" is chosen.
        """
        if sys.platform != "win32":
            raise OSError("The floating icon is only available on Windows.")
        self.title = title
        self.home = home
        self.on_click = on_click
        self.on_quit = on_quit
        self.hwnd = 0
        self._open = False
        self._hover = False
        self._ready = threading.Event()
        self._busy = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Create the window on its own thread and wait until it is on screen."""
        self._thread = threading.Thread(target=self._run, name="floating-icon", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def set_open(self, open_: bool) -> None:
        """Draw the open (gold) or closed (navy) state. Safe from any thread."""
        if self.hwnd:
            _Native.get().user32.PostMessageW(self.hwnd, _WM_SET_OPEN, int(open_), 0)

    def destroy(self) -> None:
        """Close the window and end its thread. Safe from any thread."""
        if self.hwnd:
            _Native.get().user32.PostMessageW(self.hwnd, _WM_CLOSE_ICON, 0, 0)

    # --- the window thread ---------------------------------------------------------------

    def _run(self) -> None:
        native = _Native.get()
        self._procedure = native.WNDPROC(self._window_procedure)  # keep a reference
        self.hwnd = native.create_window(self.title, self._procedure)
        self._drag: tuple[int, int, int, int] | None = None
        self._moved = False
        self._paint(self.home.left, self.home.top)
        native.show(self.hwnd)
        self._ready.set()
        native.message_loop()

    def _paint(self, left: int | None = None, top: int | None = None) -> None:
        size = self.home.width
        picture = render_icon(size, self._open, self._hover and not self._open)
        _Native.get().update_layered(self.hwnd, picture, size, left, top)

    def _window_procedure(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        native = _Native.get()
        user32 = native.user32
        if message == _WM_MOUSEACTIVATE:
            return _MA_NOACTIVATE  # clicking must not take the focus from the game
        if message == _WM_SETCURSOR:
            user32.SetCursor(user32.LoadCursorW(None, _IDC_HAND))
            return 1
        if message == _WM_LBUTTONDOWN:
            x, y = native.cursor()
            rect = native.window_rect(hwnd)
            self._drag, self._moved = (x, y, rect.left, rect.top), False
            user32.SetCapture(hwnd)
            return 0
        if message == _WM_MOUSEMOVE:
            if self._drag is not None:
                x, y = native.cursor()
                start_x, start_y, left, top = self._drag
                dx, dy = x - start_x, y - start_y
                if self._moved or max(abs(dx), abs(dy)) > DRAG_THRESHOLD:
                    self._moved = True
                    native.move(hwnd, left + dx, top + dy)
            elif not self._hover:
                self._hover = True
                native.track_leave(hwnd)
                self._paint()
            return 0
        if message == _WM_MOUSELEAVE:
            self._hover = False
            self._paint()
            return 0
        if message == _WM_LBUTTONUP:
            dragging, self._drag = self._drag is not None, None
            user32.ReleaseCapture()
            if dragging and not self._moved:
                self._in_background(self.on_click)
            return 0
        if message == _WM_RBUTTONUP:
            if native.close_menu(hwnd):
                self._in_background(self.on_quit)
            return 0
        if message == _WM_SET_OPEN:
            self._open = bool(wparam)
            self._paint()
            return 0
        if message == _WM_CLOSE_ICON:
            user32.DestroyWindow(hwnd)
            return 0
        if message == _WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _in_background(self, action: Callable[[], Any]) -> None:
        """Run a callback off the window thread, one at a time (it may take a while)."""

        def run() -> None:
            if not self._busy.acquire(blocking=False):
                return  # a click while the previous one is still being handled
            try:
                action()
            finally:
                self._busy.release()

        threading.Thread(target=run, name="icon-action", daemon=True).start()


# --- Win32 plumbing ----------------------------------------------------------------------

_WM_DESTROY = 0x0002
_WM_SETCURSOR = 0x0020
_WM_MOUSEACTIVATE = 0x0021
_WM_MOUSEMOVE = 0x0200
_WM_LBUTTONDOWN = 0x0201
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONUP = 0x0205
_WM_MOUSELEAVE = 0x02A3
_WM_APP = 0x8000
_WM_SET_OPEN = _WM_APP + 1
_WM_CLOSE_ICON = _WM_APP + 2
_MA_NOACTIVATE = 3
_IDC_HAND = 32649


class _Native:
    """ctypes declarations for the icon window, created once."""

    _instance: _Native | None = None

    @classmethod
    def get(cls) -> _Native:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        from ctypes import wintypes as wt

        self.wt = wt
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32")
        self.kernel32 = ctypes.WinDLL("kernel32")
        lresult = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(lresult, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        class WndClass(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.UINT),
                ("style", wt.UINT),
                ("lpfnWndProc", self.WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR),
                ("hIconSm", wt.HICON),
            ]

        class BitmapInfoHeader(ctypes.Structure):
            _fields_ = [
                ("biSize", wt.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD),
            ]

        class Blend(ctypes.Structure):
            _fields_ = [
                ("BlendOp", ctypes.c_ubyte),
                ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte),
            ]

        class TrackMouse(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.DWORD),
                ("dwFlags", wt.DWORD),
                ("hwndTrack", wt.HWND),
                ("dwHoverTime", wt.DWORD),
            ]

        self.WndClass, self.BitmapInfoHeader = WndClass, BitmapInfoHeader
        self.Blend, self.TrackMouse = Blend, TrackMouse
        h, u, i = wt.HWND, wt.UINT, ctypes.c_int
        signatures = {
            "DefWindowProcW": ([h, u, wt.WPARAM, wt.LPARAM], lresult),
            "RegisterClassExW": ([ctypes.POINTER(WndClass)], wt.ATOM),
            "CreateWindowExW": (
                [
                    wt.DWORD,
                    wt.LPCWSTR,
                    wt.LPCWSTR,
                    wt.DWORD,
                    i,
                    i,
                    i,
                    i,
                    h,
                    wt.HMENU,
                    wt.HINSTANCE,
                    wt.LPVOID,
                ],
                h,
            ),
            "DestroyWindow": ([h], wt.BOOL),
            "PostMessageW": ([h, u, wt.WPARAM, wt.LPARAM], wt.BOOL),
            "PostQuitMessage": ([i], None),
            "GetMessageW": ([ctypes.POINTER(wt.MSG), h, u, u], wt.BOOL),
            "TranslateMessage": ([ctypes.POINTER(wt.MSG)], wt.BOOL),
            "DispatchMessageW": ([ctypes.POINTER(wt.MSG)], lresult),
            "SetCapture": ([h], h),
            "ReleaseCapture": ([], wt.BOOL),
            "GetCursorPos": ([ctypes.POINTER(wt.POINT)], wt.BOOL),
            "GetWindowRect": ([h, ctypes.POINTER(wt.RECT)], wt.BOOL),
            "SetWindowPos": ([h, h, i, i, i, i, u], wt.BOOL),
            "SetCursor": ([wt.HANDLE], wt.HANDLE),
            "LoadCursorW": ([wt.HINSTANCE, wt.LPVOID], wt.HANDLE),
            "GetDC": ([h], wt.HDC),
            "ReleaseDC": ([h, wt.HDC], i),
            "UpdateLayeredWindow": (
                [
                    h,
                    wt.HDC,
                    ctypes.POINTER(wt.POINT),
                    ctypes.POINTER(wt.SIZE),
                    wt.HDC,
                    ctypes.POINTER(wt.POINT),
                    wt.COLORREF,
                    ctypes.POINTER(Blend),
                    wt.DWORD,
                ],
                wt.BOOL,
            ),
            "TrackMouseEvent": ([ctypes.POINTER(TrackMouse)], wt.BOOL),
            "CreatePopupMenu": ([], wt.HMENU),
            "AppendMenuW": ([wt.HMENU, u, ctypes.c_size_t, wt.LPCWSTR], wt.BOOL),
            "TrackPopupMenu": ([wt.HMENU, u, i, i, i, h, wt.LPVOID], wt.BOOL),
            "DestroyMenu": ([wt.HMENU], wt.BOOL),
            "SetForegroundWindow": ([h], wt.BOOL),
            "ShowWindow": ([h, i], wt.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user32, name)
            function.argtypes, function.restype = arguments, result
        self.gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
        self.gdi32.CreateCompatibleDC.restype = wt.HDC
        self.gdi32.CreateDIBSection.argtypes = [
            wt.HDC,
            ctypes.c_void_p,
            u,
            ctypes.POINTER(ctypes.c_void_p),
            wt.HANDLE,
            wt.DWORD,
        ]
        self.gdi32.CreateDIBSection.restype = wt.HBITMAP
        self.gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
        self.gdi32.SelectObject.restype = wt.HGDIOBJ
        self.gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
        self.gdi32.DeleteDC.argtypes = [wt.HDC]
        self.kernel32.GetModuleHandleW.restype = wt.HMODULE
        self._registered = False

    def create_window(self, title: str, procedure: Any) -> int:
        """A hidden, top-most, non-activating layered popup without a taskbar button."""
        instance = self.kernel32.GetModuleHandleW(None)
        if not self._registered:
            window_class = self.WndClass()
            window_class.cbSize = ctypes.sizeof(window_class)
            window_class.lpfnWndProc = procedure
            window_class.hInstance = instance
            window_class.lpszClassName = "ChancellorFloatingIcon"
            self.user32.RegisterClassExW(ctypes.byref(window_class))
            self._registered = True
        layered, topmost, tool, no_activate = 0x00080000, 0x00000008, 0x00000080, 0x08000000
        popup = 0x80000000
        hwnd = self.user32.CreateWindowExW(
            layered | topmost | tool | no_activate,
            "ChancellorFloatingIcon",
            title,
            popup,
            0,
            0,
            1,
            1,
            None,
            None,
            instance,
            None,
        )
        return int(hwnd)

    def update_layered(
        self, hwnd: int, pixels: bytes, size: int, left: int | None, top: int | None
    ) -> None:
        """Show premultiplied BGRA pixels as the window's whole content."""
        wt = self.wt
        screen = self.user32.GetDC(None)
        memory = self.gdi32.CreateCompatibleDC(screen)
        header = self.BitmapInfoHeader()
        header.biSize = ctypes.sizeof(header)
        header.biWidth, header.biHeight = size, -size  # negative: top row first
        header.biPlanes, header.biBitCount = 1, 32
        bits = ctypes.c_void_p()
        bitmap = self.gdi32.CreateDIBSection(
            memory, ctypes.byref(header), 0, ctypes.byref(bits), None, 0
        )
        ctypes.memmove(bits, pixels, len(pixels))
        previous = self.gdi32.SelectObject(memory, bitmap)
        blend = self.Blend(0, 0, 255, 1)  # AC_SRC_OVER, per-pixel alpha
        source = wt.POINT(0, 0)
        destination = wt.POINT(left, top) if left is not None and top is not None else None
        self.user32.UpdateLayeredWindow(
            hwnd,
            screen,
            ctypes.byref(destination) if destination else None,
            ctypes.byref(wt.SIZE(size, size)),
            memory,
            ctypes.byref(source),
            0,
            ctypes.byref(blend),
            2,  # ULW_ALPHA
        )
        self.gdi32.SelectObject(memory, previous)
        self.gdi32.DeleteObject(bitmap)
        self.gdi32.DeleteDC(memory)
        self.user32.ReleaseDC(None, screen)

    def show(self, hwnd: int) -> None:
        """Show without activating (the game keeps the focus)."""
        self.user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE

    def message_loop(self) -> None:
        message = self.wt.MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))

    def cursor(self) -> tuple[int, int]:
        point = self.wt.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def window_rect(self, hwnd: int) -> Rect:
        rect = self.wt.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def move(self, hwnd: int, left: int, top: int) -> None:
        no_size, no_z_order, no_activate = 0x0001, 0x0004, 0x0010
        self.user32.SetWindowPos(hwnd, None, left, top, 0, 0, no_size | no_z_order | no_activate)

    def track_leave(self, hwnd: int) -> None:
        """Ask for a WM_MOUSELEAVE when the pointer leaves the icon."""
        track = self.TrackMouse(ctypes.sizeof(self.TrackMouse), 0x00000002, hwnd, 0)
        self.user32.TrackMouseEvent(ctypes.byref(track))

    def close_menu(self, hwnd: int) -> bool:
        """Show the right-click menu; whether "Close Chancellor" was chosen."""
        menu = self.user32.CreatePopupMenu()
        self.user32.AppendMenuW(menu, 0, 1, "Close Chancellor")
        x, y = self.cursor()
        self.user32.SetForegroundWindow(hwnd)  # or the menu does not close on click-away
        return_command, no_notify, right_button = 0x0100, 0x0080, 0x0002
        chosen = self.user32.TrackPopupMenu(
            menu, return_command | no_notify | right_button, x, y, 0, hwnd, None
        )
        self.user32.DestroyMenu(menu)
        self.user32.PostMessageW(hwnd, 0, 0, 0)  # WM_NULL, as the documentation advises
        return chosen == 1
