"""Locate EU4 save files on disk and extract their raw text sections.

EU4 writes saves in two layouts (see ``docs/SAVE_FORMAT.md``):

* a zip archive with ``meta``, ``gamestate`` and ``ai`` entries (manual saves), and
* a single raw text file with ``meta`` and ``gamestate`` concatenated (autosaves).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TEXT_MAGIC = b"EU4txt"
BINARY_MAGIC = b"EU4bin"


class IronmanSaveError(Exception):
    """Raised when a binary (ironman) save is opened; these are not supported yet."""


@dataclass(frozen=True)
class RawSave:
    """The undecoded text sections of a save file.

    Attributes:
        path: File the save was read from.
        meta: Text of the ``meta`` section (small header with player tag and date).
        gamestate: Text of the ``gamestate`` section (the full world state).
    """

    path: Path
    meta: str
    gamestate: str


def find_latest_save(save_dir: Path) -> Path:
    """Return the most recently modified ``.eu4`` file in ``save_dir``.

    Args:
        save_dir: Folder to search.

    Returns:
        Path to the newest save.

    Raises:
        FileNotFoundError: If the folder contains no ``.eu4`` files.
    """
    raise NotImplementedError


def load_save(path: Path) -> RawSave:
    """Read a save file in either layout and return its text sections.

    Args:
        path: Path to a ``.eu4`` file.

    Returns:
        The raw ``meta`` and ``gamestate`` text.

    Raises:
        IronmanSaveError: If the save is in binary (ironman) format.
    """
    raise NotImplementedError
