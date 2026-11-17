"""The campaign journal: what changed between the player's saves (D-043).

Every tool reads one save, a snapshot in time, so nothing knew that a war started two
saves ago or a province was lost. Each time a new save is read, a small record of the
player's country is kept (:func:`take_snapshot`: key numbers, provinces and cores, wars,
allies, subjects, rivals, truces, the coalition, ruler and heir, ideas, technology, the
Emperor and passed imperial reforms). Comparing a save's record with the previous one
gives the journal: "gained Treviso; war with Gelre began; Castile left the alliance".

Records are kept per campaign (the player's context recognises the campaign, D-039) in
``journal.json`` next to the context file. All of them keep their numbers, which are the
base for trends across saves (Phase 5); only the latest :data:`DETAILED` keep the lists
the events are read from.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chancellor.context.campaign import Campaign, as_list, count_regiments
from chancellor.save.parser import get_all

FILE_NAME = "journal.json"
DETAILED = 24  # snapshots that keep their lists; older ones keep only the numbers
COALITION_AE = 50.0

# Key numbers: (snapshot key, label, decimals).
NUMBERS: tuple[tuple[str, str, int], ...] = (
    ("treasury", "treasury", 0),
    ("income", "monthly income", 1),
    ("expenses", "monthly expenses", 1),
    ("loans", "loans", 0),
    ("manpower", "manpower (thousands)", 1),
    ("regiments", "regiments", 0),
    ("development", "development", 0),
    ("provinces", "provinces", 0),
    ("stability", "stability", 0),
    ("prestige", "prestige", 0),
    ("war_exhaustion", "war exhaustion", 1),
    ("overextension", "overextension %", 0),
    ("adm_tech", "administrative technology", 0),
    ("dip_tech", "diplomatic technology", 0),
    ("mil_tech", "military technology", 0),
    ("great_power_rank", "great power rank", 0),
    ("at_coalition_ae", "countries at 50+ AE", 0),
)
# Changes in these numbers are events of their own; the rest go in one summary line.
_EVENT_NUMBERS = ("adm_tech", "dip_tech", "mil_tech", "great_power_rank")


def journal_path(context_file: Path) -> Path:
    """The journal sits next to the player's context file."""
    return context_file.with_name(FILE_NAME)


def take_snapshot(campaign: Campaign, tag: str | None = None) -> dict[str, Any]:
    """A compact record of a country on this save, as plain JSON values."""
    from chancellor.context.summarizer import _find_person, _rivals  # one source for both

    tag = tag or campaign.player
    country = campaign.country(tag) or {}
    ledger = country.get("ledger") or {}
    technology = country.get("technology") or {}
    owned = [p for p in as_list(country.get("owned_provinces")) if isinstance(p, int)]
    cores = {p for p in as_list(country.get("core_provinces")) if isinstance(p, int)}
    provinces = {}
    for province in owned:
        data = campaign.province(province) or {}
        provinces[str(province)] = str(data.get("name") or campaign.loc.province(province))
    grievances = campaign.aggressive_expansion_towards(tag)
    ruler = _find_person(country, country.get("monarch"))
    heir = _find_person(country, country.get("heir"))
    numbers = {
        "treasury": _float(country.get("treasury")),
        "income": _float(ledger.get("lastmonthincome")),
        "expenses": _float(ledger.get("lastmonthexpense")),
        "loans": float(sum(1 for loan in get_all(country, "loan") if isinstance(loan, dict))),
        "manpower": _float(country.get("manpower")),
        "regiments": float(count_regiments(country)),
        "development": _float(country.get("raw_development")),
        "provinces": float(len(owned)),
        "stability": _float(country.get("stability")),
        "prestige": _float(country.get("prestige")),
        "war_exhaustion": _float(country.get("war_exhaustion")),
        "overextension": 100 * (_float(country.get("overextension_percentage")) or 0.0),
        "adm_tech": _float(technology.get("adm_tech")),
        "dip_tech": _float(technology.get("dip_tech")),
        "mil_tech": _float(technology.get("mil_tech")),
        "great_power_rank": _great_power_rank(campaign, tag),
        "at_coalition_ae": float(sum(1 for g in grievances if g.value >= COALITION_AE)),
    }
    groups = country.get("active_idea_groups")
    return {
        "date": campaign.date,
        "tag": tag,
        "numbers": {k: v for k, v in numbers.items() if v is not None},
        "provinces": provinces,
        "uncored": sorted(str(p) for p in owned if p not in cores),
        "wars": sorted(str(w.get("name", "?")).strip() for w in campaign.wars_of(tag)),
        "allies": sorted(str(t) for t in as_list(country.get("allies"))),
        "subjects": sorted(str(t) for t in as_list(country.get("subjects"))),
        "rivals": sorted(_rivals(country)),
        "truces": sorted(t.other for t in campaign.truces(tag)),
        "coalition": sorted(
            {str(t) for v in get_all(country, "coalition_against_us") for t in as_list(v)}
        ),
        "ruler": _person(ruler),
        "heir": _person(heir),
        "ideas": {
            str(g): int(n)
            for g, n in (groups.items() if isinstance(groups, dict) else [])
            if isinstance(n, int)
        },
        "emperor": campaign.emperor or "",
        "imperial_reforms": sorted(str(r) for r in as_list(campaign.empire.get("passed_reform"))),
    }


