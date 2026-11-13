"""What needs the player's attention now: short, ranked alerts for the desktop panel.

Built only from facts the other queries already produce (wars, coalitions, aggressive
expansion, truces, the economy, the Holy Roman Empire), so each alert can be checked
against a briefing or a war check. UI_DESIGN, build order step 3.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from chancellor.context.campaign import Campaign, as_list
from chancellor.game.imperial_reforms import IMPERIAL_REFORM_COST, ImperialReformLibrary
from chancellor.save.parser import get_all

Severity = Literal["high", "medium", "info"]
_ORDER = {"high": 0, "medium": 1, "info": 2}

AE_COALITION_THRESHOLD = 50  # common/defines.lua: AE_COALITION_THRESHOLD = -50
TRUCE_WARNING_MONTHS = 24  # warn about truces with rivals or neighbours ending this soon
WAR_EXHAUSTION_WARNING = 5.0
MONARCH_POWER_CAP = 999  # points stop accumulating here
MONARCH_POWER_WARNING = 900


@dataclass(frozen=True)
class Alert:
    """One thing worth the player's attention.

    Attributes:
        kind: Stable identifier, e.g. ``coalition`` or ``truce``.
        severity: ``high`` (act now), ``medium`` (plan for it) or ``info``.
        text: One short line for the panel.
    """

    kind: str
    severity: Severity
    text: str

    def to_dict(self) -> dict[str, Any]:
        """Plain values for JSON."""
        return asdict(self)


def campaign_alerts(
    campaign: Campaign,
    tag: str | None = None,
    reforms: ImperialReformLibrary | None = None,
) -> list[Alert]:
    """Alerts for a country (default: the player), most severe first.

    Args:
        campaign: The loaded save.
        tag: Country to check; defaults to the player.
        reforms: Imperial reforms from the game files; without them the reform alert is
            skipped.

    Raises:
        KeyError: If the country is not in the save.
    """
    tag = tag or campaign.player
    country = campaign.country(tag)
    if country is None:
        raise KeyError(f"Country {tag} is not in the save")
    alerts = [
        *_wars(campaign, tag),
        *_coalition(campaign, tag, country),
        *_truces(campaign, tag, country),
        *_economy(country),
        *_stability(country),
        *_monarch_power(country),
        *_imperial_reform(campaign, tag, reforms),
    ]
    return sorted(alerts, key=lambda a: _ORDER[a.severity])


def _wars(campaign: Campaign, tag: str) -> list[Alert]:
    return [
        Alert("war", "high", f"At war: {str(war.get('name', '?')).strip()}")
        for war in campaign.wars_of(tag)
    ]


def _coalition(campaign: Campaign, tag: str, country: dict[str, Any]) -> list[Alert]:
    members: list[str] = []
    for value in get_all(country, "coalition_against_us"):
        members += [str(t) for t in as_list(value)]
    alerts = []
    if members:
        alerts.append(
            Alert(
                "coalition", "high", f"Coalition of {_plural(len(members), 'country')} against you"
            )
        )
    allies = {str(t) for t in as_list(country.get("allies"))}
    could_join = [
        g
        for g in campaign.aggressive_expansion_towards(tag)
        if g.value >= AE_COALITION_THRESHOLD
        and g.tag not in members
        and g.tag not in allies
        and not campaign.subject_type(tag, g.tag)
    ]
    if could_join:
        names = ", ".join(campaign.name(g.tag) for g in could_join[:3])
        more = f" and {len(could_join) - 3} more" if len(could_join) > 3 else ""
        alerts.append(
            Alert(
                "aggressive_expansion",
                "medium",
                f"{len(could_join)} more could join a coalition (50+ AE): {names}{more}",
            )
        )
    return alerts


def _truces(campaign: Campaign, tag: str, country: dict[str, Any]) -> list[Alert]:
    """Truces with rivals or neighbours ending soon: wars they could start, or you could."""
    rivals = {r["country"] for r in get_all(country, "rival") if isinstance(r, dict)}
    watched = rivals | {str(t) for t in as_list(country.get("neighbours"))}
    alerts = []
    for truce in campaign.truces(tag):
        if truce.other not in watched or truce.estimated_end is None:
            continue
        months = _months_between(campaign.date, truce.estimated_end)
        if months is None or months > TRUCE_WARNING_MONTHS:
            continue
        who = "rival" if truce.other in rivals else "neighbour"
        alerts.append(
            Alert(
                "truce",
                "medium",
                f"Truce with {campaign.name(truce.other)} ({who}) ends around "
                f"{truce.estimated_end} (estimate)",
            )
        )
    return alerts


def _economy(country: dict[str, Any]) -> list[Alert]:
    alerts = []
    ledger = country.get("ledger") or {}
    income, expense = ledger.get("lastmonthincome"), ledger.get("lastmonthexpense")
    if isinstance(income, float) and isinstance(expense, float) and expense > income:
        alerts.append(Alert("balance", "medium", f"Losing {expense - income:.1f} ducats a month"))
    loans = [loan for loan in get_all(country, "loan") if isinstance(loan, dict)]
    if loans:
        debt = sum(float(loan.get("amount", 0)) for loan in loans)
        text = f"{_plural(len(loans), 'loan')}, {debt:.0f} ducats of debt"
        alerts.append(Alert("loans", "medium", text))
    overextension = country.get("overextension_percentage")
    if isinstance(overextension, float) and overextension > 0:
        severity: Severity = "high" if overextension >= 1 else "medium"
        alerts.append(Alert("overextension", severity, f"Overextension {overextension * 100:.0f}%"))
    exhaustion = country.get("war_exhaustion")
    if isinstance(exhaustion, float) and exhaustion >= WAR_EXHAUSTION_WARNING:
        alerts.append(Alert("war_exhaustion", "medium", f"War exhaustion {exhaustion:.1f}"))
    return alerts


def _stability(country: dict[str, Any]) -> list[Alert]:
    stability = country.get("stability")
    if isinstance(stability, int | float) and stability < 0:
        return [Alert("stability", "high", f"Stability {stability:+.0f}")]
    return []


def _monarch_power(country: dict[str, Any]) -> list[Alert]:
    points = [v for v in as_list(country.get("powers")) if isinstance(v, int | float)]
    if len(points) != 3:
        return []
    kinds = ("Administrative", "Diplomatic", "Military")
    return [
        Alert(
            "monarch_power",
            "info",
            f"{kind} power at {value:.0f} of {MONARCH_POWER_CAP}: spend it before it is wasted",
        )
        for kind, value in zip(kinds, points, strict=True)
        if value >= MONARCH_POWER_WARNING
    ]


def _imperial_reform(
    campaign: Campaign, tag: str, reforms: ImperialReformLibrary | None
) -> list[Alert]:
    if reforms is None or campaign.emperor != tag:
        return []
    authority = campaign.empire.get("imperial_influence")
    if not isinstance(authority, int | float) or authority < IMPERIAL_REFORM_COST:
        return []
    passed = [str(r) for r in as_list(campaign.empire.get("passed_reform"))]
    dlc = "Emperor" in [str(d) for d in as_list(campaign.meta.get("dlc_enabled"))]
    upcoming = reforms.next_reforms(passed, has_emperor_dlc=dlc)
    if not upcoming:
        return []
    titles = " or ".join(
        campaign.loc.get(f"{r.name}_title", "") or r.name.replace("_", " ") for r in upcoming
    )
    return [
        Alert(
            "imperial_reform",
            "info",
            f"{titles} can be proposed (imperial authority {authority:.0f})",
        )
    ]


def _plural(count: int, noun: str) -> str:
    """``1 country``, ``19 countries``, ``2 loans``."""
    if count == 1:
        return f"1 {noun}"
    return f"{count} {noun[:-1] + 'ies' if noun.endswith('y') else noun + 's'}"


def _months_between(start: str, end: str) -> int | None:
    try:
        y1, m1, _ = (int(p) for p in start.split("."))
        y2, m2, _ = (int(p) for p in end.split("."))
    except ValueError:
        return None
    return (y2 - y1) * 12 + (m2 - m1)
