"""What creating a core costs, from the game files (D-033).

Coring a province costs administrative power per point of development and takes months.
The parts come from:

* ``common/defines.lua``: the cost per point of development (``PS_MAKE_PROVINCE_CORE``),
  the months it takes (``MONTHS_TO_CORE`` and its bounds) and the discount of a claim
  (``CORE_HAD_CLAIM``);
* the ``core_creation`` (and ``local_core_creation``) of ideas, policies, government
  reforms, estate privileges, golden bulls, imperial reforms and static and event
  modifiers (war exhaustion, per point, is a static modifier);
* ``all_power_cost`` per point of corruption and innovativeness;
* ``common/technologies``: administrative efficiency.

Two rules are not in the files: a territory pays half, read off the game's tooltip
(Austria, 1492: Friaul 61, Treviso 102); the cap of 30 development and the -80% floor of
the summed modifiers come from the game wiki's Core page (checked for 1.37).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chancellor.game.ae_rules import admin_efficiency_by_level
from chancellor.game.cache import cached
from chancellor.game.modifiers import _decode
from chancellor.save.parser import parse

TERRITORY_FACTOR = 0.5
DEVELOPMENT_CAP = 30.0
MODIFIER_FLOOR = -0.8
CORE_STATS = ("core_creation", "local_core_creation")

# Values of game version 1.37, used when the game files cannot be read.
DEFAULT_DEFINES: dict[str, float] = {
    "PS_MAKE_PROVINCE_CORE": 10,
    "MONTHS_TO_CORE": 36,
    "MONTHS_TO_CORE_MINIMUM": 6,
    "MONTHS_TO_CORE_MAXIMUM": 240,
    "CORE_HAD_CLAIM": 0.1,
    "CORE_HAD_PERMANENT_CLAIM": 0.25,
}
_DEFINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?)", re.MULTILINE)
_FOLDERS = (
    "defines.lua",
    "ideas",
    "policies",
    "government_reforms",
    "estate_privileges",
    "golden_bulls",
    "imperial_reforms",
    "static_modifiers",
    "event_modifiers",
    "technologies",
)
# Keys of an idea group that are not ideas.
_IDEA_META = {"category", "start", "bonus", "trigger", "free", "ai_will_do", "important"}


@dataclass
class IdeaGroup:
    """The coring changes of one idea group.

    Attributes:
        start: The change every country with the group has (national traditions).
        ideas: The change of each idea, in the order they are taken.
        bonus: The change once every idea is taken.
    """

    start: float = 0.0
    ideas: list[float] = field(default_factory=list)
    bonus: float = 0.0


@dataclass
class CoringRules:
    """Core creation rules.

    Attributes:
        defines: Named numbers from ``defines.lua`` (see :data:`DEFAULT_DEFINES`).
        modifiers: Static or event modifier → its coring cost change.
        war_exhaustion: Coring cost change per point of war exhaustion.
        idea_groups: Idea group → its coring changes, for groups that have any.
        policies: Policy → its coring cost change.
        government_reforms: Reform → its coring cost change.
        privileges: Estate privilege → its coring cost change.
        golden_bulls: Bull → its coring cost change.
        imperial_reforms: Reform → ``{scope: change}`` (``member``, ``emperor``, ``all``).
        corruption_power_cost: ``all_power_cost`` per point of corruption.
        innovativeness_power_cost: ``all_power_cost`` per point of innovativeness.
        admin_efficiency: Administrative technology level → administrative efficiency.
    """

    defines: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DEFINES))
    modifiers: dict[str, float] = field(default_factory=dict)
    war_exhaustion: float = 0.03
    idea_groups: dict[str, IdeaGroup] = field(default_factory=dict)
    policies: dict[str, float] = field(default_factory=dict)
    government_reforms: dict[str, float] = field(default_factory=dict)
    privileges: dict[str, float] = field(default_factory=dict)
    golden_bulls: dict[str, float] = field(default_factory=dict)
    imperial_reforms: dict[str, dict[str, float]] = field(default_factory=dict)
    corruption_power_cost: float = 1.0
    innovativeness_power_cost: float = -0.1
    admin_efficiency: dict[int, float] = field(default_factory=dict)

    def define(self, name: str) -> float:
        """A number from ``defines.lua``, or its 1.37 value."""
        return self.defines.get(name, DEFAULT_DEFINES[name])

    @classmethod
    def load(cls, game_dir: Path) -> CoringRules:
        """Load from the game installation, reusing the on-disk cache when possible."""
        sources = [game_dir / "common" / name for name in _FOLDERS]
        return cached("coring_rules", sources, lambda: cls.parse_game(game_dir))

    @classmethod
    def parse_game(cls, game_dir: Path) -> CoringRules:
        """Read every rule from the game installation."""
        common = game_dir / "common"
        rules = cls()
        defines = common / "defines.lua"
        if defines.is_file():
            found = {m.group(1): float(m.group(2)) for m in _DEFINE.finditer(_read(defines))}
            rules.defines.update({k: v for k, v in found.items() if k in DEFAULT_DEFINES})
        for path in _files(common / "ideas"):
            for name, block in parse(_read(path)).items():
                group = parse_idea_group(block)
                if group is not None:
                    rules.idea_groups[name] = group
        for path in _files(common / "policies"):
            _collect(rules.policies, parse(_read(path)), lambda block: block)
        for path in _files(common / "government_reforms"):
            _collect(
                rules.government_reforms, parse(_read(path)), lambda block: block.get("modifiers")
            )
        for path in _files(common / "estate_privileges"):
            for name, block in parse(_read(path)).items():
                if isinstance(block, dict):
                    change = _change(block.get("benefits")) + _change(block.get("penalties"))
                    if change:
                        rules.privileges[name] = change
        for path in _files(common / "golden_bulls"):
            _collect(rules.golden_bulls, parse(_read(path)), lambda block: block.get("modifier"))
        for path in _files(common / "imperial_reforms"):
            for name, block in parse(_read(path)).items():
                if not isinstance(block, dict):
                    continue
                scopes = {
                    scope: change
                    for scope in ("member", "emperor", "all")
                    if (change := _change(block.get(scope)))
                }
                if scopes:
                    rules.imperial_reforms[name] = scopes
        for folder in ("static_modifiers", "event_modifiers"):
            for path in _files(common / folder):
                document = parse(_read(path))
                _collect(rules.modifiers, document, lambda block: block)
                for name, attribute in (
                    ("corruption", "corruption_power_cost"),
                    ("innovativeness", "innovativeness_power_cost"),
                ):
                    block = document.get(name)
                    cost = block.get("all_power_cost") if isinstance(block, dict) else None
                    if folder == "static_modifiers" and isinstance(cost, int | float):
                        setattr(rules, attribute, float(cost))
        if "war_exhaustion" in rules.modifiers:
            rules.war_exhaustion = rules.modifiers.pop("war_exhaustion")
        adm = common / "technologies" / "adm.txt"
        if adm.is_file():
            rules.admin_efficiency = admin_efficiency_by_level(_read(adm))
        return rules


def parse_idea_group(block: Any) -> IdeaGroup | None:
    """The coring changes of an idea group block, or ``None`` if it has none."""
    if not isinstance(block, dict) or "category" not in block and "start" not in block:
        return None
    ideas = [
        _change(value)
        for key, value in block.items()
        if key not in _IDEA_META and isinstance(value, dict)
    ]
    group = IdeaGroup(_change(block.get("start")), ideas, _change(block.get("bonus")))
    return group if group.start or group.bonus or any(ideas) else None


def _collect(table: dict[str, float], document: dict[str, Any], body: Any) -> None:
    """Add every block of ``document`` whose ``body(block)`` changes coring."""
    for name, block in document.items():
        if isinstance(block, dict):
            change = _change(body(block))
            if change:
                table[name] = change


def _change(block: Any) -> float:
    """The coring cost change of a modifier block (0 if it has none)."""
    if not isinstance(block, dict):
        return 0.0
    return sum(float(v) for k in CORE_STATS if isinstance(v := block.get(k), int | float))


def _files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []


def _read(path: Path) -> str:
    return _decode(path.read_bytes())
