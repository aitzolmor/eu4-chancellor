"""On-disk cache for data parsed from the game installation.

Parsing the game's script and localisation files takes several seconds per run, yet those
files only change when the game is patched. Each loader passes the folders it reads, and
the cache stores the parsed result together with a fingerprint of those folders: every
file's relative path, size and modification time, plus the package version. If anything
changes, the fingerprint changes and the data is parsed again.

The cache lives in the user's cache folder (``%LOCALAPPDATA%/eu4-chancellor/cache`` on
Windows). Set ``CHANCELLOR_CACHE_DIR`` to move it, or ``CHANCELLOR_NO_CACHE=1`` to
disable it. Entries are Python pickles written by this program for this user only.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypeVar

from chancellor import __version__

T = TypeVar("T")

# Bump when the shape of cached objects changes in a way the version would not catch.
CACHE_FORMAT = 2  # 2: areas with a colour lost their provinces before
_SUFFIX = ".pickle"


def cache_dir() -> Path:
    """Folder holding cache entries."""
    override = os.environ.get("CHANCELLOR_CACHE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "eu4-chancellor" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "eu4-chancellor"
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "eu4-chancellor"


def cached(kind: str, sources: Iterable[Path], build: Callable[[], T]) -> T:
    """Return ``build()``'s result, reusing a cached copy while ``sources`` are unchanged.

    Args:
        kind: Name of the data, e.g. ``"missions"`` or ``"localisation-spanish"``.
        sources: Files or folders the data is built from.
        build: Parses the data from the game files.

    Returns:
        The cached or freshly built data.
    """
    if os.environ.get("CHANCELLOR_NO_CACHE"):
        return build()
    folder = cache_dir()
    entry = folder / f"{kind}-{fingerprint(kind, sources)}{_SUFFIX}"
    if entry.is_file():
        try:
            with entry.open("rb") as file:
                return pickle.load(file)  # noqa: S301 - written by this program
        except Exception:  # noqa: BLE001 - a corrupt entry is simply rebuilt
            pass

    value = build()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.glob(f"{kind}-*{_SUFFIX}"):
            stale.unlink(missing_ok=True)
        temporary = entry.with_suffix(".tmp")
        with temporary.open("wb") as file:
            pickle.dump(value, file, protocol=pickle.HIGHEST_PROTOCOL)
        temporary.replace(entry)
    except OSError:
        pass  # caching is an optimisation; never fail the command because of it
    return value


def fingerprint(kind: str, sources: Iterable[Path]) -> str:
    """Hash of the package version and every source file's path, size and mtime."""
    digest = hashlib.sha256(f"{__version__}|{CACHE_FORMAT}|{kind}".encode())
    for source in sources:
        files = sorted(source.rglob("*")) if source.is_dir() else [source]
        digest.update(str(source).encode())
        for path in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.is_file():
                relative = path.relative_to(source) if source.is_dir() else path.name
                digest.update(f"{relative}|{stat.st_size}|{stat.st_mtime_ns}".encode())
    return digest.hexdigest()[:16]


def clear_cache() -> int:
    """Delete every cache entry. Returns how many were removed."""
    folder = cache_dir()
    removed = 0
    if folder.is_dir():
        for entry in folder.glob(f"*{_SUFFIX}"):
            entry.unlink(missing_ok=True)
            removed += 1
    return removed
