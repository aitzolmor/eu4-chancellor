import os
import time
from pathlib import Path

import pytest

from chancellor.watcher import SaveWatcher


@pytest.fixture
def save_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "save games"
    folder.mkdir()
    return folder


def write(path: Path, text: str, mtime: int) -> None:
    """Write a save and give it an explicit modification time (seconds)."""
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(mtime * 10**9, mtime * 10**9))


def watcher(save_dir: Path) -> tuple[SaveWatcher, list[Path]]:
    seen: list[Path] = []
    return SaveWatcher(save_dir, seen.append), seen


def test_first_check_only_records_the_current_save(save_dir: Path):
    write(save_dir / "a.eu4", "EU4txt", 100)
    watch, seen = watcher(save_dir)
    assert watch.check() is False
    assert watch.check() is False  # nothing changed
    assert seen == []


def test_new_save_is_reported_once_it_has_settled(save_dir: Path):
    write(save_dir / "a.eu4", "EU4txt", 100)
    watch, seen = watcher(save_dir)
    watch.check()
    write(save_dir / "b.eu4", "EU4txt date=1476.1.1", 200)
    assert watch.check() is False  # seen once: it may still be being written
    assert watch.check() is True
    assert seen == [save_dir / "b.eu4"]
    assert watch.check() is False  # reported only once


def test_a_save_still_growing_is_not_reported(save_dir: Path):
    write(save_dir / "a.eu4", "EU4txt", 100)
    watch, seen = watcher(save_dir)
    watch.check()
    for step, size in enumerate((10, 20, 30), 1):
        write(save_dir / "autosave.eu4", "x" * size, 200 + step)
        assert watch.check() is False
    assert watch.check() is True
    assert seen == [save_dir / "autosave.eu4"]


def test_overwriting_the_same_file_counts_as_new(save_dir: Path):
    write(save_dir / "autosave.eu4", "EU4txt one", 100)
    watch, seen = watcher(save_dir)
    watch.check()
    write(save_dir / "autosave.eu4", "EU4txt two!", 300)
    watch.check()
    assert watch.check() is True
    assert seen == [save_dir / "autosave.eu4"]


def test_empty_or_missing_folder_is_not_an_error(tmp_path: Path):
    folder = tmp_path / "save games"
    watch, seen = watcher(folder)
    assert watch.check() is False
    folder.mkdir()
    write(folder / "first.eu4", "EU4txt", 100)
    watch.check()
    assert watch.check() is True
    assert seen == [folder / "first.eu4"]


def test_the_thread_reports_new_saves(save_dir: Path):
    write(save_dir / "a.eu4", "EU4txt", 100)
    seen: list[Path] = []
    watch = SaveWatcher(save_dir, seen.append, interval=0.02)
    watch.start()
    try:
        write(save_dir / "b.eu4", "EU4txt", 200)
        deadline = time.monotonic() + 2
        while not seen and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        watch.stop()
    assert seen == [save_dir / "b.eu4"]
