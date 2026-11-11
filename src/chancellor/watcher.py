"""Watch the save folder and notify when a new save is written (Phase 2)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def watch_saves(save_dir: Path, on_new_save: Callable[[Path], None]) -> None:
    """Block and call ``on_new_save`` each time a save file finishes writing.

    EU4 writes saves incrementally, so the callback must only fire once the file
    size has been stable for a short period.

    Args:
        save_dir: Folder to watch.
        on_new_save: Callback receiving the path of the new save.
    """
    raise NotImplementedError
