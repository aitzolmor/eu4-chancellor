import pytest

from chancellor.app import layout
from chancellor.app.layout import (
    Docker,
    DockError,
    Monitor,
    Rect,
    monitor_at,
    overlay_layout,
    plan_layout,
    side_of,
)

# The developer's screens: a 2240×1400 laptop at 150% and a 1920×1080 screen to its right.
MAIN = Monitor("DISPLAY1", Rect(0, 0, 2240, 1400), Rect(0, 0, 2240, 1328), 144, True)
SIDE = Monitor("DISPLAY2", Rect(2240, 0, 1920, 1080), Rect(2240, 0, 1920, 1032), 96, False)
SMALL = Monitor("DISPLAY3", Rect(-1280, 0, 1280, 720), Rect(-1280, 0, 1280, 680), 96, False)


def test_two_screens_dock_on_the_other_screen():
    plan = plan_layout([MAIN, SIDE], MAIN)
    assert plan.mode == "two_screens"
    assert plan.panel == Rect(2240, 0, 640, 1032)  # a third of the second screen
    assert plan.chat == Rect(2880, 0, 1280, 1032)


def test_game_on_the_second_screen_sends_the_windows_to_the_first():
    plan = plan_layout([MAIN, SIDE], SIDE)
    assert plan.panel.left == 0 and plan.chat.right == 2240
    assert plan.panel.height == 1328  # the work area, above the taskbar


def test_the_largest_other_screen_is_used():
    plan = plan_layout([MAIN, SMALL, SIDE], MAIN)
    assert plan.panel.left == 2240


def test_one_screen_opens_an_overlay_column_on_the_icon_side():
    right = plan_layout([MAIN], MAIN)  # default side
    assert right.mode == "overlay"
    assert right.panel == Rect(1344, 0, 896, 531)  # 40% of the width, top 40%
    assert right.chat == Rect(1344, 531, 896, 797)
    left = plan_layout([MAIN], MAIN, side="left")
    assert left.panel.left == left.chat.left == 0
    assert left.panel.width == 896


def test_overlay_widens_to_what_claude_desktop_accepts():
    # Claude Desktop will not go below ~903 px at 150%; the column follows it.
    plan = overlay_layout(MAIN.work, 903, "right")
    assert plan.chat == Rect(1337, 531, 903, 797)
    assert plan.panel.left == 1337 and plan.panel.width == 903
    assert overlay_layout(MAIN.work, 5000, "left").chat.width == 2240  # never off-screen


def test_side_of_uses_the_rect_centre():
    assert side_of(MAIN, Rect(2120, 664, 96, 96)) == "right"
    assert side_of(MAIN, Rect(100, 664, 96, 96)) == "left"
    assert side_of(SIDE, Rect(2300, 0, 96, 96)) == "left"


def test_without_a_known_game_monitor_the_primary_is_home():
    assert plan_layout([SIDE, MAIN], None).panel.left == 2240


def test_no_monitors_is_an_error():
    with pytest.raises(ValueError):
        plan_layout([], None)


def test_monitor_at_uses_the_window_centre():
    assert monitor_at([MAIN, SIDE], Rect(2000, 100, 600, 400)) == SIDE  # centre x = 2300
    assert monitor_at([MAIN, SIDE], Rect(0, 0, 2240, 1400)) == MAIN
    assert monitor_at([MAIN], Rect(5000, 0, 10, 10)) is None


def test_docking_is_windows_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(layout.sys, "platform", "linux")
    with pytest.raises(DockError, match="only available on Windows"):
        Docker("Chancellor")
