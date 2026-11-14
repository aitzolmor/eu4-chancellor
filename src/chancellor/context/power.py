"""Monarch power: what it buys, what it costs and how fast it comes (D-029).

The briefing showed only the points a country holds, so advice on spending them was
guesswork: Claude suggested buying a military technology that was twenty years ahead of
its time. This module applies the game's own rules (:class:`PowerRules`) to the save and
states the costs, with their parts, so the advice can rest on them:

* the next technology in each category: the base cost, its increase over time, the
  penalty for being ahead of its year and for institutions not embraced, the active
  modifiers that change it (events, corruption, innovativeness), and the discounts for
  ideas of that category and for neighbours that already have it. Checked against the
  game's tooltip for Austria in 1483 (677 / 653 / 1194);
* the next idea, a point of stability and a general;
* an estimate of the power gained each month: the base, the ruler, the national focus,
  advisors, power projection, and the upkeep of leaders beyond the free pool;
* the leaders and advisors themselves.

Technology cost modifiers from the bonuses of idea groups, policies, government reforms
and estate privileges are not read yet, so costs are estimates; the game's own tooltip
shows the exact figure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.game.power_rules import CATEGORIES, POWER_PROJECTION_BONUS, PowerRules
from chancellor.save.parser import get_all

_LABELS = {"adm": "Administrative", "dip": "Diplomatic", "mil": "Military"}
# A ruler is recorded under the key of how they came to the throne.
_RULER_KEYS = ("monarch", "monarch_heir", "heir", "foreign_heir", "queen", "monarch_consort")
_MAX_WAIT_MONTHS = 600
_LEADER_TYPES = {
    "general": "General",
    "admiral": "Admiral",
    "conquistador": "Conquistador",
    "explorer": "Explorer",
}


@dataclass
class TechCost:
    """The next technology of one category and what it costs.

    Attributes:
        category: ``adm``, ``dip`` or ``mil``.
        level: The level it would reach.
        year: The year that level belongs to.
        cost: Estimated cost in monarch points today.
        parts: The modifiers applied to the base, as ``(description, share)``.
        base: The base cost before modifiers.
        ahead_per_year: The share added for each year the level is ahead of its time.
        months_ahead: Months until the level's year begins (0 when it has begun).
        today: The save's year and month, to count whole years ahead later on.
    """

    category: str
    level: int
    year: int
    cost: int
    parts: list[tuple[str, float]] = field(default_factory=list)
    base: float = 600.0
    ahead_per_year: float = 0.0
    months_ahead: int = 0
    today: tuple[int, int] = (0, 1)

    def cost_after(self, months: int) -> float:
        """The cost after ``months`` more months: the ahead-of-time penalty shrinks.

        The game counts whole years between the level's year and the current one.
        """
        if not self.months_ahead:
            return float(self.cost)
        others = sum(share for text, share in self.parts if "ahead of its time" not in text)
        year, month = self.today
        later = year + (month - 1 + months) // 12
        years = max(self.year - later, 0)
        return self.base * max(1 + others + years * self.ahead_per_year, 0.1)


@dataclass
class Person:
    """A leader or an advisor of the country."""

    name: str
    kind: str
    detail: str


@dataclass
class PowerReport:
    """Monarch power of one country.

    Attributes:
        points: Points held per category.
        monthly: Estimated monthly gain per category.
        monthly_parts: Where the monthly gain comes from, per category.
        techs: The next technology per category (absent at the last level).
        idea_cost: Base cost of the next idea (administrative, diplomatic or military,
            depending on the idea group).
        ideas_taken: Ideas taken in idea groups (national ideas not counted).
        stability_cost: Administrative cost of one point of stability.
        general_cost: Military cost of recruiting a general.
        leaders: The country's leaders.
        free_leaders: Leaders kept without upkeep, at least: the land force limit and some
            ideas add more, and they are not read.
        leader_upkeep: Monthly military points paid for leaders beyond that pool.
        advisors: The country's advisors.
        stability: Current stability.
    """

    points: dict[str, int]
    monthly: dict[str, float]
    monthly_parts: dict[str, list[tuple[str, float]]]
    techs: dict[str, TechCost]
    idea_cost: int
    ideas_taken: int
    stability_cost: int
    general_cost: int
    leaders: list[Person]
    free_leaders: int
    leader_upkeep: float
    advisors: list[Person]
    stability: float


def power_report(campaign: Campaign, rules: PowerRules, tag: str | None = None) -> PowerReport:
    """Work out a country's monarch power: holdings, costs and monthly gain.

    Args:
        campaign: The loaded save.
        rules: Cost rules from the game files.
        tag: The country; the player's by default.

    Raises:
        KeyError: If the country is not in the save.
    """
    tag = tag or campaign.player
    country = campaign.country(tag)
    if country is None:
        raise KeyError(f"Country {tag} is not in the save")
    powers = [int(v) for v in as_list(country.get("powers")) if isinstance(v, int | float)]
    points = dict(zip(CATEGORIES, powers + [0, 0, 0], strict=False))

    ideas = dict(country.get("active_idea_groups") or {})
    national = next(iter(ideas), None)  # the save lists the national ideas first
    ideas_taken = sum(int(v) for k, v in ideas.items() if k != national and isinstance(v, int))
    ideas_by_category: dict[str, int] = {}
    for group, count in ideas.items():
        category = rules.idea_categories.get(group)
        if group != national and category and isinstance(count, int):
            ideas_by_category[category] = ideas_by_category.get(category, 0) + count

    leaders = _leaders(country)
    advisors, advisor_power = _advisors(campaign, country, rules)
    emperor = campaign.emperor == tag
    projection = float(country.get("current_power_projection") or 0.0)
    free = rules.base_free_leaders + (rules.emperor_free_leaders if emperor else 0)
    if projection >= 25:
        free += rules.power_projection_free_leaders
    upkeep = max(len(leaders) - free, 0) * rules.define("LEADER_MAINTENANCE_COST")
    monthly_parts = _monthly(campaign, country, rules, advisor_power, upkeep)

    techs = {}
    for category in CATEGORIES:
        cost = _tech_cost(campaign, country, rules, category, ideas_by_category.get(category, 0))
        if cost is not None:
            techs[category] = cost

    return PowerReport(
        points=points,
        monthly={c: sum(v for _, v in parts) for c, parts in monthly_parts.items()},
        monthly_parts=monthly_parts,
        techs=techs,
        idea_cost=round(rules.define("PS_BUY_IDEA")),
        ideas_taken=ideas_taken,
        stability_cost=round(rules.define("PS_BOOST_STABILITY")),
        general_cost=round(rules.define("PS_BUY_GENERAL")),
        leaders=leaders,
        free_leaders=free,
        leader_upkeep=upkeep,
        advisors=advisors,
        stability=float(country.get("stability") or 0.0),
    )


def render_power(report: PowerReport) -> str:
    """The Markdown section for the briefing."""
    lines = [
        "## Monarch power: what it buys",
        "",
        "| | " + " | ".join(_LABELS[c] for c in CATEGORIES) + " |",
        "| --- | --- | --- | --- |",
        "| Points | " + " | ".join(str(report.points[c]) for c in CATEGORIES) + " |",
        "| Monthly gain (est.) | "
        + " | ".join(f"{report.monthly[c]:+.0f}" for c in CATEGORIES)
        + " |",
        "| Next technology | " + " | ".join(_tech_cell(report, c) for c in CATEGORIES) + " |",
        "| Can buy it in | " + " | ".join(_wait_cell(report, c) for c in CATEGORIES) + " |",
        "",
    ]
    for category in CATEGORIES:
        tech = report.techs.get(category)
        if tech:
            parts = ", ".join(f"{text} {share:+.1%}" for text, share in tech.parts) or "none"
            lines.append(
                f"- {_LABELS[category]} technology {tech.level} (year {tech.year}): "
                f"~{tech.cost} points. Base cost {_base(report, tech)} with {parts}."
            )
    for category in CATEGORIES:
        parts = ", ".join(f"{text} {value:+g}" for text, value in report.monthly_parts[category])
        lines.append(f"- {_LABELS[category]} points a month: {parts}.")
    can_raise = report.stability < 3
    lines += [
        f"- Next idea: {report.idea_cost} points of its group's category "
        f"({report.ideas_taken} ideas taken in idea groups).",
        f"- One point of stability: {report.stability_cost} administrative points"
        + ("" if can_raise else " (stability is already at its maximum of +3)")
        + ".",
        f"- A new general: {report.general_cost} military points. " + _leader_note(report),
    ]
    if report.leaders:
        lines.append(
            "- Leaders: "
            + "; ".join(f"{p.name} ({p.kind}, {p.detail})" for p in report.leaders)
            + "."
        )
    if report.advisors:
        lines.append(
            "- Advisors: "
            + "; ".join(f"{p.name} ({p.kind}, {p.detail})" for p in report.advisors)
            + "."
        )
    affordable = _affordable(report)
    lines.append(
        "- Can be bought now: "
        + (", ".join(affordable) if affordable else "nothing listed above")
        + "."
    )
    lines += [
        "",
        "_Costs follow the game's rules (checked against its tooltip); technology cost "
        "changes from idea group bonuses, policies, government reforms and estate privileges "
        'are not counted yet. "Can buy it in" saves every point for that technology and '
        "lets its ahead-of-time penalty shrink as its year approaches, so it can be sooner "
        "than the game's own estimate, which keeps today's cost._",
    ]
    return "\n".join(lines)


# --- technology -------------------------------------------------------------------------


def _tech_cost(
    campaign: Campaign, country: dict[str, Any], rules: PowerRules, category: str, ideas: int
) -> TechCost | None:
    levels = rules.techs.get(category) or []
    current = int((country.get("technology") or {}).get(f"{category}_tech", 0) or 0)
    # The file's blocks are the levels to buy: the one after level N is block N (checked
    # against the game: Austria at administrative 6 in 1483 buys level 7, year 1479).
    if current >= len(levels):
        return None
    tech = levels[current]
    parts: list[tuple[str, float]] = []
    year, month = _year_month(campaign.date)
    ahead = rules.define("TECH_AHEAD_OF_TIME")
    years_ahead = max(tech.year - year, 0)  # whole years, as the game counts them
    span = rules.end_year - rules.start_year
    if span > 0 and tech.year > rules.start_year:
        share = rules.define("TECH_TIME_COST") * (tech.year - rules.start_year) / span
        parts.append(("increase over time", round(share, 3)))
    if years_ahead:
        parts.append((f"{years_ahead} years ahead of its time", years_ahead * ahead))
    embraced = [
        name
        for name, flag in zip(
            rules.institutions, as_list(country.get("institutions")), strict=False
        )
        if flag == 1
    ]
    for name, share in tech.institutions.items():
        if name not in embraced and share:
            parts.append((f"{campaign.text(name)} not embraced", share))
    if ideas:
        parts.append(
            (f"{ideas} {_LABELS[category].lower()} ideas", ideas * rules.define("IDEA_TO_TECH"))
        )
    parts += _active_modifiers(campaign, country, rules, category)
    neighbours = [
        t
        for t in as_list(country.get("neighbours"))
        if isinstance(t, str) and _tech_level(campaign, t, category) > current
    ]
    if neighbours:
        # One bonus, however many neighbours have it: the game showed -5% for Austria with
        # eleven neighbours ahead in one category and five in another.
        parts.append(("a neighbour already has it", rules.define("NEIGHBOURBONUS")))
    base = rules.define("PS_ADVANCE_TECH")
    factor = max(1 + sum(share for _, share in parts), 0.1)
    return TechCost(
        category,
        current + 1,
        tech.year,
        round(base * factor),
        parts,
        base=base,
        ahead_per_year=ahead,
        months_ahead=max((tech.year - year) * 12 - (month - 1), 0) if years_ahead else 0,
        today=(year, month),
    )


def _active_modifiers(
    campaign: Campaign, country: dict[str, Any], rules: PowerRules, category: str
) -> list[tuple[str, float]]:
    """Technology cost changes from active modifiers, corruption and innovativeness."""
    parts = []
    stats = ("technology_cost", f"{category}_tech_cost_modifier", "all_power_cost")
    for entry in get_all(country, "modifier"):
        name = entry.get("modifier") if isinstance(entry, dict) else None
        found = rules.tech_cost_modifiers.get(str(name)) if name else None
        if found:
            share = sum(found.get(stat, 0.0) for stat in stats)
            if share:
                parts.append((campaign.text(str(name)), share))
    # The game keeps these to a thousandth, cutting off the rest (the tooltip showed
    # +0.3% for 0.395 corruption and -0.1% for 1.71 innovativeness).
    corruption = float(country.get("corruption") or 0.0)
    share = _thousandths(corruption * rules.corruption_power_cost / 100)
    if share:
        parts.append(("corruption", share))
    innovativeness = float(country.get("innovativeness") or 0.0)
    share = _thousandths(innovativeness * rules.innovativeness_power_cost / 100)
    if share:
        parts.append(("innovativeness", share))
    return parts


def _thousandths(value: float) -> float:
    """Cut a share to whole thousandths, towards zero."""
    return math.trunc(value * 1000) / 1000


def _tech_level(campaign: Campaign, tag: str, category: str) -> int:
    country = campaign.country(tag) or {}
    value = (country.get("technology") or {}).get(f"{category}_tech", 0)
    return int(value) if isinstance(value, int | float) else 0


# --- monthly gain ------------------------------------------------------------------------


def _monthly(
    campaign: Campaign,
    country: dict[str, Any],
    rules: PowerRules,
    advisor_power: dict[str, float],
    upkeep: float,
) -> dict[str, list[tuple[str, float]]]:
    ruler = _person(country, country.get("monarch"), _RULER_KEYS) or {}
    focus = str(country.get("national_focus") or "").lower()
    parts: dict[str, list[tuple[str, float]]] = {}
    for category, stat in zip(CATEGORIES, ("ADM", "DIP", "MIL"), strict=True):
        items = [("base", rules.define("BASE_POWER_INCREASE"))]
        skill = ruler.get(stat)
        if isinstance(skill, int | float):
            items.append(("ruler", float(skill)))
        if focus in CATEGORIES:
            change = (
                rules.define("NAT_FOCUS_INCREASE")
                if focus == category
                else rules.define("NAT_FOCUS_DECREASE")
            )
            items.append(("national focus", change))
        if advisor_power.get(category):
            items.append(("advisors", advisor_power[category]))
        threshold, bonus = POWER_PROJECTION_BONUS
        if float(country.get("current_power_projection") or 0.0) >= threshold:
            items.append((f"power projection {threshold:g}+", bonus))
        if category == "mil" and upkeep:
            items.append(("leader upkeep", -upkeep))
        parts[category] = items
    return parts


# --- people ---------------------------------------------------------------------------------


def _leaders(country: dict[str, Any]) -> list[Person]:
    wanted = {_id(ref) for ref in as_list(country.get("leader"))} - {None}
    people = []
    for record in _history_records(country, "leader", wanted):
        pips = "/".join(str(record.get(k, 0)) for k in ("fire", "shock", "maneuver", "siege"))
        personality = record.get("personality")
        detail = f"fire/shock/maneuver/siege {pips}"
        if isinstance(personality, str):
            detail += f", {personality.replace('_personality', '').replace('_', ' ')}"
        kind = _LEADER_TYPES.get(str(record.get("type")), str(record.get("type", "?")))
        people.append(Person(str(record.get("name", "?")), kind, detail))
    return people


def _advisors(
    campaign: Campaign, country: dict[str, Any], rules: PowerRules
) -> tuple[list[Person], dict[str, float]]:
    """The country's advisors and the power they add each month.

    Advisors are recorded in the history of the province they were hired in, so the
    country's provinces are searched, capital first, until each one is found.
    """
    wanted = {_id(ref) for ref in as_list(country.get("advisor"))} - {None}
    records: dict[Any, dict[str, Any]] = {}
    for province_id in [country.get("capital"), *as_list(country.get("owned_provinces"))]:
        if not wanted - set(records):
            break
        if isinstance(province_id, int):
            province = campaign.province(province_id) or {}
            for record in _history_records(province, "advisor", wanted):
                records[_id(record.get("id"))] = record
    people = []
    power: dict[str, float] = {}
    for record in records.values():
        kind = str(record.get("type", "?"))
        skill = record.get("skill")
        category = rules.advisor_categories.get(kind)
        if category and isinstance(skill, int | float):
            power[category] = power.get(category, 0.0) + float(skill)
        detail = f"skill {skill}" + (f", +{skill} {category} a month" if category else "")
        people.append(Person(str(record.get("name", "?")), kind.replace("_", " "), detail))
    return people, power


def _history_records(holder: dict[str, Any], key: str, wanted: set[Any]) -> list[dict[str, Any]]:
    """The latest history record of each wanted id under ``key`` (country or province)."""
    found: dict[Any, dict[str, Any]] = {}
    history = holder.get("history") or {}
    for date in history:
        for event in get_all(history, date):
            if not isinstance(event, dict):
                continue
            for record in get_all(event, key):
                if isinstance(record, dict) and _id(record.get("id")) in wanted:
                    found[_id(record.get("id"))] = record
    return list(found.values())


def _person(country: dict[str, Any], ref: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    wanted = {_id(ref)} - {None}
    for key in keys:
        records = _history_records(country, key, wanted)
        if records:
            return records[-1]
    return None


def _id(ref: Any) -> Any:
    return ref.get("id") if isinstance(ref, dict) else None


# --- rendering helpers ------------------------------------------------------------------------


def _base(report: PowerReport, tech: TechCost) -> int:
    factor = 1 + sum(share for _, share in tech.parts)
    return round(tech.cost / factor) if factor > 0.1 else tech.cost


def _tech_cell(report: PowerReport, category: str) -> str:
    tech = report.techs.get(category)
    return f"{tech.level}: ~{tech.cost}" if tech else "none left"


def months_until_affordable(report: PowerReport, category: str) -> int | None:
    """Months until the next technology can be bought, saving every point for it.

    Points come in at the estimated monthly gain while the cost falls as the level's year
    approaches. ``0`` means now; ``None`` means not within fifty years at this rate.
    """
    tech = report.techs.get(category)
    if tech is None:
        return None
    points = float(report.points[category])
    gain = report.monthly[category]
    for month in range(_MAX_WAIT_MONTHS + 1):
        if points + gain * month >= tech.cost_after(month):
            return month
    return None


def _wait_cell(report: PowerReport, category: str) -> str:
    if category not in report.techs:
        return "-"
    months = months_until_affordable(report, category)
    if months is None:
        return "not within 50 years"
    return "now" if months == 0 else f"~{months} months"


def _leader_note(report: PowerReport) -> str:
    count = len(report.leaders)
    plural = "s" if count != 1 else ""
    note = (
        f"The country has {count} leader{plural}; at least {report.free_leaders} are free "
        "(the land force limit and some ideas add more; the game's leader screen shows the "
        "pool)"
    )
    if report.leader_upkeep:
        return note + f". The rest may cost up to {report.leader_upkeep:g} military points a month."
    return note + ", so the leaders cost no upkeep now."


def _affordable(report: PowerReport) -> list[str]:
    items = []
    for category in CATEGORIES:
        tech = report.techs.get(category)
        if tech and tech.cost <= report.points[category]:
            items.append(f"{_LABELS[category].lower()} technology {tech.level}")
    if report.stability < 3 and report.stability_cost <= report.points["adm"]:
        items.append("a point of stability")
    if report.general_cost <= report.points["mil"]:
        upkeep = (
            " (it may cost upkeep: the known free pool is full)"
            if len(report.leaders) >= report.free_leaders
            else ""
        )
        items.append(f"a general{upkeep}")
    for category in CATEGORIES:
        if report.idea_cost <= report.points[category]:
            items.append(f"an idea in a {_LABELS[category].lower()} group")
    return items


def _year_month(date: str) -> tuple[int, int]:
    try:
        year, month, *_ = (int(part) for part in date.split("."))
    except ValueError:
        return 0, 1
    return year, month
