import pytest

from chancellor.app import icon_window
from chancellor.app.icon_window import GOLD, NAVY, FloatingIcon, render_icon
from chancellor.app.layout import Rect

SIZE = 96  # 64 logical pixels at 150%


def pixel(picture: bytes, x: int, y: int, size: int = SIZE) -> tuple[int, int, int, int]:
    """(red, green, blue, alpha) of a premultiplied BGRA picture."""
    i = (y * size + x) * 4
    blue, green, red, alpha = picture[i : i + 4]
    return red, green, blue, alpha


def test_corners_are_fully_transparent():
    picture = render_icon(SIZE)
    assert len(picture) == SIZE * SIZE * 4
    for x, y in [(0, 0), (SIZE - 1, 0), (0, SIZE - 1), (SIZE - 1, SIZE - 1), (8, 8)]:
        assert pixel(picture, x, y)[3] == 0


def test_closed_icon_is_navy_with_a_gold_ring_and_crown():
    picture = render_icon(SIZE)
    assert pixel(picture, SIZE // 2, 75) == (*NAVY, 255)  # inside, below the crown base
    assert pixel(picture, 1, SIZE // 2) == (*GOLD, 255)  # the ring at the left edge
    assert pixel(picture, SIZE // 2, 58) == (*GOLD, 255)  # on the crown's lower edge


def test_open_icon_swaps_the_colours():
    picture = render_icon(SIZE, open_=True)
    assert pixel(picture, SIZE // 2, 75) == (*GOLD, 255)
    assert pixel(picture, SIZE // 2, 58) == (*NAVY, 255)


def test_edges_are_anti_aliased():
    picture = render_icon(SIZE)
    alphas = {pixel(picture, x, SIZE // 2)[3] for x in range(0, 4)}
    assert any(0 < a < 255 for a in alphas)  # a soft edge, not a staircase


def test_pixels_are_premultiplied():
    picture = render_icon(SIZE)
    for x in range(SIZE):
        red, green, blue, alpha = pixel(picture, x, 2)
        assert max(red, green, blue) <= alpha


def test_hover_lightens_the_closed_icon_only():
    assert render_icon(SIZE, hover=True) != render_icon(SIZE)
    assert render_icon(SIZE, open_=True, hover=True) == render_icon(SIZE, open_=True)


def test_the_window_is_windows_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(icon_window.sys, "platform", "linux")
    with pytest.raises(OSError, match="only available on Windows"):
        FloatingIcon("Chancellor icon", Rect(0, 0, 96, 96), lambda: None, lambda: None)
