import json
import os
import zipfile
from pathlib import Path

import pytest

from chancellor.save.loader import (
    IronmanSaveError,
    SaveFormatError,
    find_current_save,
    find_latest_save,
    load_save,
)

META = 'date=1475.6.21\nplayer="HAB"\ndisplayed_country_name="Austria"\n'.encode("cp1252")
GAMESTATE = 'players_countries={\n\t"Player"\n\t"HAB"\n}\nname="Náinnas"\n'.encode("cp1252")


def write_zip_save(path: Path, meta: bytes = META, gamestate: bytes = GAMESTATE) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("meta", b"EU4txt\n" + meta)
        archive.writestr("gamestate", b"EU4txt\n" + gamestate)
        archive.writestr("ai", b"EU4txt\nai={}\n")
    return path


def write_text_save(path: Path) -> Path:
    path.write_bytes(b"EU4txt\n" + META + GAMESTATE)
    return path


def make_user_dir(tmp_path: Path) -> Path:
    save_dir = tmp_path / "save games"
    save_dir.mkdir()
    return save_dir


def set_mtime(path: Path, timestamp: float) -> None:
    os.utime(path, (timestamp, timestamp))


# --- load_save -------------------------------------------------------------------------


def test_load_zip_save(tmp_path: Path):
    raw = load_save(write_zip_save(tmp_path / "a.eu4"))

    assert raw.layout == "zip"
    assert raw.meta.startswith("date=1475.6.21")
    assert raw.gamestate.startswith("players_countries=")
    assert "EU4txt" not in raw.meta + raw.gamestate


def test_load_text_save_splits_meta_and_gamestate(tmp_path: Path):
    raw = load_save(write_text_save(tmp_path / "autosave.eu4"))

    assert raw.layout == "text"
    assert raw.meta == META.decode("cp1252")
    assert raw.gamestate == GAMESTATE.decode("cp1252")


def test_text_is_decoded_as_windows_1252(tmp_path: Path):
    raw = load_save(write_zip_save(tmp_path / "a.eu4"))

    assert 'name="Náinnas"' in raw.gamestate


def test_text_save_without_gamestate_marker_returns_whole_body(tmp_path: Path):
    path = tmp_path / "odd.eu4"
    path.write_bytes(b"EU4txt\n" + META)

    raw = load_save(path)

    assert raw.meta == raw.gamestate == META.decode("cp1252")


def test_ironman_text_layout_is_rejected(tmp_path: Path):
    path = tmp_path / "ironman.eu4"
    path.write_bytes(b"EU4bin\x00\x01")

    with pytest.raises(IronmanSaveError):
        load_save(path)


def test_ironman_zip_layout_is_rejected(tmp_path: Path):
    path = tmp_path / "ironman.eu4"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("meta", b"EU4bin\x00")
        archive.writestr("gamestate", b"EU4bin\x00")

    with pytest.raises(IronmanSaveError):
        load_save(path)


def test_non_save_file_is_rejected(tmp_path: Path):
    path = tmp_path / "notes.eu4"
    path.write_text("hello", encoding="utf-8")

    with pytest.raises(SaveFormatError):
        load_save(path)


def test_zip_without_expected_entries_is_rejected(tmp_path: Path):
    path = tmp_path / "broken.eu4"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("other", b"EU4txt\n")

    with pytest.raises(SaveFormatError):
        load_save(path)


# --- finding saves ---------------------------------------------------------------------


def test_find_latest_save_picks_newest_eu4_file(tmp_path: Path):
    save_dir = make_user_dir(tmp_path)
    old = write_text_save(save_dir / "old.eu4")
    new = write_text_save(save_dir / "new.eu4")
    other = save_dir / "newest.txt"
    other.write_text("not a save", encoding="utf-8")
    set_mtime(old, 1_000)
    set_mtime(new, 2_000)
    set_mtime(other, 3_000)

    assert find_latest_save(save_dir) == new


def test_find_latest_save_errors_on_empty_folder(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        find_latest_save(make_user_dir(tmp_path))


def test_find_latest_save_errors_on_missing_folder(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        find_latest_save(tmp_path / "missing")


def test_find_current_save_prefers_continue_game(tmp_path: Path):
    save_dir = make_user_dir(tmp_path)
    current = write_zip_save(save_dir / "Austria1475_06_21.eu4")
    newer = write_text_save(save_dir / "autosave.eu4")
    set_mtime(current, 1_000)
    set_mtime(newer, 2_000)
    (tmp_path / "continue_game.json").write_text(
        json.dumps({"filename": "save games/Austria1475_06_21.eu4"}), encoding="utf-8"
    )

    assert find_current_save(save_dir) == current


@pytest.mark.parametrize(
    "content",
    [
        None,
        "not json",
        json.dumps({"filename": "save games/deleted.eu4"}),
        json.dumps({"title": "no filename"}),
        json.dumps(["unexpected"]),
    ],
)
def test_find_current_save_falls_back_to_newest(tmp_path: Path, content: str | None):
    save_dir = make_user_dir(tmp_path)
    save = write_text_save(save_dir / "autosave.eu4")
    if content is not None:
        (tmp_path / "continue_game.json").write_text(content, encoding="utf-8")

    assert find_current_save(save_dir) == save
