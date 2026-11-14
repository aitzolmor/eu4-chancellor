import pytest

from chancellor.app import layout
from chancellor.app.layout import (
    Docker,
    DockError,
    IconPlace,
    Monitor,
    Rect,
    icon_place,
    icon_rect,
    monitor_at,
    overlay_layout,
    plan_layout,
    saved_monitor,
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


def test_one_screen_opens_an_overlay_column_on_the_chosen_side():
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


def test_the_win32_layer_has_every_call_the_docker_makes():
    import inspect
    import re

    used = set(re.findall(r"self\._api\.(\w+)", inspect.getsource(Docker)))
    missing = {name for name in used if not hasattr(layout._Win32, name)}
    assert not missing, f"Docker calls _Win32 methods that do not exist: {missing}"


def test_icon_place_round_trips_on_its_monitor():
    rect = Rect(2240 + 1920 - 64 - 16, 400, 64, 64)  # 64 px at 100% on the side screen
    place = icon_place(SIDE, rect)
    assert (place.monitor, place.primary) == ("DISPLAY2", False)
    assert icon_rect(SIDE, 64, place) == rect


def test_icon_place_survives_a_change_of_scaling():
    # Saved at the right edge, middle height; restored on a screen with other DPI.
    place = IconPlace("DISPLAY1", True, 1.0, 0.5)
    rect = icon_rect(MAIN, 64, place)
    assert rect.width == 96  # 64 logical pixels at 150%
    assert rect.right == MAIN.work.right
    assert rect.top == round(0.5 * (MAIN.work.height - 96))


def test_icon_place_is_clamped_onto_the_screen():
    rect = icon_rect(SIDE, 64, IconPlace("DISPLAY2", False, 1.7, -0.2))
    assert (rect.right, rect.top) == (SIDE.work.right, SIDE.work.top)


def test_saved_monitor_by_name_or_the_primary():
    monitors = [MAIN, SIDE]
    assert saved_monitor(monitors, IconPlace("DISPLAY2", False, 0, 0)) is SIDE
    # Device names change when a display reconnects: a primary place falls back.
    assert saved_monitor(monitors, IconPlace("DISPLAY9", True, 0, 0)) is MAIN
    assert saved_monitor(monitors, IconPlace("DISPLAY9", False, 0, 0)) is None
