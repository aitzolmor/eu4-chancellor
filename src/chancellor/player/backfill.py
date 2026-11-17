"""Fill the campaign journal from saves read before it existed (D-045).

The journal (D-043) starts with the first save the Chancellor reads, so its charts would
start empty. The saves already on disk hold the history: this module lists them by
``campaign_id`` and records the ones the player picks into the current campaign's
journal.

The player picks because the game cannot tell: one campaign carries several
campaign ids over its life (D-039), and two games of the same country look alike
from their headers. Reading a save takes about three seconds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from chancellor.save.loader import load_save
from chancellor.save.parser import parse


@dataclass
class SaveGroup:
    """Saves sharing a ``campaign_id``.

    Attributes:
        campaign_id: The id.
        tag: The player's country in them.
        saves: ``(date, path)``, oldest first.
    """

    campaign_id: str
    tag: str
    saves: list[tuple[str, Path]] = field(default_factory=list)

    @property
    def first(self) -> str:
        """Date of the oldest save."""
        return self.saves[0][0]

    @property
    def last(self) -> str:
        """Date of the newest save."""
        return self.saves[-1][0]


def save_groups(save_dir: Path, tag: str) -> list[SaveGroup]:
    """The country's saves in the folder, grouped by ``campaign_id``, oldest group first."""
    groups: dict[str, SaveGroup] = {}
    for path in sorted(save_dir.glob("*.eu4")):
        try:
            meta = parse(load_save(path).meta)
        except (OSError, ValueError):
            continue
        if str(meta.get("player")) != tag:
            continue
        campaign_id = str(meta.get("campaign_id") or "")
        group = groups.setdefault(campaign_id, SaveGroup(campaign_id, tag))
        group.saves.append((str(meta.get("date", "")), path))
    for group in groups.values():
        group.saves.sort(key=lambda s: _date(s[0]))
    return sorted(groups.values(), key=lambda g: _date(g.first))


def pick(groups: Iterable[SaveGroup], prefixes: Iterable[str]) -> list[SaveGroup]:
    """The groups whose id starts with one of the prefixes (the first 8 characters do)."""
    wanted = [p.strip().lower() for p in prefixes if p.strip()]
    return [g for g in groups if any(g.campaign_id.lower().startswith(p) for p in wanted)]


def backfill(
    groups: Iterable[SaveGroup],
    record: Callable[[Path], bool],
    progress: Callable[[str], None] = lambda _: None,
) -> int:
    """Record every save of the groups, oldest first.

    Args:
        groups: The groups to read.
        record: Reads one save and records it; returns whether it was new.
        progress: Told about each save as it is read.

    Returns:
        How many saves were recorded.
    """
    saves = sorted((s for g in groups for s in g.saves), key=lambda s: _date(s[0]))
    recorded = 0
    for date, path in saves:
        progress(f"{date} {path.name}")
        if record(path):
            recorded += 1
    return recorded


def render_groups(groups: list[SaveGroup], current: str | None) -> str:
    """The groups, for the player to pick from."""
    lines = []
    for group in groups:
        mark = "  <- the current save" if group.campaign_id == current else ""
        lines.append(
            f"{group.campaign_id[:8]}  {group.first} to {group.last}  "
            f"({len(group.saves)} saves){mark}"
        )
    return "\n".join(lines) + "\n"


def _date(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return (0,)
