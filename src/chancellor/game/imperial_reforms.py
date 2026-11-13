"""Imperial reforms of the Holy Roman Empire from ``common/imperial_reforms`` (D-010).

Each reform names the reform it follows (``required_reform``), the one that rules it out
(``disabled_by``, for the two branches after the Perpetual Diet), its place in the
reform screen (``gui_container``) and the modifiers it grants to the Emperor, to members,
to every country or to provinces. The game ships two sets: one for players with the
*Emperor* DLC (``potential = { has_dlc = "Emperor" }``) and one for players without it.

The save lists the reforms passed (``empire.passed_reform``) and the DLCs enabled
(``meta.dlc_enabled``); :meth:`ImperialReformLibrary.next_reforms` combines both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chancellor.game.cache import cached
from chancellor.game.modifiers import _decode
from chancellor.save.parser import parse

# From common/defines.lua: IMPERIAL_REFORM_COST = 50, the imperial authority a reform
# needs at least (electors must also agree).
IMPERIAL_REFORM_COST = 50
# Blocks of a reform whose stats apply to someone, in display order.
MODIFIER_SCOPES = ("emperor", "member", "all", "province", "emperor_per_prince")


@dataclass(frozen=True)
class ImperialReform:
    """One imperial reform.

    Attributes:
        name: Script key, e.g. ``emperor_reichsregiment``.
        empire: ``hre`` or ``celestial_empire``.
        required: The reform that must be passed first, if any.
        disabled_by: A reform that rules this one out, if any.
        branch: ``mainline``, ``left_branch`` or ``right_branch``.
        dlc: ``True`` if it needs the Emperor DLC, ``False`` if it is only for players
            without it, ``None`` if it does not depend on it.
        modifiers: Stat changes per scope (``emperor``, ``member``, ``province``, ...).
    """

    name: str
    empire: str
    required: str | None = None
    disabled_by: str | None = None
    branch: str = "mainline"
    dlc: bool | None = None
    modifiers: dict[str, list[tuple[str, Any]]] = field(default_factory=dict)


class ImperialReformLibrary:
    """The imperial reforms of the game, in file order."""

    def __init__(self, reforms: list[ImperialReform] | None = None) -> None:
        """Create a library from already parsed reforms."""
        self.reforms = reforms or []
        self._by_name = {r.name: r for r in self.reforms}

    @classmethod
    def load(cls, game_dir: Path) -> ImperialReformLibrary:
        """Load from the game installation, reusing the on-disk cache when possible."""
        folder = game_dir / "common" / "imperial_reforms"
        return cached("imperial_reforms", [folder], lambda: cls.parse_game(game_dir))

    @classmethod
    def parse_game(cls, game_dir: Path) -> ImperialReformLibrary:
        """Parse every file of ``common/imperial_reforms``."""
        folder = game_dir / "common" / "imperial_reforms"
        reforms: list[ImperialReform] = []
        if folder.is_dir():
            for path in sorted(folder.glob("*.txt")):
                reforms += parse_reform_file(_decode(path.read_bytes()))
        return cls(reforms)

    def __len__(self) -> int:
        return len(self.reforms)

    def get(self, name: str) -> ImperialReform | None:
        """The reform with this script key, if it exists."""
        return self._by_name.get(name)

    def next_reforms(self, passed: list[str], has_emperor_dlc: bool) -> list[ImperialReform]:
        """HRE reforms that can be proposed now.

        A reform is next when it belongs to the player's set (with or without the Emperor
        DLC), is not passed, its required reform is passed, and no passed reform rules it
        out. After the Perpetual Diet two branches open, so there can be two.
        """
        done = set(passed)
        result = []
        for reform in self.reforms:
            if reform.empire != "hre" or reform.name in done:
                continue
            if reform.dlc is not None and reform.dlc != has_emperor_dlc:
                continue
            if reform.required and reform.required not in done:
                continue
            if reform.disabled_by and reform.disabled_by in done:
                continue
            if any(r.disabled_by == reform.name for r in self.reforms if r.name in done):
                continue
            result.append(reform)
        return result


def parse_reform_file(text: str) -> list[ImperialReform]:
    """Extract the reforms defined in one file."""
    reforms = []
    for name, block in parse(text).items():
        if not isinstance(block, dict):
            continue
        modifiers = {
            scope: [
                (stat, value)
                for stat, value in block[scope].items()
                if isinstance(value, int | float | bool)
            ]
            for scope in MODIFIER_SCOPES
            if isinstance(block.get(scope), dict)
        }
        reforms.append(
            ImperialReform(
                name=name,
                empire=str(block.get("empire", "")),
                required=_text(block.get("required_reform")),
                disabled_by=_text(block.get("disabled_by")),
                branch=str(block.get("gui_container", "mainline")),
                dlc=_needs_dlc(block.get("potential")),
                modifiers={k: v for k, v in modifiers.items() if v},
            )
        )
    return reforms


def _text(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _needs_dlc(potential: Any) -> bool | None:
    """``potential = { has_dlc = "Emperor" }`` → True; ``NOT = { has_dlc = ... }`` → False."""
    if not isinstance(potential, dict):
        return None
    if potential.get("has_dlc") == "Emperor":
        return True
    negated = potential.get("NOT")
    if isinstance(negated, dict) and negated.get("has_dlc") == "Emperor":
        return False
    return None
