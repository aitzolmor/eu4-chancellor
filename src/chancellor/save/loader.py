"""Locate EU4 save files on disk and extract their raw text sections.

EU4 writes non-ironman saves in two layouts (see ``docs/SAVE_FORMAT.md``):

* ``zip``: an archive with ``meta``, ``gamestate`` and ``ai`` entries (manual saves).
* ``text``: a single plain-text file where the ``meta`` keys are followed directly by the
  ``gamestate`` keys (autosaves).

Both are decoded from Windows-1252 and returned without the ``EU4txt`` magic header.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TEXT_MAGIC = b"EU4txt"
BINARY_MAGIC = b"EU4bin"
ENCODING = "cp1252"
SAVE_SUFFIX = ".eu4"
CONTINUE_GAME_FILE = "continue_game.json"

# First top-level key of the gamestate section (observed on 1.37). In the plain-text
# layout everything before it belongs to the meta section.
_GAMESTATE_FIRST_KEY = b"\nplayers_countries="

SaveLayout = Literal["zip", "text"]


class SaveFormatError(Exception):
    """Raised when a file is not a recognisable EU4 save."""


class IronmanSaveError(SaveFormatError):
    """Raised when a binary (ironman) save is opened; these are not supported yet."""


@dataclass(frozen=True)
class RawSave:
    """The decoded but unparsed text sections of a save file.

    Attributes:
        path: File the save was read from.
        layout: On-disk layout the save was stored in.
        meta: Text of the ``meta`` section (small header with player tag and date).
        gamestate: Text of the ``gamestate`` section (the full world state).
    """

    path: Path
    layout: SaveLayout
    meta: str
    gamestate: str


def find_current_save(save_dir: Path) -> Path:
    """Return the save that belongs to the campaign the player is currently on.

    The game records the save it would resume in ``continue_game.json``, located in the
    user data folder (the parent of ``save_dir``). That is preferred over modification
    time because autosaves rotate and may belong to another playthrough. If the file is
    missing or points to a save that no longer exists, the newest ``.eu4`` file wins.

    Args:
        save_dir: The ``save games`` folder.

    Returns:
        Path to the current save.

    Raises:
        FileNotFoundError: If no save can be found.
    """
    from_continue = _save_from_continue_game(save_dir)
    if from_continue is not None:
        return from_continue
    return find_latest_save(save_dir)


def find_latest_save(save_dir: Path) -> Path:
    """Return the most recently modified ``.eu4`` file in ``save_dir``.

    Args:
        save_dir: Folder to search.

    Returns:
        Path to the newest save.

    Raises:
        FileNotFoundError: If the folder does not exist or contains no ``.eu4`` files.
    """
    if not save_dir.is_dir():
        raise FileNotFoundError(f"Save folder not found: {save_dir}")
    saves = [p for p in save_dir.iterdir() if p.suffix == SAVE_SUFFIX and p.is_file()]
    if not saves:
        raise FileNotFoundError(f"No {SAVE_SUFFIX} files in {save_dir}")
    return max(saves, key=lambda p: p.stat().st_mtime)


def load_save(path: Path) -> RawSave:
    """Read a save file in either layout and return its text sections.

    Args:
        path: Path to a ``.eu4`` file.

    Returns:
        The decoded ``meta`` and ``gamestate`` text, without magic headers.

    Raises:
        IronmanSaveError: If the save is in binary (ironman) format.
        SaveFormatError: If the file is not an EU4 save.
    """
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if not {"meta", "gamestate"} <= names:
                raise SaveFormatError(f"{path} is a zip but lacks meta/gamestate entries")
            meta = archive.read("meta")
            gamestate = archive.read("gamestate")
        return RawSave(
            path=path,
            layout="zip",
            meta=_decode(_strip_magic(meta, path)),
            gamestate=_decode(_strip_magic(gamestate, path)),
        )

    body = _strip_magic(path.read_bytes(), path)
    meta, gamestate = _split_text_save(body)
    return RawSave(path=path, layout="text", meta=_decode(meta), gamestate=_decode(gamestate))


def _save_from_continue_game(save_dir: Path) -> Path | None:
    """Resolve the save referenced by ``continue_game.json``, if usable."""
    user_dir = save_dir.parent
    try:
        data = json.loads((user_dir / CONTINUE_GAME_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    filename = data.get("filename") if isinstance(data, dict) else None
    if not isinstance(filename, str) or not filename:
        return None
    candidate = user_dir / filename
    return candidate if candidate.is_file() else None


def _strip_magic(data: bytes, path: Path) -> bytes:
    """Validate the magic header and return the content after it."""
    if data.startswith(BINARY_MAGIC):
        raise IronmanSaveError(f"{path} is a binary (ironman) save, which is not supported yet")
    if not data.startswith(TEXT_MAGIC):
        raise SaveFormatError(f"{path} is not an EU4 save (missing {TEXT_MAGIC!r} header)")
    return data[len(TEXT_MAGIC) :].lstrip(b"\r\n")


def _split_text_save(body: bytes) -> tuple[bytes, bytes]:
    """Split a plain-text save into its meta and gamestate parts.

    If the gamestate marker is missing, the whole body is returned for both parts so that
    callers can still look up meta keys such as ``player`` and ``date``.
    """
    index = body.find(_GAMESTATE_FIRST_KEY)
    if index == -1:
        return body, body
    return body[: index + 1], body[index + 1 :]


def _decode(data: bytes) -> str:
    """Decode save text. Undefined Windows-1252 bytes are replaced, never fatal."""
    return data.decode(ENCODING, errors="replace")
