"""Watches: the player's "tell me when ..." turned into conditions checked on each save (D-041).

A watch is the player's own words plus one or more conditions the model builds from a
closed list of metrics (:data:`METRICS`), all read from the save: "tell me when France is
weak enough to attack" becomes *war odds against France >= 1.5* and *France at war is
true*. When every condition holds on a save, the watch fires once and keeps the in-game
date it fired. Watches are stored with the player's context, per campaign
(:mod:`chancellor.player.context`).

Every metric is something the other tools already compute, so a fired watch can be
checked against a briefing or a war check.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list, count_regiments

COALITION_AE = 50.0
WAR_ODDS_UNDEFENDED = 99.0  # war odds against a country with no regiments on its side
OPS = (">=", "<=", "is")


@dataclass(frozen=True)
class Metric:
    """One thing a watch can look at.

    Attributes:
        description: What it measures, for the tool description.
        kind: ``number`` (compared with >= or <=) or ``bool`` (compared with ``is``).
        other: Whether it relates the country to a second one (``other``, by default
            the player).
        read: ``(campaign, country, other) -> value``, or ``None`` when unknown.
    """

    description: str
    kind: str
    other: bool
    read: Callable[[Campaign, str, str], float | bool | None]


@dataclass
class Condition:
    """One condition of a watch.

    Attributes:
        metric: A key of :data:`METRICS`.
        op: ``>=``, ``<=`` or ``is``.
        value: The threshold, or ``True`` / ``False`` for ``is``.
        country: The country it looks at (a tag); the player when empty.
        other: The second country, for metrics that relate two; the player when empty.
    """

    metric: str
    op: str
    value: float | bool
    country: str = ""
    other: str = ""


@dataclass
class Watch:
    """A watch, as stored.

    Attributes:
        id: Number, unique among the player's entries and watches.
        description: What the player asked for, in their words.
        conditions: All must hold for the watch to fire.
        game_date: In-game date it was set.
        written: Real date it was set.
        fired: In-game date it fired, or empty while it waits.
    """

    id: int
    description: str
    conditions: list[Condition] = field(default_factory=list)
    game_date: str = ""
    written: str = ""
    fired: str = ""


@dataclass
class Reading:
    """A condition with its value on the current save."""

    condition: Condition
    value: float | bool | None
    met: bool


class WatchError(ValueError):
    """A condition the watches cannot check (unknown metric, wrong operator or value)."""


def check(campaign: Campaign, watch: Watch) -> list[Reading]:
    """Each condition of a watch with its current value and whether it holds."""
    readings = []
    for condition in watch.conditions:
        metric = METRICS[condition.metric]
        country = condition.country or campaign.player
        other = condition.other or campaign.player
        try:
            value = metric.read(campaign, country, other)
        except (KeyError, ValueError, TypeError):
            value = None
        readings.append(Reading(condition, value, _holds(condition, value)))
    return readings


def validate_condition(raw: Any) -> Condition:
    """A condition from a tool call (countries still as given; resolve them after).

    Raises:
        WatchError: If it names an unknown metric, a wrong operator or a wrong value.
    """
    if not isinstance(raw, dict):
        raise WatchError("Each condition is an object with metric, op and value.")
    name = str(raw.get("metric") or "").strip().lower()
    if name not in METRICS:
        raise WatchError(f"Unknown metric '{name}'; use one of: {', '.join(METRICS)}.")
    metric = METRICS[name]
    op, value = _loose(raw.get("op"), raw.get("value"), metric.kind)
    if metric.kind == "bool":
        if op != "is" or not isinstance(value, bool):
            raise WatchError(f"'{name}' is true or false: use op 'is' with true or false.")
    else:
        if op not in (">=", "<=") or isinstance(value, bool) or not isinstance(value, int | float):
            raise WatchError(f"'{name}' is a number: use op '>=' or '<=' with a number.")
        value = float(value)
    country = raw.get("country") or ""
    other = raw.get("other") or ""
    if not isinstance(country, str) or not isinstance(other, str):
        raise WatchError("`country` and `other` are country names or tags.")
    if other and not metric.other:
        raise WatchError(f"'{name}' looks at one country; leave `other` out.")
    return Condition(name, op, value, country, other)


def describe(condition: Condition, campaign: Campaign) -> str:
    """A condition in words, with its countries named."""
    metric = METRICS[condition.metric]
    who = campaign.name(condition.country) if condition.country else "you"
    text = f"{condition.metric} of {who}"
    if metric.other:
        text += f" with {campaign.name(condition.other) if condition.other else 'you'}"
    if metric.kind == "bool":
        return f"{text} is {'true' if condition.value else 'false'}"
    return f"{text} {condition.op} {_number(condition.value)}"


def show(value: float | bool | None) -> str:
    """A metric's current value for the output."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    return _number(value)


