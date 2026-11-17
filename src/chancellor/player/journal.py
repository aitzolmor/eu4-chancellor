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
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from chancellor.context.campaign import Campaign, as_list, count_regiments
from chancellor.save.parser import LazyBlock, get_all

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
# Numbers kept for the rivals and great powers too, to compare with them (D-048).
OTHER_NUMBERS = ("development", "regiments", "income", "treasury", "provinces", "manpower")
# Kept in every snapshot, even trimmed ones: the numbers, the player's and the others'.
_ALWAYS_KEPT = ("date", "tag", "numbers", "others", "rivals", "great_powers")
# Changes in these numbers are events of their own; the rest go in one summary line.
_EVENT_NUMBERS = ("adm_tech", "dip_tech", "mil_tech", "great_power_rank")


def journal_path(context_file: Path) -> Path:
    """The journal sits next to the player's context file."""
    return context_file.with_name(FILE_NAME)


def take_snapshot(
    campaign: Campaign, tag: str | None = None, extra: Iterable[str] = ()
) -> dict[str, Any]:
    """A compact record of a country on this save, as plain JSON values.

    ``extra`` are countries tracked in full besides the rivals and great powers: the
    ones the player picked to compare with (D-049).
    """
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
    rivals = sorted(_rivals(country))
    great_powers = _great_powers(campaign)
    others = {}
    for other in dict.fromkeys([*rivals, *extra, *great_powers]):  # rivals first
        if other != tag and campaign.exists(other):
            others[other] = country_numbers(campaign, other)
    # Neighbours and the largest countries too, with fewer numbers, so a country that
    # becomes a rival later already has a history to compare with (D-048).
    neighbours = [str(t) for t in as_list(country.get("neighbours"))]
    largest = sorted(campaign.quick_stats, key=lambda t: -campaign.quick_stats[t][0])
    for other in dict.fromkeys([*neighbours, *largest[:TRACKED_LARGEST]]):
        if other != tag and other not in others and campaign.exists(other):
            figures = country_numbers(campaign, other)
            others[other] = {k: v for k, v in figures.items() if k in COMPARE_KEYS}
    return {
        "date": campaign.date,
        "tag": tag,
        "numbers": {k: v for k, v in numbers.items() if v is not None},
        "provinces": provinces,
        "uncored": sorted(str(p) for p in owned if p not in cores),
        "wars": sorted(str(w.get("name", "?")).strip() for w in campaign.wars_of(tag)),
        "allies": sorted(str(t) for t in as_list(country.get("allies"))),
        "subjects": sorted(str(t) for t in as_list(country.get("subjects"))),
        "rivals": rivals,
        "great_powers": [t for t in great_powers if t != tag],
        "others": others,
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
        years_with_others: set[int] = set()
        for old in snapshots[:-DETAILED]:  # older ones keep their numbers only
            for key in list(old):
                if key not in _ALWAYS_KEPT:
                    del old[key]
            # The other countries' numbers once an in-game year, so monthly autosaves over a
            # whole campaign stay around 2 MB; the charts join the yearly points.
            year = _date(str(old.get("date", "")))[0]
            if year in years_with_others:
                old.pop("others", None)
            elif "others" in old:
                years_with_others.add(year)
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


# Numbers charted and tabled as trends (D-045), in display order.
TREND_KEYS = (
    "treasury",
    "income",
    "expenses",
    "manpower",
    "regiments",
    "development",
    "provinces",
    "prestige",
    "overextension",
    "at_coalition_ae",
)
# The largest countries tracked on every save, besides rivals, great powers, neighbours.
TRACKED_LARGEST = 30
# Numbers charted against the rivals (D-048), and how many countries at most.
COMPARE_KEYS = ("development", "regiments", "income")
COMPARED = 3
# Journal lines worth marking on a chart: the moments the numbers usually move around.
_MARKED = ("War began", "War ended", "New ruler", "Gained", "Lost")
TREND_ROWS = 12


def trend_data(
    snapshots: list[dict[str, Any]],
    date: str,
    campaign: Campaign,
    chosen: list[str] | None = None,
) -> dict[str, Any]:
    """The journal's numbers up to ``date`` as series, and its main events, for charts.

    Returns:
        ``{"dates": [...], "years": [...], "series": {key: [value | None]},
        "labels": {key: label}, "events": [{"date", "year", "text"}]}``.
    """
    known = [s for s in snapshots if _date(str(s.get("date", ""))) <= _date(date)]
    labels = dict((k, label) for k, label, _ in NUMBERS)
    events = []
    for before, after in zip(known, known[1:], strict=False):
        for line in changes(before, after, campaign):
            if line.startswith(_MARKED):
                text = line if len(line) <= 70 else line[:67] + "..."
                events.append({"date": after["date"], "year": _year(after["date"]), "text": text})
    latest = known[-1] if known else {}
    compare: list[str | None] = rival_slots(known)
    basis = "rivals"
    if chosen:  # the countries the player picked (D-049), in the order picked
        compare = list(chosen)[:COMPARED]
        basis = "countries you picked"
    elif not any(compare):  # no rivals: the strongest great powers instead
        compare = list(latest.get("great_powers") or [])[:COMPARED]
        basis = "great powers"
    shown = [tag for tag in compare if tag]
    others = {
        tag: {
            key: [_lineage_value(s, lineage(campaign, tag), key) for s in known]
            for key in COMPARE_KEYS
        }
        for tag in shown
    }
    return {
        "compare": compare,
        "compare_basis": basis,
        "names": {tag: campaign.name(tag) for tag in [campaign.player, *shown]},
        "others": others,
        "dates": [str(s["date"]) for s in known],
        "years": [_year(str(s["date"])) for s in known],
        "series": {key: [s.get("numbers", {}).get(key) for s in known] for key in TREND_KEYS},
        "labels": {key: labels[key] for key in TREND_KEYS},
        "events": events,
    }


def render_trends(data: dict[str, Any], country: str) -> str:
    """Markdown for ``get_trends``: a table of up to :data:`TREND_ROWS` dates."""
    dates = data["dates"]
    lines = [f"# Trends: {country}", ""]
    if len(dates) < 2:
        lines.append(
            "Not enough saves recorded yet for a trend: the journal records each save the "
            "Chancellor reads (and `chancellor journal --backfill` can add older ones)."
        )
        return "\n".join(lines) + "\n"
    rows = _sample(len(dates), TREND_ROWS)
    keys = list(data["series"])
    lines.append(f"{len(dates)} saves recorded, {dates[0]} to {dates[-1]}; {len(rows)} shown.")
    lines += [
        "",
        "| Date | " + " | ".join(data["labels"][k] for k in keys) + " |",
        "| --- |" + " --- |" * len(keys),
    ]
    digits = dict((k, d) for k, _, d in NUMBERS)
    for i in rows:
        cells = ["-" if (v := data["series"][k][i]) is None else _fmt(v, digits[k]) for k in keys]
        lines.append(f"| {dates[i]} | " + " | ".join(cells) + " |")
    if data.get("compare"):
        player = next(iter(data["names"]))
        series: dict[str | None, dict[str, list[float | None]]] = {
            player: {k: data["series"][k] for k in COMPARE_KEYS},
            **data["others"],
        }
        lines += [
            "",
            f"Compared with the {data['compare_basis']}, {dates[0]} → {dates[-1]}:",
            "",
            "| Country | " + " | ".join(data["labels"].get(k, k) for k in COMPARE_KEYS) + " |",
            "| --- |" + " --- |" * len(COMPARE_KEYS),
        ]
        for tag, values in series.items():
            if tag is None:
                continue
            cells = [_span(values[key]) for key in COMPARE_KEYS]
            lines.append(f"| {data['names'].get(tag, tag)} | " + " | ".join(cells) + " |")
    if data["events"]:
        lines += ["", "Main events:", ""]
        lines += [f"- {e['date']}: {e['text']}" for e in data["events"][-12:]]
    lines += [
        "",
        "_From the campaign journal: one record per save the Chancellor read, so the "
        "spacing between dates varies._",
    ]
    return "\n".join(lines) + "\n"


def lineage(campaign: Campaign, tag: str) -> list[str]:
    """A country's tag and the tags it had before forming it (Castile, then Spain).

    The save records them in ``previous_country_tags``; the journal stored the numbers
    under the tag of the day, so a comparison looks them up under each in turn (D-049).
    """
    country = campaign.country(tag) or {}
    previous = [str(t) for t in as_list(country.get("previous_country_tags")) if t]
    return [tag, *reversed(previous)]


def _lineage_value(snapshot: dict[str, Any], tags: list[str], key: str) -> float | None:
    others = snapshot.get("others", {})
    for tag in tags:
        value = others.get(tag, {}).get(key)
        if value is not None:
            return value
    return None


def rival_slots(snapshots: list[dict[str, Any]]) -> list[str | None]:
    """Each rival's colour slot, kept for as long as it stays a rival (D-048).

    Walking the snapshots oldest first, a country that stops being a rival frees its
    slot and a new rival takes the first free one, so changing one rival never repaints
    the others. Returns :data:`COMPARED` slots; an empty one is ``None``.
    """
    slots: list[str | None] = [None] * COMPARED
    for snapshot in snapshots:
        if "rivals" not in snapshot:
            continue
        rivals = list(snapshot["rivals"])
        slots = [tag if tag in rivals else None for tag in slots]
        for rival in rivals:
            if rival not in slots and None in slots:
                slots[slots.index(None)] = rival
    return slots


def _span(values: list[float | None]) -> str:
    """The first and last known value of a series: ``120 → 340``."""
    known = [v for v in values if v is not None]
    if not known:
        return "-"
    return f"{_fmt(known[0], 0)} → {_fmt(known[-1], 0)}"


def _sample(count: int, rows: int) -> list[int]:
    """Up to ``rows`` indexes spread evenly over ``count``, first and last included."""
    if count <= rows:
        return list(range(count))
    return sorted({round(i * (count - 1) / (rows - 1)) for i in range(rows)})


def _year(date: str) -> float:
    parts = _date(date)
    if len(parts) < 3:
        return float(parts[0])
    year, month, day = parts[:3]
    return year + (month - 1) / 12 + (day - 1) / 365


def country_numbers(campaign: Campaign, tag: str) -> dict[str, float]:
    """The few numbers kept for another country (:data:`OTHER_NUMBERS`)."""
    country = campaign.country(tag) or {}
    ledger = country.get("ledger") or {}
    owned = [p for p in as_list(country.get("owned_provinces")) if isinstance(p, int)]
    numbers = {
        "development": _float(country.get("raw_development")),
        "regiments": float(count_regiments(country)),
        "income": _float(ledger.get("lastmonthincome")),
        "treasury": _float(country.get("treasury")),
        "provinces": float(len(owned)),
        "manpower": _float(country.get("manpower")),
    }
    return {k: v for k, v in numbers.items() if v is not None}


def _great_powers(campaign: Campaign) -> list[str]:
    """The great powers by rank (the save's ``great_powers.original``)."""
    block = campaign.gamestate.get("great_powers")
    if isinstance(block, LazyBlock):
        block = block.parse()
    if not isinstance(block, dict):
        return []
    ranked = [
        (int(e.get("rank", 99)), str(e["country"]))
        for e in get_all(block, "original")
        if isinstance(e, dict) and e.get("country")
    ]
    return [tag for _, tag in sorted(ranked)]


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
