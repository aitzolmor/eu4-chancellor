"""How much aggressive expansion (AE) a conquest causes, from the game files (D-030).

Taking a province in a peace deal adds AE to the countries around it. The rules live in
several files:

* ``common/defines.lua``: AE per development of a demanded province
  (``PO_DEMAND_PROVINCES_AE``), the development cap per province (``AE_PROVINCE_CAP``),
  and how culture, religion, the Empire and distance change what each country receives
  (``AE_SAME_CULTURE``, ``AE_SAME_RELIGION``, ``AE_HRE_INTERNAL``, ``AE_DISTANCE_BASE``
  and friends);
* ``common/wargoal_types``: the casus belli factor (``badboy_factor``): a claim
  (``take_claim``) counts fully, a core (``take_core``) a quarter;
* ``common/static_modifiers``: what prestige does to AE (``ae_impact`` per 100);
* ``common/technologies``: administrative efficiency, which also lowers AE;
* ``map/positions.txt``: where each province is, to measure distances.

How the numbers combine follows the game wiki's formula (written for 1.24, with the
1.37 values from ``defines.lua``). Two parts are not documented for 1.37 and are
estimates until checked against a peace deal: the exact distance falloff and which
distant countries receive no AE at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from chancellor.game.cache import cached
from chancellor.game.modifiers import _decode
from chancellor.save.parser import get_all, parse

# Values of game version 1.37, used when the game files cannot be read.
DEFAULT_DEFINES: dict[str, float] = {
    "PO_DEMAND_PROVINCES_AE": 0.6,
    "AE_PROVINCE_CAP": 30,
    "AE_SAME_CULTURE": 0.5,
    "AE_SAME_CULTURE_GROUP": 0.25,
    "AE_INFIDEL_CONQUEST": 0.25,
    "AE_SAME_RELIGION": 0.5,
    "AE_SAME_RELIGION_GROUP": 0.0,
    "AE_DIFFERENT_RELIGION": -0.5,
    "AE_HRE_INTERNAL": 0.5,
    "AE_DISTANCE_BASE": 0.75,
    "AE_SAME_OVERLORD": 0.5,
}
_DEFINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?)", re.MULTILINE)
_POSITION = re.compile(r"^(\d+)=\{\s*position=\{\s*(-?[\d.]+)\s+(-?[\d.]+)", re.MULTILINE)


@dataclass
class AeRules:
    """The rules for the AE of a conquest.

    Attributes:
        defines: Named numbers from ``defines.lua`` (see :data:`DEFAULT_DEFINES`).
        claim_factor: Casus belli factor for taking a province the attacker has no core
            on (a claim, or no casus belli at all).
        core_factor: Casus belli factor for taking back a core.
        prestige_ae_impact: Change of AE per 100 prestige.
        admin_efficiency: Administrative technology level → administrative efficiency
            gained up to and including it.
        positions: Province id → map position of its city.
    """

    defines: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DEFINES))
    claim_factor: float = 1.0
    core_factor: float = 0.25
    prestige_ae_impact: float = -0.1
    admin_efficiency: dict[int, float] = field(default_factory=dict)
    positions: dict[int, tuple[float, float]] = field(default_factory=dict)

    def define(self, name: str) -> float:
        """A number from ``defines.lua``, or its 1.37 value."""
        return self.defines.get(name, DEFAULT_DEFINES[name])

    @classmethod
    def load(cls, game_dir: Path) -> AeRules:
        """Load from the game installation, reusing the on-disk cache when possible."""
        common = game_dir / "common"
        sources = [
            common / "defines.lua",
            common / "wargoal_types",
            common / "static_modifiers",
            common / "technologies",
            game_dir / "map" / "positions.txt",
        ]
        return cached("ae_rules", sources, lambda: cls.parse_game(game_dir))

    @classmethod
    def parse_game(cls, game_dir: Path) -> AeRules:
        """Read every rule from the game installation."""
        common = game_dir / "common"
        rules = cls()
        defines = common / "defines.lua"
        if defines.is_file():
            found = {m.group(1): float(m.group(2)) for m in _DEFINE.finditer(_read(defines))}
            rules.defines.update({k: v for k, v in found.items() if k in DEFAULT_DEFINES})
        for path in _files(common / "wargoal_types"):
            document = parse(_read(path))
            for name, attribute in (("take_claim", "claim_factor"), ("take_core", "core_factor")):
                factor = _badboy_factor(document.get(name))
                if factor is not None:
                    setattr(rules, attribute, factor)
        for path in _files(common / "static_modifiers"):
            block = parse(_read(path)).get("prestige")
            impact = block.get("ae_impact") if isinstance(block, dict) else None
            if isinstance(impact, int | float):
                rules.prestige_ae_impact = float(impact)
        adm = common / "technologies" / "adm.txt"
        if adm.is_file():
            rules.admin_efficiency = admin_efficiency_by_level(_read(adm))
        positions = game_dir / "map" / "positions.txt"
        if positions.is_file():
            rules.positions = parse_positions(_read(positions))
        return rules


def admin_efficiency_by_level(text: str) -> dict[int, float]:
    """Administrative efficiency gained up to each administrative technology level.

    The technology file's blocks are the levels after level 0 (block ``n`` is level
    ``n + 1``, as the technology costs showed in D-029).
    """
    total = 0.0
    result = {0: 0.0}
    for index, block in enumerate(get_all(parse(text), "technology")):
        if isinstance(block, dict):
            value = block.get("administrative_efficiency")
            if isinstance(value, int | float):
                total += float(value)
        result[index + 1] = total
    return result


def parse_positions(text: str) -> dict[int, tuple[float, float]]:
    """Province id → the first position (its city) in ``map/positions.txt``."""
    return {
        int(m.group(1)): (float(m.group(2)), float(m.group(3))) for m in _POSITION.finditer(text)
    }


def _badboy_factor(block: object) -> float | None:
    attacker = block.get("attacker") if isinstance(block, dict) else None
    factor = attacker.get("badboy_factor") if isinstance(attacker, dict) else None
    return float(factor) if isinstance(factor, int | float) else None


def _files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.txt")) if folder.is_dir() else []


def _read(path: Path) -> str:
    return _decode(path.read_bytes())