def metric_list() -> str:
    """The metrics, one per line, for the tool description."""
    return "; ".join(f"{name} ({m.kind}): {m.description}" for name, m in METRICS.items())


def to_dict(watch: Watch) -> dict[str, Any]:
    """Plain values for JSON."""
    return {
        "id": watch.id,
        "description": watch.description,
        "conditions": [vars(c).copy() for c in watch.conditions],
        "game_date": watch.game_date,
        "written": watch.written,
        "fired": watch.fired,
    }


def from_dict(raw: dict[str, Any]) -> Watch:
    """A watch read back from JSON; unknown metrics are dropped."""
    conditions = []
    for item in raw.get("conditions", []):
        if isinstance(item, dict) and item.get("metric") in METRICS:
            conditions.append(
                Condition(
                    str(item["metric"]),
                    str(item.get("op", ">=")),
                    item.get("value", 0),
                    str(item.get("country", "")),
                    str(item.get("other", "")),
                )
            )
    return Watch(
        id=int(raw.get("id", 0)),
        description=str(raw.get("description", "")),
        conditions=conditions,
        game_date=str(raw.get("game_date", "")),
        written=str(raw.get("written", "")),
        fired=str(raw.get("fired", "")),
    )


def _loose(op: Any, value: Any, kind: str) -> tuple[Any, Any]:
    """Forgive common slips in a tool call: "1.5" or "true" as text, > for >=, = for is."""
    op = str(op or "").strip()
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes"):
            value = True
        elif text in ("false", "no"):
            value = False
        else:
            with contextlib.suppress(ValueError):  # not a number: refused below
                value = float(text)
    if kind == "bool":
        if op in ("=", "==", "is"):
            op = "is"
        if isinstance(value, int | float) and not isinstance(value, bool) and value in (0, 1):
            value = bool(value)
    else:
        op = {">": ">=", "<": "<=", "=>": ">=", "=<": "<="}.get(op, op)
    return op, value


# --- metrics --------------------------------------------------------------------------------


def _holds(condition: Condition, value: float | bool | None) -> bool:
    if value is None:
        return False
    if condition.op == "is":
        return bool(value) is bool(condition.value)
    if isinstance(value, bool):
        return False
    if condition.op == ">=":
        return value >= float(condition.value)
    return value <= float(condition.value)


def _number(value: float | bool) -> str:
    number = float(value)
    return f"{number:.0f}" if number == int(number) else f"{number:.2f}".rstrip("0")


def _field(key: str, scale: float = 1.0) -> Callable[[Campaign, str, str], float | None]:
    def read(campaign: Campaign, country: str, _: str) -> float | None:
        data = campaign.country(country)
        if data is None:
            return None
        return float(data.get(key) or 0.0) * scale

    return read


def _power(index: int) -> Callable[[Campaign, str, str], float | None]:
    def read(campaign: Campaign, country: str, _: str) -> float | None:
        data = campaign.country(country)
        powers = [v for v in as_list((data or {}).get("powers")) if isinstance(v, int | float)]
        return float(powers[index]) if len(powers) > index else None

    return read


def _tech(category: str) -> Callable[[Campaign, str, str], float | None]:
    def read(campaign: Campaign, country: str, _: str) -> float | None:
        data = campaign.country(country)
        if data is None:
            return None
        return float((data.get("technology") or {}).get(f"{category}_tech", 0) or 0)

    return read


def _manpower_percent(campaign: Campaign, country: str, _: str) -> float | None:
    data = campaign.country(country)
    if data is None or not data.get("max_manpower"):
        return None
    return 100 * float(data.get("manpower") or 0.0) / float(data["max_manpower"])


