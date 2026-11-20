"""The player's casus belli, from what the probe mod wrote to ``game.log`` (D-044, D-051).

The save does not hold casus belli. The probe mod checks every casus belli type, each
month, against the countries worth attacking, for the player and for each subject (whose
casus belli the overlord can use); :mod:`chancellor.live.gamelog` reads those lines. This
module decides whether that check can speak for the loaded save, and words it for the
war check and the expansion targets.

The check is only trusted when the log belongs to the same country as the save and
its date is within a year of the save's: the log starts empty each time the game starts,
and the player may have loaded another campaign since.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chancellor.context.campaign import Campaign
from chancellor.live.gamelog import read_probe

MAX_AGE_DAYS = 366


@dataclass
class CasusBelli:
    """The latest monthly casus belli check of the probe mod.

    Attributes:
        date: The game date of the check.
        checked: Tag → name of every country checked for the player.
        own: Target tag → the player's casus belli types against it.
        by_subject: Subject tag → target tag → the subject's casus belli types.
        subjects: Subject tag → name.
    """

    date: str
    checked: dict[str, str] = field(default_factory=dict)
    own: dict[str, list[str]] = field(default_factory=dict)
    by_subject: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    subjects: dict[str, str] = field(default_factory=dict)

    def against(self, target: str) -> list[tuple[str | None, str]]:
        """``(holder, type)`` for each casus belli against ``target``.

        The holder is ``None`` for the player, otherwise the subject's tag.
        """
        found: list[tuple[str | None, str]] = [(None, cb) for cb in self.own.get(target, [])]
        for subject, targets in self.by_subject.items():
            found += [(subject, cb) for cb in targets.get(target, [])]
        return found

    def covers(self, target: str) -> bool:
        """Whether ``target`` was checked, so an empty answer means "none"."""
        return target in self.checked or any(target in t for t in self.by_subject.values())


@dataclass
class CasusBelliLookup:
    """The check, when it can be used, or why it cannot.

    Attributes:
        data: The check, or ``None``.
        reason: Why there is no usable check (empty when there is one).
    """

    data: CasusBelli | None
    reason: str = ""


def load_casus_belli(campaign: Campaign, log: Path | None) -> CasusBelliLookup:
    """The probe mod's latest casus belli check, if it speaks for this save.

    Args:
        campaign: The loaded save; its player and date are matched against the log.
        log: The game's ``logs/game.log``, or ``None`` when the user folder is unknown.
    """
    off = "Casus belli need the Chancellor probe mod running in the game"
    if log is None or not log.is_file():
        return CasusBelliLookup(None, f"{off} (no game log found).")
    try:
        report = read_probe(log)
    except OSError as exc:
        return CasusBelliLookup(None, f"{off} (the game log could not be read: {exc}).")
    if not report.cb_targets or not report.last_date:
        return CasusBelliLookup(
            None,
            f"{off}: the game log has no casus belli check (the mod is not enabled, or no "
            "month has passed since the game started).",
        )
    country = report.heartbeats[-1][2] if report.heartbeats else ""
    player = campaign.player
    if player and country and country not in (campaign.name(player), player):
        return CasusBelliLookup(
            None, f"The game log's casus belli are {country}'s, not {campaign.name(player)}'s."
        )
    save_date = campaign.date
    age = _days(save_date) - _days(report.last_date) if save_date[:1].isdigit() else 0
    if abs(age) > MAX_AGE_DAYS:
        return CasusBelliLookup(
            None,
            f"The game log's casus belli check is from {report.last_date}, too far from the "
            f"save's date ({save_date}); play a month with the probe mod for a fresh one.",
        )
    return CasusBelliLookup(
        CasusBelli(
            date=report.last_date,
            checked=dict(report.cb_targets),
            own={tag: list(types) for tag, types in report.casus_belli.items()},
            by_subject={s: dict(t) for s, t in report.subject_cb.items()},
            subjects=dict(report.subjects),
        )
    )


def cb_name(campaign: Campaign, cb: str) -> str:
    """A casus belli type's name in the game's language (``cb_conquest`` → Conquista)."""
    name = campaign.loc.get(cb, "")
    return name.rstrip(".").strip() or cb.removeprefix("cb_").replace("_", " ")


def describe_against(campaign: Campaign, data: CasusBelli, target: str) -> str:
    """One line: the casus belli against ``target``, whose, or that there are none."""
    found = data.against(target)
    if found:
        return "; ".join(
            f"{cb_name(campaign, cb)} ({'yours' if who is None else campaign.name(who)})"
            for who, cb in found
        )
    if data.covers(target):
        return "none"
    return (
        "not checked (the mod checks your continent, neighbours, rivals and holders of your "
        "claims or cores; reinstall it with `chancellor probe install` if it is older)"
    )


def short_against(campaign: Campaign, data: CasusBelli, target: str) -> str:
    """A table cell: the distinct casus belli names against ``target``, or "none"."""
    names: list[str] = []
    for who, cb in data.against(target):
        name = cb_name(campaign, cb) + ("" if who is None else f" ({campaign.name(who)})")
        if name not in names:
            names.append(name)
    if names:
        return ", ".join(names)
    return "none" if data.covers(target) else "?"


def _days(date: str) -> int:
    """A rough day count for comparing game dates (``1535.4.22``)."""
    parts = [int(p) for p in date.split(".")[:3] if p.isdigit()] + [1, 1, 1]
    year, month, day = parts[:3]
    return year * 365 + (month - 1) * 30 + day