def changes(before: dict[str, Any], after: dict[str, Any], campaign: Campaign) -> list[str]:
    """What happened between two snapshots of the same country, as short lines."""
    name = campaign.name
    events: list[str] = []
    if "provinces" in before and "provinces" in after:
        gained = [after["provinces"][p] for p in after["provinces"] if p not in before["provinces"]]
        lost = [before["provinces"][p] for p in before["provinces"] if p not in after["provinces"]]
        if gained:
            events.append("Gained " + _listed(gained))
        if lost:
            events.append("Lost " + _listed(lost))
        cored = [
            after["provinces"][p]
            for p in before.get("uncored", [])
            if p in after["provinces"] and p not in after.get("uncored", [])
        ]
        if cored:
            events.append("Cored " + _listed(cored))
    for key, began, ended, label in (
        ("wars", "War began", "War ended", None),
        ("allies", "New ally", "Alliance ended with", name),
        ("subjects", "New subject", "No longer a subject", name),
        ("rivals", "New rival", "No longer a rival", name),
        ("truces", "Truce began with", "Truce ended with", name),
        ("coalition", "Joined the coalition against you", "Left the coalition against you", name),
    ):
        if key not in before or key not in after:
            continue
        added = [x for x in after[key] if x not in before[key]]
        removed = [x for x in before[key] if x not in after[key]]
        show = label or (lambda x: x)
        if added:
            events.append(f"{began}: {_listed([show(x) for x in added])}")
        if removed:
            events.append(f"{ended}: {_listed([show(x) for x in removed])}")
    if before.get("ruler") and after.get("ruler") and before["ruler"] != after["ruler"]:
        events.append(f"New ruler: {after['ruler']} (after {before['ruler']})")
    if "heir" in before and "heir" in after and before["heir"] != after["heir"]:
        if (
            after["heir"]
            and after["heir"] != before.get("ruler")
            and after["heir"] != after.get("ruler")
        ):
            events.append(f"New heir: {after['heir']}")
        elif not after["heir"]:
            events.append("No heir any more")
    for group, taken in after.get("ideas", {}).items():
        was = before.get("ideas", {}).get(group)
        if was is None and "ideas" in before:
            events.append(f"New idea group: {campaign.text(group)}")
        elif was is not None and taken > was:
            events.append(f"{campaign.text(group)}: {was} → {taken} ideas")
    if before.get("emperor") and after.get("emperor") and before["emperor"] != after["emperor"]:
        events.append(f"New Emperor: {name(after['emperor'])}")
    passed = [
        r for r in after.get("imperial_reforms", []) if r not in before.get("imperial_reforms", [])
    ]
    if passed and "imperial_reforms" in before:
        events.append(
            "Imperial reform passed: " + _listed([campaign.text(f"{r}_title") for r in passed])
        )
    old, new = before.get("numbers", {}), after.get("numbers", {})
    for key in _EVENT_NUMBERS:
        if key in old and key in new and old[key] != new[key]:
            label = dict((k, lbl) for k, lbl, _ in NUMBERS)[key]
            events.append(f"{label.capitalize()}: {_fmt(old[key], 0)} → {_fmt(new[key], 0)}")
    moved = [
        f"{label} {_fmt(old[key], digits)} → {_fmt(new[key], digits)}"
        for key, label, digits in NUMBERS
        if key not in _EVENT_NUMBERS
        and key in old
        and key in new
        and _fmt(old[key], digits) != _fmt(new[key], digits)
    ]
    if moved:
        events.append("Numbers: " + "; ".join(moved))
    return events


