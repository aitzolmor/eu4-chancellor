"""What developing a province costs, from the game files (D-031).

Developing a province (+1 tax, production or manpower) costs a base of 50 monarch points,
changed by the province and its country. The parts come from:

* the province's terrain (:class:`TerrainMap`) and climate (``map/climate.txt`` and the
  ``tropical`` / ``arid`` / ``arctic`` static modifiers);
* ``common/static_modifiers``: ``development_scaled`` (per point of development
  already there) and ``prosperity``;
* ``common/centers_of_trade``: the discount of a centre of trade by level;
* ``common/institutions``: the bonus of each embraced institution;
* ``common/golden_bulls``: the bull in force for the papacy's religion;
* ``common/imperial_reforms``: passed reforms, for the Empire's provinces or members;
* ``common/event_modifiers``: active country and province modifiers.

Three rules are not in the files and were read off the game's tooltips (Austria,
1483): the base of 50; the capital's discount of 0.05% per point of the country's
development; and the growth per point of development, +3% from 10 and +6% from 20.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chancellor.game.cache import cached
from chancellor.game.modifiers import _decode
from chancellor.game.terrain import TerrainMap
from chancellor.save.parser import parse

BASE_COST = 50.0
CAPITAL_DISCOUNT_PER_DEVELOPMENT = -0.0005
_COST_STATS = ("development_cost", "local_development_cost", "development_cost_modifier")
_FOLDERS = (
    "static_modifiers",
    "centers_of_trade",
    "institutions",
    "golden_bulls",
    "imperial_reforms",
    "event_modifiers",
)
_CLIMATES = ("tropical", "arid", "arctic")


@dataclass
class DevelopmentRules:
    """Development cost rules.

    Attributes:
        terrain: Each province's terrain and the terrain categories.
        climate: Province id → climate (``tropical``, ``arid`` or ``arctic``).
        static: Static modifier → its development cost change (``prosperity``,
            ``development_scaled``, the climates, ...).
        centers_of_trade: Centre of trade level → its discount for its own province.
        state_centers_of_trade: Centre of trade level → its discount for every province
            of its state (level 3).
        institutions: Institution → the development cost change of embracing it.
        institution_order: Every institution, in the order of the save's list.
        golden_bulls: Bull → its development cost change.
        imperial_reforms: Reform → ``{scope: change}`` (``province``, ``member``,
            ``emperor``, ``all``).
        modifiers: Event modifier → its development cost change, for those that have one.
        corruption_power_cost: ``all_power_cost`` per point of corruption.
        innovativeness_power_cost: ``all_power_cost`` per point of innovativeness.
    """

    terrain: TerrainMap = field(default_factory=TerrainMap)
    climate: dict[int, str] = field(default_factory=dict)
    static: dict[str, float] = field(default_factory=dict)
    centers_of_trade: dict[int, float] = field(default_factory=dict)
    state_centers_of_trade: dict[int, float] = field(default_factory=dict)
    institutions: dict[str, float] = field(default_factory=dict)
    institution_order: list[str] = field(default_factory=list)
    corruption_power_cost: float = 1.0
    innovativeness_power_cost: float = -0.1
    golden_bulls: dict[str, float] = field(default_factory=dict)
    imperial_reforms: dict[str, dict[str, float]] = field(default_factory=dict)
    modifiers: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, game_dir: Path) -> DevelopmentRules:
        """Load from the game installation, reusing the on-disk cache when possible."""
        sources = [game_dir / "common" / name for name in _FOLDERS]
        sources.append(game_dir / "map" / "climate.txt")
        rules = cached("development_rules", sources, lambda: cls.parse_game(game_dir))
        rules.terrain = TerrainMap.load(game_dir)
        return rules

    @classmethod
    def parse_game(cls, game_dir: Path) -> DevelopmentRules:
        """Read every rule from the game installation (without the terrain map)."""
        common = game_dir / "common"
        rules = cls()
        for path in _files(common / "static_modifiers"):
            for name, block in parse(_read(path)).items():
                change = _cost(block)
                if change:
                    rules.static[name] = change
                if name in ("corruption", "innovativeness") and isinstance(block, dict):
                    cost = block.get("all_power_cost")
                    if isinstance(cost, int | float):
                        setattr(rules, f"{name}_power_cost", float(cost))
        for path in _files(common / "centers_of_trade"):
            for block in parse(_read(path)).values():
                if not isinstance(block, dict) or not isinstance(block.get("level"), int):
                    continue
                level = int(block["level"])
                for key, table in (
                    ("province_modifiers", rules.centers_of_trade),
                    ("state_modifiers", rules.state_centers_of_trade),
                ):
                    change = _cost(block.get(key))
                    if change:  # coastal and inland centres of a level give the same
                        table[level] = min(change, table.get(level, 0.0))
        for path in _files(common / "institutions"):
            for name, block in parse(_read(path)).items():
                if not isinstance(block, dict):
                    continue
                rules.institution_order.append(name)
                change = _cost(block.get("bonus"))
                if change:
                    rules.institutions[name] = change
        for path in _files(common / "golden_bulls"):
            for name, block in parse(_read(path)).items():
                change = _cost(block.get("modifier")) if isinstance(block, dict) else 0.0
                if change:
                    rules.golden_bulls[name] = change
        for path in _files(common / "imperial_reforms"):
            for name, block in parse(_read(path)).items():
                if not isinstance(block, dict):
                    continue
                scopes = {
                    scope: change
                    for scope in ("province", "member", "emperor", "all")
                    if (change := _cost(block.get(scope)))
                }
                if scopes:
                    rules.imperial_reforms[name] = scopes
        for path in _files(common / "event_modifiers"):
            for name, block in parse(_read(path)).items():
                change = _cost(block)
                if change:
                    rules.modifiers[name] = change
        climate = game_dir / "map" / "climate.txt"
        if climate.is_file():
            for name, value in parse(_read(climate)).items():
                if name in _CLIMATES:
                    for province in value if isinstance(value, list) else [value]:
                        if isinstance(province, int):
                            rules.climate[province] = name
        return rules


def _cost(block: Any) -> float:
    """The development cost change of a modifier block (0 if it has none)."""
    if not isinstance(block, dict):
        return 0.0
    return sum(float(v) for k in _COST_STATS if isinstance(v := block.get(k), int | float))


def _files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []


def _read(path: Path) -> str:
    return _decode(path.read_bytes())
