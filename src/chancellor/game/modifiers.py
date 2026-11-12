"""Modifier definitions from the game files: what a named modifier actually changes.

Mission rewards and events refer to modifiers by name
(``add_country_modifier = { name = hab_union_with_bohemia }``). The bonuses live in
``common/event_modifiers`` and, for conditional ones, ``common/triggered_modifiers`` and
``common/province_triggered_modifiers``::

    hab_union_with_bohemia = {
        diplomatic_upkeep = 1
        reduced_liberty_desire = 10
    }

Stat names are localised as ``MODIFIER_<KEY>`` or ``<KEY>`` (e.g.
``MODIFIER_DIPLOMATIC_UPKEEP`` → "Relaciones diplomáticas").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chancellor.game.cache import cached
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse

_FOLDERS = ("event_modifiers", "triggered_modifiers", "province_triggered_modifiers")
# Keys of a modifier block that describe the modifier rather than change a stat.
_META_KEYS = {
    "potential",
    "trigger",
    "on_activation",
    "on_deactivation",
    "picture",
    "icon",
    "religion",
    "secondary_religion",
    "is_bad",
    "hidden",
}
# Stats whose fractional values are plain numbers, not percentages.
_PLAIN_PREFIXES = ("yearly_", "monthly_", "global_unrest", "local_unrest", "max_")
_PLAIN_STATS = {
    "prestige",
    "legitimacy",
    "stability",
    "diplomatic_upkeep",
    "tolerance_own",
    "war_exhaustion",
    "army_tradition",
    "navy_tradition",
    "papal_influence",
    "devotion",
    "republican_tradition",
    "meritocracy",
    "horde_unity",
    "church_power",
}

_MAX_NAME_LENGTH = 60

Effects = list[tuple[str, Any]]


class ModifierLibrary:
    """Named modifiers and the stats they change."""

    def __init__(self, modifiers: dict[str, Effects] | None = None) -> None:
        """Create a library from already extracted effects."""
        self._modifiers = modifiers or {}

    @classmethod
    def load(cls, game_dir: Path) -> ModifierLibrary:
        """Load from the game installation, reusing the on-disk cache when possible."""
        return cached(
            "modifiers",
            [game_dir / "common" / f for f in _FOLDERS],
            lambda: cls.parse_game(game_dir),
        )

    @classmethod
    def parse_game(cls, game_dir: Path) -> ModifierLibrary:
        """Parse the modifier folders of the game installation."""
        modifiers: dict[str, Effects] = {}
        for folder in _FOLDERS:
            path = game_dir / "common" / folder
            if not path.is_dir():
                continue
            for file in sorted(path.glob("*.txt")):
                modifiers.update(parse_modifier_file(_decode(file.read_bytes())))
        return cls(modifiers)

    def __len__(self) -> int:
        return len(self._modifiers)

    def __contains__(self, name: object) -> bool:
        return name in self._modifiers

    def effects(self, name: str) -> Effects:
        """``(stat, value)`` pairs of a modifier; empty if unknown."""
        return self._modifiers.get(name, [])


def parse_modifier_file(text: str) -> dict[str, Effects]:
    """Extract the stat changes of every modifier defined in a file."""
    result: dict[str, Effects] = {}
    for name, block in parse(text).items():
        if not isinstance(block, dict):
            continue
        result[name] = [
            (stat, value)
            for stat, value in block.items()
            if stat not in _META_KEYS and isinstance(value, int | float | bool)
        ]
    return result


def format_effect(stat: str, value: Any, loc: Localisation) -> str:
    """One stat change in readable form, e.g. ``"Coste de desarrollo local -10%"``.

    Fractional values below 1 are shown as percentages unless the stat is a known plain
    number (prestige, yearly or monthly gains, ...).
    """
    name = _stat_name(stat, loc)
    if value is True:
        return name
    if value is False:
        return f"{name}: no"
    fractional = isinstance(value, float) and not value.is_integer() and abs(value) < 1
    plain = stat.startswith(_PLAIN_PREFIXES) or stat in _PLAIN_STATS
    if fractional and not plain:
        return f"{name} {value * 100:+g}%"
    return f"{name} {value:+g}"


def _stat_name(stat: str, loc: Localisation) -> str:
    """Localised stat name; several stats have no entry and fall back to the key."""
    for key in (f"MODIFIER_{stat.upper()}", stat, stat.upper()):
        text = " ".join(loc.get(key, "").replace("§Y", "").replace("§!", "").split())
        if text and len(text) <= _MAX_NAME_LENGTH:  # longer entries are descriptions
            return text.rstrip(":").strip()
    return stat.replace("_", " ")


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