class JournalStore:
    """Snapshots per campaign, in ``journal.json``. A missing or broken file is empty."""

    def __init__(self, path: Path) -> None:
        """Use the file at ``path`` (created on the first write)."""
        self.path = path

    def snapshots(self, campaign_key: str) -> list[dict[str, Any]]:
        """A campaign's snapshots, oldest first."""
        return self._load().get(campaign_key, [])

    def record(self, campaign_key: str, snapshot: dict[str, Any]) -> bool:
        """Keep a snapshot; one per in-game date (a newer read replaces it).

        Returns:
            Whether anything changed on disk.
        """
        data = self._load()
        snapshots = [s for s in data.get(campaign_key, []) if s.get("date") != snapshot["date"]]
        if snapshot in data.get(campaign_key, []):
            return False
        snapshots.append(snapshot)
        snapshots.sort(key=lambda s: _date(str(s.get("date", ""))))
        for old in snapshots[:-DETAILED]:  # older ones keep their numbers only
            for key in list(old):
                if key not in ("date", "tag", "numbers"):
                    del old[key]
        data[campaign_key] = snapshots
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)
        return True

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}


def journal_entries(
    snapshots: list[dict[str, Any]], date: str, campaign: Campaign, saves: int
) -> list[tuple[str, str, list[str]]]:
    """``(from, to, changes)`` for up to ``saves`` steps ending at this save, newest first.

    Snapshots after this save's date are ignored, so reloading an older save shows the
    history up to it.
    """
    known = [s for s in snapshots if _date(str(s.get("date", ""))) <= _date(date)]
    entries = []
    for before, after in reversed(list(zip(known, known[1:], strict=False))):
        entries.append((before["date"], after["date"], changes(before, after, campaign)))
        if len(entries) >= saves:
            break
    return entries


def render_journal(entries: list[tuple[str, str, list[str]]], country: str, recorded: int) -> str:
    """Markdown for ``get_campaign_journal``."""
    lines = [f"# Campaign journal: {country}", ""]
    if not entries:
        lines.append(
            f"Only {recorded} save recorded for this campaign so far: the journal compares "
            "each save with the previous one the Chancellor read, so it starts with the next."
            if recorded
            else "No save recorded for this campaign yet."
        )
    for start, end, events in entries:
        lines += ["", f"## {start} → {end}", ""]
        lines += [f"- {e}" for e in events] if events else ["- Nothing notable changed."]
    lines += [
        "",
        "_Built from the saves the Chancellor has read (when the panel or a chat read a new "
        "save), so steps can span several in-game months. Numbers are the player's country._",
    ]
    return "\n".join(lines) + "\n"


def _person(person: dict[str, Any] | None) -> str:
    if not person:
        return ""
    return f"{person.get('name', '?')} {person.get('dynasty', '')}".strip()


def _great_power_rank(campaign: Campaign, tag: str) -> float | None:
    from chancellor.context.status import _great_power_rank as rank

    value = rank(campaign, tag)
    return float(value) if value else None


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _fmt(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}"


def _listed(items: list[str], limit: int = 8) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _date(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return (0,)