def _regiments(campaign: Campaign, country: str, _: str) -> float | None:
    data = campaign.country(country)
    return float(count_regiments(data)) if data is not None else None


def _ae(campaign: Campaign, country: str, other: str) -> float:
    for grievance in campaign.aggressive_expansion_towards(other):
        if grievance.tag == country:
            return grievance.value
    return 0.0


def _at_coalition_ae(campaign: Campaign, _: str, other: str) -> float:
    return float(
        sum(1 for g in campaign.aggressive_expansion_towards(other) if g.value >= COALITION_AE)
    )


def _coalition_members(campaign: Campaign, country: str, _: str) -> float | None:
    from chancellor.context.war_check import _coalition

    data = campaign.country(country)
    return float(len(set(_coalition(data)))) if data is not None else None


def _war_odds(campaign: Campaign, country: str, other: str) -> float | None:
    from chancellor.context.war_check import check_war

    if country == other or not campaign.exists(country):
        return None
    war = check_war(campaign, country, other)
    attackers = war.totals("attackers", worst_case=False).regiments
    defenders = war.totals("defenders", worst_case=True).regiments
    if not defenders:
        return WAR_ODDS_UNDEFENDED if attackers else None
    return attackers / defenders


def _at_war(campaign: Campaign, country: str, _: str) -> bool:
    return bool(campaign.wars_of(country))


def _truce(campaign: Campaign, country: str, other: str) -> bool:
    return campaign.truce(country, other) is not None


def _allied(campaign: Campaign, country: str, other: str) -> bool:
    return any(
        {link.get("first"), link.get("second")} == {country, other}
        for link in campaign.active_links("alliance")
    )


def _exists(campaign: Campaign, country: str, _: str) -> bool:
    return campaign.exists(country)


def _year(campaign: Campaign, _: str, __: str) -> float | None:
    parts = campaign.date.split(".")
    try:
        year, month, day = (int(p) for p in parts)
    except ValueError:
        return None
    return year + (month - 1) / 12 + (day - 1) / 365


METRICS: dict[str, Metric] = {
    "treasury": Metric("ducats in the treasury", "number", False, _field("treasury")),
    "manpower": Metric("manpower in thousands", "number", False, _field("manpower")),
    "manpower_percent": Metric("manpower as % of the maximum", "number", False, _manpower_percent),
    "adm_power": Metric("administrative points", "number", False, _power(0)),
    "dip_power": Metric("diplomatic points", "number", False, _power(1)),
    "mil_power": Metric("military points", "number", False, _power(2)),
    "stability": Metric("stability (-3 to 3)", "number", False, _field("stability")),
    "war_exhaustion": Metric("war exhaustion", "number", False, _field("war_exhaustion")),
    "overextension": Metric(
        "overextension in %", "number", False, _field("overextension_percentage", 100)
    ),
    "prestige": Metric("prestige", "number", False, _field("prestige")),
    "adm_tech": Metric("administrative technology level", "number", False, _tech("adm")),
    "dip_tech": Metric("diplomatic technology level", "number", False, _tech("dip")),
    "mil_tech": Metric("military technology level", "number", False, _tech("mil")),
    "development": Metric("total development", "number", False, _field("raw_development")),
    "regiments": Metric("land regiments, at sea included", "number", False, _regiments),
    "ae": Metric(
        "aggressive expansion the country holds against `other` (coalitions form at 50)",
        "number",
        True,
        _ae,
    ),
    "countries_at_coalition_ae": Metric(
        "how many countries hold 50+ AE against `other` (country is ignored)",
        "number",
        True,
        _at_coalition_ae,
    ),
    "coalition_members": Metric(
        "members of the coalition against the country", "number", False, _coalition_members
    ),
    "war_odds": Metric(
        "the war check's odds if `other` attacked the country: `other`'s likely regiments "
        "over the country's worst-case defenders (1.5 = 50% stronger)",
        "number",
        True,
        _war_odds,
    ),
    "at_war": Metric("the country is at war", "bool", False, _at_war),
    "truce": Metric("the country has a truce with `other`", "bool", True, _truce),
    "allied": Metric("the country is allied with `other`", "bool", True, _allied),
    "exists": Metric("the country exists (owns land)", "bool", False, _exists),
    "year": Metric("the in-game year, with a fraction for the month", "number", False, _year),
}
