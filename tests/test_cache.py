import os
from pathlib import Path

import pytest

from chancellor.game import cache
from chancellor.game.cache import cache_dir, cached, clear_cache, fingerprint
from chancellor.game.missions import MissionLibrary


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "game" / "missions"
    folder.mkdir(parents=True)
    (folder / "a.txt").write_text("a_series = { slot = 1 a_m = { position = 1 } }", "utf-8")
    return folder


def counting_builder():
    calls = []

    def build():
        calls.append(1)
        return {"value": len(calls)}

    return build, calls


def test_cache_dir_override(isolated_cache: Path):
    assert cache_dir() == isolated_cache


def test_second_call_uses_cache(source: Path, isolated_cache: Path):
    build, calls = counting_builder()
    assert cached("thing", [source], build) == {"value": 1}
    assert cached("thing", [source], build) == {"value": 1}
    assert len(calls) == 1
    assert len(list(isolated_cache.glob("thing-*.pickle"))) == 1


def test_changed_source_rebuilds_and_replaces_entry(source: Path, isolated_cache: Path):
    build, calls = counting_builder()
    cached("thing", [source], build)
    (source / "b.txt").write_text("more", encoding="utf-8")
    assert cached("thing", [source], build) == {"value": 2}
    assert len(calls) == 2
    assert len(list(isolated_cache.glob("thing-*.pickle"))) == 1  # stale entry removed


def test_fingerprint_tracks_size_and_mtime(source: Path):
    before = fingerprint("thing", [source])
    path = source / "a.txt"
    os.utime(path, ns=(1, 1))
    assert fingerprint("thing", [source]) != before
    assert fingerprint("other", [source]) != fingerprint("thing", [source])


def test_missing_sources_are_fine(tmp_path: Path):
    build, calls = counting_builder()
    assert cached("thing", [tmp_path / "missing"], build) == {"value": 1}


def test_corrupt_entry_is_rebuilt(source: Path, isolated_cache: Path):
    build, calls = counting_builder()
    cached("thing", [source], build)
    entry = next(isolated_cache.glob("thing-*.pickle"))
    entry.write_bytes(b"not a pickle")
    assert cached("thing", [source], build) == {"value": 2}


def test_disabled_by_environment(source: Path, monkeypatch, isolated_cache: Path):
    monkeypatch.setenv("CHANCELLOR_NO_CACHE", "1")
    build, calls = counting_builder()
    cached("thing", [source], build)
    cached("thing", [source], build)
    assert len(calls) == 2
    assert not isolated_cache.exists()


def test_unwritable_cache_does_not_fail(source: Path, monkeypatch, tmp_path: Path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("CHANCELLOR_CACHE_DIR", str(blocker / "sub"))  # parent is a file
    build, _ = counting_builder()
    assert cached("thing", [source], build) == {"value": 1}


def test_clear_cache(source: Path):
    build, _ = counting_builder()
    cached("one", [source], build)
    cached("two", [source], build)
    assert clear_cache() == 2
    assert clear_cache() == 0


def test_loader_round_trip(source: Path, monkeypatch):
    game_dir = source.parent
    first = MissionLibrary.load(game_dir)
    monkeypatch.setattr(MissionLibrary, "parse_game", classmethod(lambda cls, d: 1 / 0))
    second = MissionLibrary.load(game_dir)  # served from the cache, no parsing
    assert second.mission("a_m").series == first.mission("a_m").series == "a_series"


def test_default_location_per_platform(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("CHANCELLOR_CACHE_DIR")
    monkeypatch.setattr(cache.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert cache_dir() == tmp_path / "eu4-chancellor" / "cache"
    monkeypatch.setattr(cache.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_dir() == tmp_path / "xdg" / "eu4-chancellor"
