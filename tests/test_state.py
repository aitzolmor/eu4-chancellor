from pathlib import Path

from chancellor.app.layout import IconPlace
from chancellor.app.state import (
    load_icon_place,
    load_overlay_side,
    save_icon_place,
    save_overlay_side,
    state_dir,
)


def test_state_goes_to_the_overridden_folder(isolated_state: Path):
    assert state_dir() == isolated_state


def test_icon_place_round_trips(isolated_state: Path):
    assert load_icon_place() is None
    place = IconPlace("\\\\.\\DISPLAY1", True, 0.9876, 0.5)
    save_icon_place(place)
    assert load_icon_place() == place
    assert (isolated_state / "state.json").is_file()


def test_unreadable_state_means_nothing_saved(isolated_state: Path):
    isolated_state.mkdir(parents=True)
    (isolated_state / "state.json").write_text("{not json", encoding="utf-8")
    assert load_icon_place() is None
    (isolated_state / "state.json").write_text('{"icon": {"x": "left"}}', encoding="utf-8")
    assert load_icon_place() is None


def test_saving_keeps_other_keys(isolated_state: Path):
    isolated_state.mkdir(parents=True)
    (isolated_state / "state.json").write_text('{"other": 1}', encoding="utf-8")
    save_icon_place(IconPlace("D", False, 0.0, 1.0))
    text = (isolated_state / "state.json").read_text(encoding="utf-8")
    assert '"other": 1' in text


def test_overlay_side_round_trips_next_to_the_icon_place(isolated_state: Path):
    assert load_overlay_side() is None
    save_icon_place(IconPlace("D", True, 0.5, 0.5))
    save_overlay_side("left")
    assert load_overlay_side() == "left"
    assert load_icon_place() == IconPlace("D", True, 0.5, 0.5)  # both kept
    (isolated_state / "state.json").write_text('{"overlay_side": "up"}', encoding="utf-8")
    assert load_overlay_side() is None
