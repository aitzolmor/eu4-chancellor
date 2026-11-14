"""Static game data needed to evaluate conditions (D-010).

Conditions such as ``culture_group = germanic``, ``region = north_german_region`` or
``is_free_or_tributary_trigger = yes`` refer to definitions in the game files:

* ``common/cultures`` and ``common/religions``: which group each culture/religion is in;
* ``map/area.txt``, ``map/region.txt``, ``map/superregion.txt``, ``map/continent.txt``
  and ``common/colonial_regions``: which provinces each geographic name covers;
* ``common/scripted_triggers``: named, reusable conditions;
* ``common/government_reforms``: the government attributes each reform grants
  (``has_government_attribute``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chancellor.game.cache import cached
from chancellor.save.parser import Repeated, parse

# Folders under common/ read by GameRules (the map/ folder is read too).
_RULE_FOLDERS = (
    "cultures",
    "religions",
    "scripted_triggers",
    "colonial_regions",
    "government_reforms",
)
# Keys inside a culture or religion group that are not cultures/religions.
_GROUP_SETTINGS = {"country", "province", "flags_with_emblem_percentage", "flag_emblem_index_range"}


@dataclass
class GameRules:
    """Lookup tables built from the game files.

    Attributes:
        culture_groups: Culture → culture group.
        religion_groups: Religion → religion group.
        geography: Area, region, superregion or continent name → province ids.
        scripted_triggers: Name → condition block.
        government_attributes: Reform → attribute → whether the reform always grants it
            (``False`` when it only does so under a ``conditional`` block, such as one
            that depends on a DLC).
    """

    culture_groups: dict[str, str] = field(default_factory=dict)
    religion_groups: dict[str, str] = field(default_factory=dict)
    geography: dict[str, frozenset[int]] = field(default_factory=dict)
    scripted_triggers: dict[str, dict[str, Any]] = field(default_factory=dict)
    government_attributes: dict[str, dict[str, bool]] = field(default_factory=dict)

    @classmethod
    def load(cls, game_dir: Path) -> GameRules:
        """Load from the game installation, reusing the on-disk cache when possible."""
        return cached(
            "rules",
            [game_dir / "common" / d for d in _RULE_FOLDERS] + [game_dir / "map"],
            lambda: cls.parse_game(game_dir),
        )

    @classmethod
    def parse_game(cls, game_dir: Path) -> GameRules:
        """Read every table from the game installation."""
        rules = cls()
        for path in _files(game_dir / "common" / "cultures"):
            rules.culture_groups.update(_members_by_group(parse(_read(path))))
        for path in _files(game_dir / "common" / "religions"):
            rules.religion_groups.update(_members_by_group(parse(_read(path))))
        for path in _files(game_dir / "common" / "scripted_triggers"):
            for name, block in parse(_read(path)).items():
                if isinstance(block, dict):
                    rules.scripted_triggers[name] = block
        for path in _files(game_dir / "common" / "government_reforms"):
            rules.government_attributes.update(_reform_attributes(parse(_read(path))))
        rules.geography = _geography(game_dir / "map")
        return rules


def _reform_attributes(document: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """``{reform: {custom_attributes: {...}, conditional: {...}}}`` → attributes."""
    result: dict[str, dict[str, bool]] = {}
    for reform, block in document.items():
        if not isinstance(block, dict):
            continue
        attributes: dict[str, bool] = {}
        for name in _attributes(block.get("custom_attributes")):
            attributes[name] = True
        for conditional in as_values(block.get("conditional")):
            if isinstance(conditional, dict):
                for name in _attributes(conditional.get("custom_attributes")):
                    attributes.setdefault(name, False)
        if attributes:
            result[reform] = attributes
    return result


def _attributes(block: Any) -> list[str]:
    """Names set to ``yes`` in one or more ``custom_attributes`` blocks."""
    names = []
    for item in as_values(block):
        if isinstance(item, dict):
            names += [key for key, value in item.items() if value is True]
    return names


def as_values(value: Any) -> list[Any]:
    """A value that may be repeated (the parser groups repeated keys) as a list."""
    if value is None:
        return []
    if isinstance(value, Repeated | list):
        return list(value)
    return [value]


def _members_by_group(document: dict[str, Any]) -> dict[str, str]:
    """``{group: {member: {...}}}`` → ``{member: group}``."""
    result = {}
    for group, block in document.items():
        if not isinstance(block, dict):
            continue
        for member, value in block.items():
            if isinstance(value, dict) and member not in _GROUP_SETTINGS:
                result[member] = group
    return result


def _geography(map_dir: Path) -> dict[str, frozenset[int]]:
    geography: dict[str, frozenset[int]] = {}

    def ids(value: Any) -> frozenset[int]:
        values = value if isinstance(value, list) else [value]
        return frozenset(v for v in values if isinstance(v, int))

    for name in ("area.txt", "continent.txt"):
        path = map_dir / name
        if path.is_file():
            for key, value in parse(_read(path)).items():
                geography[key] = ids(value) if not isinstance(value, dict) else frozenset()

    regions = map_dir / "region.txt"
    if regions.is_file():
        for region, block in parse(_read(regions)).items():
            areas = block.get("areas", []) if isinstance(block, dict) else []
            areas = areas if isinstance(areas, list) else [areas]
            geography[region] = frozenset().union(*(geography.get(a, frozenset()) for a in areas))

    colonial = map_dir.parent / "common" / "colonial_regions"
    for path in _files(colonial):
        for name, block in parse(_read(path)).items():
            if isinstance(block, dict):
                geography[name] = ids(block.get("provinces", []))

    superregions = map_dir / "superregion.txt"
    if superregions.is_file():
        for name, value in parse(_read(superregions)).items():
            members = value if isinstance(value, list) else []
            provinces = [geography.get(r, frozenset()) for r in members if isinstance(r, str)]
            geography[name] = frozenset().union(*provinces)
    return geography


def _files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []


def _read(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
