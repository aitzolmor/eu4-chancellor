"""Decisions from the game's ``decisions/`` folder, including formable nations (D-010).

Each file holds ``country_decisions = { <name> = { ... } }`` blocks. A decision has a
``potential`` (who sees it), an ``allow`` (what is needed to take it) and an ``effect``.
Formable nations are decisions whose effect contains ``change_tag``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chancellor.save.parser import get_all, parse


@dataclass
class Decision:
    """One decision.

    Attributes:
        name: Decision key, e.g. ``german_nation``.
        major: Whether the game lists it as a major decision.
        potential: Conditions to see the decision.
        allow: Conditions to take it.
        effect: What it does.
        forms: The tag it forms, for formable nations.
    """

    name: str
    major: bool
    potential: dict[str, Any] = field(default_factory=dict)
    allow: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] = field(default_factory=dict)
    forms: str | None = None


class DecisionLibrary:
    """Every decision defined in the game installation."""

    def __init__(self, decisions: list[Decision] | None = None) -> None:
        """Create a library from already parsed decisions."""
        self.decisions = decisions or []
        self._by_name = {d.name: d for d in self.decisions}

    @classmethod
    def load(cls, game_dir: Path) -> DecisionLibrary:
        """Parse every file in ``<game_dir>/decisions``."""
        decisions: list[Decision] = []
        folder = game_dir / "decisions"
        if folder.is_dir():
            for path in sorted(folder.glob("*.txt")):
                decisions += parse_decision_file(_decode(path.read_bytes()))
        return cls(decisions)

    def __len__(self) -> int:
        return len(self.decisions)

    def get(self, name: str) -> Decision | None:
        """A decision by name."""
        return self._by_name.get(name)


def parse_decision_file(text: str) -> list[Decision]:
    """Parse the content of one decisions file."""
    document = parse(text)
    result = []
    for group in get_all(document, "country_decisions"):
        if not isinstance(group, dict):
            continue
        for name, block in group.items():
            if isinstance(block, dict):
                result.append(_decision(name, block))
    return result


def _decision(name: str, block: dict[str, Any]) -> Decision:
    def section(key: str) -> dict[str, Any]:
        value = block.get(key)
        return value if isinstance(value, dict) else {}

    effect = section("effect")
    return Decision(
        name=name,
        major=block.get("major") is True,
        potential=section("potential"),
        allow=section("allow"),
        effect=effect,
        forms=_changed_tag(effect),
    )


def _changed_tag(effect: Any) -> str | None:
    """Find ``change_tag = XXX`` anywhere in an effect."""
    if isinstance(effect, dict):
        for key, value in effect.items():
            if key == "change_tag" and isinstance(value, str) and len(value) == 3:
                return value
            found = _changed_tag(value)
            if found:
                return found
    elif isinstance(effect, list):
        for value in effect:
            found = _changed_tag(value)
            if found:
                return found
    return None


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
