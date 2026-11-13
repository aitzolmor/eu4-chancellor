import pytest

from chancellor.app import layout
from chancellor.app.layout import Docker, DockError, Monitor, Rect, monitor_at, plan_layout

# The developer's screens: a 2240×1400 laptop at 150% and a 1920×1080 screen to its right.
MAIN = Monitor("DISPLAY1", Rect(0, 0, 2240, 1400), Rect(0, 0, 2240, 1328), 144, True)
SIDE = Monitor("DISPLAY2", Rect(2240, 0, 1920, 1080), Rect(2240, 0, 1920, 1032), 96, False)
SMALL = Monitor("DISPLAY3", Rect(-1280, 0, 1280, 720), Rect(-1280, 0, 1280, 680), 96, False)


def test_two_screens_leave_the_game_alone():
    plan = plan_layout([MAIN, SIDE], MAIN)
    assert plan.mode == "two_screens"
    assert plan.game is None
    assert plan.panel == Rect(2240, 0, 640, 1032)  # a third of the second screen
    assert plan.chat == Rect(2880, 0, 1280, 1032)


def test_game_on_the_second_screen_sends_the_column_to_the_first():
    plan = plan_layout([MAIN, SIDE], SIDE)
    assert plan.panel.left == 0 and plan.chat.right == 2240
    assert plan.panel.height == 1328  # the work area, above the taskbar


def test_the_largest_other_screen_is_used():
    plan = plan_layout([MAIN, SMALL, SIDE], MAIN)
    assert plan.panel.left == 2240


def test_one_screen_splits_seventy_thirty():
    plan = plan_layout([MAIN], MAIN)
    assert plan.mode == "one_screen"
    assert plan.game == Rect(0, 0, 1568, 1328)
    assert plan.panel == Rect(1568, 0, 672, 531)  # top 40% of the column
    assert plan.chat == Rect(1568, 531, 672, 797)
    assert plan.game.right == plan.panel.left == plan.chat.left


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
