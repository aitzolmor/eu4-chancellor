from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path: Path) -> Path:
    """Keep the game-data cache of every test in its own temporary folder."""
    folder = tmp_path / "cache"
    monkeypatch.setenv("CHANCELLOR_CACHE_DIR", str(folder))
    monkeypatch.delenv("CHANCELLOR_NO_CACHE", raising=False)
    return folder


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path: Path) -> Path:
    """Keep the desktop app's saved state (the icon's place) out of the real folder."""
    folder = tmp_path / "state"
    monkeypatch.setenv("CHANCELLOR_STATE_DIR", str(folder))
    return folder
