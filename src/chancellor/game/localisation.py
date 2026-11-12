"""Readable names from the game's localisation files.

Localisation lives in ``<game_dir>/localisation/*_l_<language>.yml``. Despite the
extension, the files are not standard YAML. Each line looks like::

    l_spanish:
     CAS:0 "Castilla"
     PROV219:0 "Toledo"

Files are UTF-8 with a BOM. Later files override earlier ones, mirroring the game.
"""

from __future__ import annotations

import re
from pathlib import Path

from chancellor.game.cache import cached

DEFAULT_LANGUAGE = "english"

_ENTRY = re.compile(r'^\s*([\w.\-]+):\d*\s*"(.*)"\s*(?:#.*)?$')
_LANGUAGE_SETTING = re.compile(r'^language="l_(\w+)"', re.MULTILINE)


class Localisation:
    """Lookup table from localisation keys to display text."""

    def __init__(self, entries: dict[str, str] | None = None) -> None:
        """Create a table from already loaded entries.

        Args:
            entries: Mapping of localisation keys to text.
        """
        self._entries = entries or {}

    @classmethod
    def load(cls, game_dir: Path, language: str = DEFAULT_LANGUAGE) -> Localisation:
        """Load a language from the game installation, reusing the on-disk cache."""
        return cached(
            f"localisation-{language}",
            [game_dir / "localisation"],
            lambda: cls.parse_game(game_dir, language),
        )

    @classmethod
    def parse_game(cls, game_dir: Path, language: str = DEFAULT_LANGUAGE) -> Localisation:
        """Parse every localisation file for ``language`` from the game installation.

        Args:
            game_dir: EU4 installation folder.
            language: Language name without the ``l_`` prefix, e.g. ``"spanish"``.

        Returns:
            The loaded table. Empty if the folder or language does not exist.
        """
        entries: dict[str, str] = {}
        folder = game_dir / "localisation"
        if folder.is_dir():
            for path in sorted(folder.rglob(f"*_l_{language}.yml")):
                entries.update(parse_localisation(path.read_text(encoding="utf-8-sig")))
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str, default: str | None = None) -> str:
        """Return the text for ``key``, or ``default`` (the key itself if not given)."""
        return self._entries.get(key, key if default is None else default)

    def country(self, tag: str) -> str:
        """Return a country's display name, falling back to its tag."""
        return self._entries.get(tag, tag)

    def province(self, province_id: int | str) -> str:
        """Return a province's display name, falling back to ``"Province <id>"``."""
        number = str(province_id).lstrip("-")
        return self._entries.get(f"PROV{number}", f"Province {number}")


def parse_localisation(text: str) -> dict[str, str]:
    """Parse the content of one localisation file.

    Args:
        text: File content, already decoded.

    Returns:
        Mapping of keys to text. Lines that are not entries are ignored.
    """
    entries: dict[str, str] = {}
    for line in text.splitlines():
        match = _ENTRY.match(line)
        if match:
            entries[match.group(1)] = match.group(2)
    return entries


def detect_language(user_dir: Path) -> str:
    """Read the language the player has selected from the game's ``settings.txt``.

    Args:
        user_dir: The EU4 user data folder (parent of ``save games``).

    Returns:
        Language name without the ``l_`` prefix, or :data:`DEFAULT_LANGUAGE`.
    """
    try:
        text = (user_dir / "settings.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return DEFAULT_LANGUAGE
    match = _LANGUAGE_SETTING.search(text)
    return match.group(1) if match else DEFAULT_LANGUAGE
