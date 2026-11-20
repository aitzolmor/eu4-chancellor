"""What needs the player's attention now: short, ranked alerts for the desktop panel.

Built only from facts the other queries already produce (wars, coalitions, aggressive
expansion, truces, the economy, the Holy Roman Empire), so each alert can be checked
against a briefing or a war check. UI_DESIGN, build order step 3.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from chancellor.context.campaign import Campaign, as_list
from chancellor.context.decisions import check_decisions
from chancellor.context.missions import mission_tree
from chancellor.context.script import clean_text
from chancellor.game.decisions import DecisionLibrary
from chancellor.game.imperial_reforms import IMPERIAL_REFORM_COST, ImperialReformLibrary
from chancellor.game.missions import MissionLibrary
from chancellor.game.rules import GameRules
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


@dataclass
class ReadyNow:
    """What the country can claim right now (D-055).

    Attributes:
        missions: Keys of the available missions whose requirements are all met.
        formables: Keys of the formable-nation decisions whose requirements are all met.
    """

    missions: list[str] = field(default_factory=list)
    formables: list[str] = field(default_factory=list)


def ready_now(
    campaign: Campaign,
    rules: GameRules,
    missions: MissionLibrary,
    decisions: DecisionLibrary,
    tag: str | None = None,
) -> ReadyNow:
    """Missions that can be completed and nations that can be formed now (about 3 s).

    Only what the evaluator settles as certainly met counts; a requirement it cannot
    check keeps the mission or nation out, so the alert never claims too much.
    """
    tag = tag or campaign.player
    tree = mission_tree(campaign, missions, tag, rules)
    formables = check_decisions(campaign, rules, decisions, tag, missions, formables_only=True)
    return ReadyNow(
        missions=[m.mission.name for m in tree.available() if m.completable is True],
        formables=[d.decision.name for d in formables if d.can_take is True],
    )


def title(campaign: Campaign, key: str) -> str:
    """A mission's or decision's title in the game's language."""
    text = campaign.loc.get(f"{key}_title", "")
    return clean_text(text, campaign) if text else key.replace("_", " ")


def campaign_alerts(
    campaign: Campaign,
    tag: str | None = None,
    reforms: ImperialReformLibrary | None = None,
    ready: ReadyNow | None = None,
) -> list[Alert]:
    """Alerts for a country (default: the player), most severe first.

    Args:
        campaign: The loaded save.
        tag: Country to check; defaults to the player.
        reforms: Imperial reforms from the game files; without them the reform alert is
            skipped.
        ready: What can be claimed now (:func:`ready_now`); without it, no mission or
            formable alerts.

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
        *_ready(campaign, ready),
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


def _ready(campaign: Campaign, ready: ReadyNow | None) -> list[Alert]:
    if ready is None:
        return []
    alerts = []
    if ready.formables:
        names = ", ".join(title(campaign, d) for d in ready.formables)
        alerts.append(Alert("formable_ready", "medium", f"Can be taken now: {names}"))
    if ready.missions:
        names = ", ".join(title(campaign, m) for m in ready.missions)
        count = _plural(len(ready.missions), "mission")
        alerts.append(Alert("missions_ready", "info", f"{count} can be completed: {names}"))
    return alerts


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
