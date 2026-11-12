"""Mission trees read from the game's ``missions/`` folder (D-010).

A mission file holds *series* (one column of the in-game mission tree). Each series has
a ``slot`` and contains missions with a ``position``, ``required_missions``, a
``trigger`` (what must be true to complete it) and an ``effect`` (the reward)::

    WoC_austria_1_holy_roman_empire = {
        slot = 1
        potential = { ... }
        hab_imperial_borders = {
            icon = the_imperial_border
            position = 2
            required_missions = { hab_secure_electors }
            trigger = { is_emperor = yes ... }
            effect = { add_imperial_influence = 15 ... }
        }
    }

Which series a country actually has is recorded in the save
(``country_missions.mission_slot``), so ``potential`` conditions never need evaluating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chancellor.game.cache import cached
from chancellor.save.parser import parse

# Keys of a series block that are settings, not missions.
_SERIES_SETTINGS = {
    "slot",
    "generic",
    "ai",
    "potential",
    "potential_on_load",
    "has_country_shield",
}
_MISSION_MARKERS = {"trigger", "effect", "required_missions", "position", "icon"}


@dataclass
class Mission:
    """One mission of a series.

    Attributes:
        name: Mission key, e.g. ``hab_crown_of_bohemia``.
        series: Name of the series it belongs to.
        position: Row in the mission tree (1 = top).
        required: Missions that must be completed first.
        trigger: Conditions to complete it, as parsed script.
        effect: Rewards, as parsed script.
        icon: Icon key.
    """

    name: str
    series: str
    position: int | None
    required: list[str]
    trigger: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] = field(default_factory=dict)
    icon: str | None = None


@dataclass
class MissionSeries:
    """A column of the mission tree."""

    name: str
    slot: int | None
    generic: bool
    missions: list[Mission]


class MissionLibrary:
    """Every mission series defined in the game installation."""

    def __init__(self, series: dict[str, MissionSeries] | None = None) -> None:
        """Create a library from already built series."""
        self._series = series or {}
        self._missions = {m.name: m for s in self._series.values() for m in s.missions}

    @classmethod
    def load(cls, game_dir: Path) -> MissionLibrary:
        """Load from the game installation, reusing the on-disk cache when possible."""
        return cached("missions", [game_dir / "missions"], lambda: cls.parse_game(game_dir))

    @classmethod
    def parse_game(cls, game_dir: Path) -> MissionLibrary:
        """Parse every file in ``<game_dir>/missions`` (about 1 s for the full game)."""
        series: dict[str, MissionSeries] = {}
        folder = game_dir / "missions"
        if folder.is_dir():
            for path in sorted(folder.glob("*.txt")):
                series.update(parse_mission_file(_decode(path.read_bytes())))
        return cls(series)

    def __len__(self) -> int:
        return len(self._series)

    def series(self, name: str) -> MissionSeries | None:
        """A series by name."""
        return self._series.get(name)

    def mission(self, name: str) -> Mission | None:
        """A mission by name, from any series."""
        return self._missions.get(name)


def parse_mission_file(text: str) -> dict[str, MissionSeries]:
    """Parse the content of one mission file into its series.

    Args:
        text: File content, already decoded.

    Returns:
        Series keyed by name.
    """
    result: dict[str, MissionSeries] = {}
    for name, block in parse(text).items():
        if not isinstance(block, dict):
            continue
        missions = []
        for key, value in block.items():
            if key in _SERIES_SETTINGS or not isinstance(value, dict):
                continue
            if not _MISSION_MARKERS & value.keys():
                continue
            missions.append(_mission(key, name, value))
        missions.sort(key=lambda m: (m.position is None, m.position or 0))
        slot = block.get("slot")
        result[name] = MissionSeries(
            name=name,
            slot=slot if isinstance(slot, int) else None,
            generic=block.get("generic") is True,
            missions=missions,
        )
    return result


def _mission(name: str, series: str, block: dict[str, Any]) -> Mission:
    required = block.get("required_missions", [])
    if isinstance(required, dict):  # an empty `{ }` parses as a dict
        required = []
    elif not isinstance(required, list):
        required = [required]
    trigger = block.get("trigger")
    effect = block.get("effect")
    position = block.get("position")
    icon = block.get("icon")
    return Mission(
        name=name,
        series=series,
        position=position if isinstance(position, int) else None,
        required=[str(r) for r in required],
        trigger=trigger if isinstance(trigger, dict) else {},
        effect=effect if isinstance(effect, dict) else {},
        icon=icon if isinstance(icon, str) else None,
    )


def _decode(data: bytes) -> str:
    """Game script files are mostly UTF-8, but some are still Windows-1252."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
