"""What monarch power buys, from the game files (D-010, D-029).

The save does not store what a technology or an idea costs: the game works it out on
the fly. These are the rules it uses, read from the installed game:

* ``common/defines.lua``: base costs (``PS_ADVANCE_TECH = 600``, ``PS_BUY_IDEA = 400``,
  ``PS_BOOST_STABILITY = 100``, ``PS_BUY_GENERAL = 50``), the technology cost rules
  (``TECH_AHEAD_OF_TIME``, ``IDEA_TO_TECH``, ``NEIGHBOURBONUS``), monthly power
  (``BASE_POWER_INCREASE``, national focus) and leader upkeep
  (``LEADER_MAINTENANCE_COST``);
* ``common/technologies``: each level's year and the institutions it expects;
* ``common/institutions``: their order, which is the order of the save's
  ``institutions`` list;
* ``common/advisortypes``: the power category each advisor type adds to;
* ``common/ideas``: the category of each idea group (ideas only make technology of their
  own category cheaper);
* ``common/event_modifiers``: the modifiers that change technology costs, so the ones
  active in a country (the save lists them) can be counted;
* ``common/static_modifiers``: the free leader pool every country gets
  (``base_values``), the one the Emperor adds and the one for 25 power projection
  (``power_projection_25``), and what each point of corruption and of innovativeness
  does to power costs (``all_power_cost``).

One rule is not in the files: 50 power projection adds 1 point a month in every
category (the game's tooltip lists it). It is :data:`POWER_PROJECTION_BONUS`.

When a value cannot be read, the 1.37 value is used, so the costs still come out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from chancellor.game.cache import cached
from chancellor.game.modifiers import _decode
from chancellor.save.parser import get_all, parse

CATEGORIES = ("adm", "dip", "mil")
# Built into the game, not in its files: from this much power projection a country gains
# 1 more point a month in every category ("At least 50 power projection: +1").
POWER_PROJECTION_BONUS = (50.0, 1.0)

# Values of game version 1.37, used when the game files cannot be read.
DEFAULT_DEFINES: dict[str, float] = {
    "PS_ADVANCE_TECH": 600,
    "PS_BUY_IDEA": 400,
    "PS_BOOST_STABILITY": 100,
    "PS_BUY_GENERAL": 50,
    "IDEA_TO_TECH": -0.02,
    "TECH_AHEAD_OF_TIME": 0.1,
    "NEIGHBOURBONUS": -0.05,
    "NEIGHBOURBONUS_CAP": -0.75,
    "BASE_POWER_INCREASE": 3,
    "NAT_FOCUS_INCREASE": 2,
    "NAT_FOCUS_DECREASE": -1,
    "LEADER_MAINTENANCE_COST": 1,
    "POWER_MAX": 999,
    "TECH_TIME_COST": 0.3,
}
_DEFINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?)", re.MULTILINE)
_DATE_DEFINE = re.compile(r'^\s*(START_DATE|END_DATE)\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.MULTILINE)
_FOLDERS = (
    "technologies",
    "institutions",
    "advisortypes",
    "static_modifiers",
    "ideas",
    "event_modifiers",
)
# Stats that change what a technology costs.
TECH_COST_STATS = (
    "technology_cost",
    "adm_tech_cost_modifier",
    "dip_tech_cost_modifier",
    "mil_tech_cost_modifier",
    "all_power_cost",
)


@dataclass(frozen=True)
class TechLevel:
    """One technology level.

    Attributes:
        level: The level number (0 is the starting one).
        year: The year it belongs to; researching it earlier costs more.
        institutions: Institution → cost penalty share when it is not embraced.
    """

    level: int
    year: int
    institutions: dict[str, float] = field(default_factory=dict)


@dataclass
class PowerRules:
    """Cost rules for monarch power.

    Attributes:
        defines: Named numbers from ``defines.lua`` (see :data:`DEFAULT_DEFINES`).
        techs: Category (``adm``/``dip``/``mil``) → its levels, in order.
        institutions: Institution keys in the order of the save's ``institutions`` list.
        advisor_categories: Advisor type → the category it adds power to.
        base_free_leaders: The free leader pool every country has.
        emperor_free_leaders: The extra free leaders of the Holy Roman Emperor.
        power_projection_free_leaders: The extra free leaders from 25 power projection.
        start_year: The game's start date as a fractional year (1444.11.11).
        end_year: The game's end date as a fractional year (1821.1.2).
        idea_categories: Idea group → the category of its ideas.
        tech_cost_modifiers: Modifier → its technology cost stats (see
            :data:`TECH_COST_STATS`), for the modifiers that have any.
        corruption_power_cost: ``all_power_cost`` per point of corruption.
        innovativeness_power_cost: ``all_power_cost`` per point of innovativeness.
    """

    defines: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DEFINES))
    techs: dict[str, list[TechLevel]] = field(default_factory=dict)
    institutions: list[str] = field(default_factory=list)
    advisor_categories: dict[str, str] = field(default_factory=dict)
    base_free_leaders: int = 1
    emperor_free_leaders: int = 1
    power_projection_free_leaders: int = 1
    start_year: float = 1444 + 10 / 12 + 10 / 365
    end_year: float = 1821 + 1 / 365
    idea_categories: dict[str, str] = field(default_factory=dict)
    tech_cost_modifiers: dict[str, dict[str, float]] = field(default_factory=dict)
    corruption_power_cost: float = 1.0
    innovativeness_power_cost: float = -0.1

    def define(self, name: str) -> float:
        """A number from ``defines.lua``, or its 1.37 value."""
        return self.defines.get(name, DEFAULT_DEFINES[name])

    @classmethod
    def load(cls, game_dir: Path) -> PowerRules:
        """Load from the game installation, reusing the on-disk cache when possible."""
        sources = [game_dir / "common" / name for name in _FOLDERS]
        sources.append(game_dir / "common" / "defines.lua")
        return cached("power_rules", sources, lambda: cls.parse_game(game_dir))

    @classmethod
    def parse_game(cls, game_dir: Path) -> PowerRules:
        """Read every rule from the game installation."""
        common = game_dir / "common"
        rules = cls()
        defines = common / "defines.lua"
        if defines.is_file():
            found = {m.group(1): float(m.group(2)) for m in _DEFINE.finditer(_read(defines))}
            rules.defines.update({k: v for k, v in found.items() if k in DEFAULT_DEFINES})
            for name, year, month, day in _DATE_DEFINE.findall(_read(defines)):
                value = int(year) + (int(month) - 1) / 12 + (int(day) - 1) / 365
                setattr(rules, "start_year" if name == "START_DATE" else "end_year", value)
        for path in _files(common / "technologies"):
            category, levels = parse_technology_file(_read(path))
            if category:
                rules.techs[category] = levels
        for path in _files(common / "institutions"):
            rules.institutions += [k for k, v in parse(_read(path)).items() if isinstance(v, dict)]
        for path in _files(common / "advisortypes"):
            for name, block in parse(_read(path)).items():
                power = block.get("monarch_power") if isinstance(block, dict) else None
                if isinstance(power, str):
                    rules.advisor_categories[name] = power.lower()
        for path in _files(common / "ideas"):
            for name, block in parse(_read(path)).items():
                category = block.get("category") if isinstance(block, dict) else None
                if isinstance(category, str):
                    rules.idea_categories[name] = category.lower()
        for path in _files(common / "event_modifiers"):
            for name, block in parse(_read(path)).items():
                stats = _tech_cost_stats(block)
                if stats:
                    rules.tech_cost_modifiers[name] = stats
        for path in _files(common / "static_modifiers"):
            document = parse(_read(path))
            for name, attribute in (
                ("corruption", "corruption_power_cost"),
                ("innovativeness", "innovativeness_power_cost"),
            ):
                block = document.get(name)
                cost = block.get("all_power_cost") if isinstance(block, dict) else None
                if isinstance(cost, int | float):
                    setattr(rules, attribute, float(cost))
            for name, attribute in (
                ("base_values", "base_free_leaders"),
                ("emperor", "emperor_free_leaders"),
                ("power_projection_25", "power_projection_free_leaders"),
            ):
                block = document.get(name)
                pool = block.get("free_leader_pool") if isinstance(block, dict) else None
                if isinstance(pool, int | float):
                    setattr(rules, attribute, int(pool))
        return rules


def parse_technology_file(text: str) -> tuple[str | None, list[TechLevel]]:
    """``monarch_power = MIL`` and the ``technology`` blocks of one file."""
    document = parse(text)
    power = document.get("monarch_power")
    category = power.lower() if isinstance(power, str) else None
    levels = []
    for index, block in enumerate(get_all(document, "technology")):
        if not isinstance(block, dict):
            continue
        expected = block.get("expects_institution")
        institutions = {
            str(k): float(v)
            for k, v in (expected.items() if isinstance(expected, dict) else [])
            if isinstance(v, int | float)
        }
        year = block.get("year")
        levels.append(
            TechLevel(index, int(year) if isinstance(year, int | float) else 0, institutions)
        )
    return category, levels


def _tech_cost_stats(block: object) -> dict[str, float]:
    """The technology cost stats of a modifier block."""
    if not isinstance(block, dict):
        return {}
    return {
        stat: float(value)
        for stat in TECH_COST_STATS
        if isinstance(value := block.get(stat), int | float) and value
    }


def _files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []


def _read(path: Path) -> str:
    return _decode(path.read_bytes())
