from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path: Path) -> Path:
    """Keep the game-data cache of every test in its own temporary folder."""
    folder = tmp_path / "cache"
    monkeypatch.setenv("CHANCELLOR_CACHE_DIR", str(folder))
    monkeypatch.delenv("CHANCELLOR_NO_CACHE", raising=False)
    return folder
