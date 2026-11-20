"""What to do now: structured action recommendations (Phase 6, "Advise"; D-056).

The other tools describe the campaign; this one turns what they compute into a short,
ranked list of actions, each with the facts behind it. Every recommendation is built
from a rule over numbers the rest of the code already computes and the player can
check: missions and formables ready to claim (D-054, D-055), monarch power and what it
buys, overextension and coring costs, the budget (D-052), the expansion targets with
their odds, coalition risk and casus belli (D-051). Nothing here is a guess the save
cannot back.

Recommendations are *structured* (a kind, a target, a priority) rather than prose, so
the next rungs of the vision can build on them: "Guide" maps each kind to the game's
screens, and "Act" carries it out. Choosing among them is left to the model and the
player, with the player's recorded goals marked on the ones that touch them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from chancellor.context.alerts import ReadyNow, title
from chancellor.context.campaign import Campaign
from chancellor.context.coring import CoringCost
from chancellor.context.ledger import Ledger
from chancellor.context.missions import MissionTree, one_line
from chancellor.context.power import PowerReport, months_until_affordable
from chancellor.context.targets import TargetReport
from chancellor.save.parser import get_all

Priority = Literal["now", "soon", "consider"]


class CasusBelliData(Protocol):
    """The probe mod's casus belli check (``live.casus_belli.CasusBelli``, D-051)."""

    def against(self, target: str) -> list[tuple[str | None, str]]: ...  # noqa: D102

    def covers(self, target: str) -> bool: ...  # noqa: D102


_ORDER = {"now": 0, "soon": 1, "consider": 2}
_LABELS = {"adm": "administrative", "dip": "diplomatic", "mil": "military"}

POWER_CAP_WARNING = 900  # points stop accumulating at 999
COALITION_AE = 50
GOOD_ODDS = 2.0
TARGETS_SHOWN = 3
CORING_SHOWN = 3
MAX_IDEAS = 7


@dataclass
class Recommendation:
    """One action worth taking, with why.

    Attributes:
        kind: What sort of action (``complete_mission``, ``declare_war``, ...): stable,
            so later steps can map it to the game's screens.
        priority: ``now`` (do it now), ``soon`` (plan for it) or ``consider``.
        action: The action, in one line.
        reasons: The facts behind it, each checkable in the game or another tool.
        target: What it acts on: a mission or decision key, a country tag, a province id,
            a technology category.
        source: The tool with the details.
        goals: Ids of the player's recorded goals it touches.
    """

    kind: str
    priority: Priority
    action: str
    reasons: list[str] = field(default_factory=list)
    target: str | None = None
    source: str = ""
    goals: list[int] = field(default_factory=list)


@dataclass
class Goal:
    """A goal the player recorded (player context)."""

    id: int
    text: str


def recommend(
    campaign: Campaign,
    *,
    tag: str | None = None,
    ready: ReadyNow | None = None,
    tree: MissionTree | None = None,
    power: PowerReport | None = None,
    coring: list[CoringCost] | None = None,
    ledger: Ledger | None = None,
    targets: TargetReport | None = None,
    casus_belli: CasusBelliData | None = None,
    goals: list[Goal] | None = None,
) -> list[Recommendation]:
    """Recommendations for a country (the player's by default), most urgent first.

    Each input is optional: a missing one (no game files, no probe mod) only drops the
    recommendations that need it.
    """
    tag = tag or campaign.player
    found: list[Recommendation] = []
    if ready is not None:
        found += _ready(campaign, ready, tree)
    if ledger is not None:
        found += _budget(campaign, tag, ledger)
    if power is not None:
        found += _power(power)
    if coring is not None:
        found += _coring(campaign, tag, coring, power)
    if targets is not None:
        waiting = {r.target: r.reasons for r in found if r.kind == "time_mission" and r.target}
        done = [title(campaign, k) for k in (ready.missions if ready else []) if k not in waiting]
        wait_lines = [
            line for lines in waiting.values() for line in lines if line.startswith("now ")
        ]
        found += _expansion(campaign, targets, casus_belli, done, wait_lines)
    found += _coalition(campaign, tag)
    if tree is not None:
        found += _missions_close(tree)
    for recommendation in found:
        recommendation.goals = _goals_touched(campaign, recommendation, goals or [])
    return sorted(found, key=lambda r: (_ORDER[r.priority], not r.goals))


def render_recommendations(
    campaign: Campaign,
    recommendations: list[Recommendation],
    goals: list[Goal],
    tag: str | None = None,
    missing: list[str] | None = None,
) -> str:
    """Markdown for ``get_recommendations``."""
    tag = tag or campaign.player
    lines = [f"# What to do now: {campaign.label(tag)}, {campaign.date}", ""]
    if goals:
        lines += ["Recorded goals: " + "; ".join(f"#{g.id} {g.text}" for g in goals), ""]
    if not recommendations:
        lines.append("Nothing stands out: no mission or nation is ready, the budget is fine,")
        lines.append("power is not piling up and no target is clearly favourable.")
    heading = {"now": "Now", "soon": "Soon", "consider": "To consider"}
    number = 0
    for priority in ("now", "soon", "consider"):
        group = [r for r in recommendations if r.priority == priority]
        if not group:
            continue
        lines += [f"## {heading[priority]}", ""]
        for item in group:
            number += 1
            touched = f" (goal {', '.join(f'#{g}' for g in item.goals)})" if item.goals else ""
            # The kind and target as keys: stable for checks and for "Guide" (D-058).
            key = f"{item.kind} {item.target}" if item.target else item.kind
            lines.append(f"{number}. **{item.action}**{touched} `[{key}]`")
            lines += [f"   - {reason}" for reason in item.reasons]
            if item.source:
                lines.append(f"   - Details: {item.source}")
        lines.append("")
    if missing:
        lines += ["Not covered here: " + "; ".join(missing) + ".", ""]
    lines.append(
        "_Each recommendation comes from a rule over the save's numbers (and the probe "
        "mod's casus belli when it runs); none is a plan. Weigh them with the player's "
        "goals and say which you would take first, and why._"
    )
    return "\n".join(lines) + "\n"


# --- rules ---------------------------------------------------------------------------


def _ready(campaign: Campaign, ready: ReadyNow, tree: MissionTree | None) -> list[Recommendation]:
    found = [
        Recommendation(
            "form_nation",
            "now",
            f"Take the decision «{title(campaign, key)}»",
            ["every requirement is met (checked against the save)"],
            key,
            "get_decisions",
        )
        for key in ready.formables
    ]
    states = {m.mission.name: m for m in tree.available()} if tree else {}
    for key in ready.missions:
        state = states.get(key)
        better = [c for c in (state.reward_conditions if state else []) if c.met is False]
        if not better:
            found.append(
                Recommendation(
                    "complete_mission",
                    "now",
                    f"Complete the mission «{title(campaign, key)}»",
                    ["every requirement is met (checked against the save); claim the reward"],
                    key,
                    "get_missions",
                )
            )
            continue
        # The reward grows under a condition not met yet: claiming waits for the right
        # moment (D-057), so the player decides when.
        reasons = ["every requirement is met, but part of the reward needs more:"]
        for condition in better:
            reasons += [f"now {value}" for value in condition.now]
            reasons.append(f"then it also gives: {one_line(condition.reward)}")
        reasons.append("claiming now gives the rest of the reward and loses that part")
        found.append(
            Recommendation(
                "time_mission",
                "soon",
                f"Complete «{title(campaign, key)}» now, or wait for the better reward",
                reasons,
                key,
                "get_missions",
            )
        )
    return found


def _budget(campaign: Campaign, tag: str, ledger: Ledger) -> list[Recommendation]:
    found = []
    income, spent = ledger.recurring_income, ledger.recurring_expenses
    if income is not None and spent is not None and income < spent:
        costs = sorted(ledger.last_month_expenses.items(), key=lambda i: -i[1])[:3]
        found.append(
            Recommendation(
                "fix_deficit",
                "now",
                "Fix the deficit",
                [
                    f"recurring balance {income - spent:+.2f} ducats a month",
                    "largest costs: " + ", ".join(f"{n} {v:.1f}" for n, v in costs),
                ],
                None,
                "get_budget",
            )
        )
    country = campaign.country(tag) or {}
    loans = [loan for loan in get_all(country, "loan") if isinstance(loan, dict)]
    treasury = country.get("treasury")
    if loans and isinstance(treasury, int | float):
        smallest = min(float(loan.get("amount", 0) or 0) for loan in loans)
        if smallest and treasury >= smallest:
            found.append(
                Recommendation(
                    "repay_loan",
                    "soon",
                    "Repay a loan",
                    [
                        f"{len(loans)} loans; the smallest is {smallest:.0f} ducats and the "
                        f"treasury holds {treasury:.0f}; interest stops with it"
                    ],
                    None,
                    "get_country_briefing",
                )
            )
    reparations = ledger.last_month_income.get("War reparations", 0.0)
    total = sum(ledger.last_month_income.values())
    if total and reparations / total >= 0.1:
        found.append(
            Recommendation(
                "plan_income",
                "consider",
                "Plan for the end of the war reparations",
                [
                    f"{reparations:.1f} of {total:.1f} ducats a month ({reparations / total:.0%}) "
                    "come from war reparations, which stop 10 years after the peace"
                ],
                None,
                "get_budget",
            )
        )
    return found


def _power(power: PowerReport) -> list[Recommendation]:
    found = []
    for category, label in _LABELS.items():
        points = power.points.get(category, 0)
        tech = power.techs.get(category)
        affordable = tech is not None and tech.cost <= points
        capped = points >= POWER_CAP_WARNING
        if affordable and tech is not None and (not tech.months_ahead or capped):
            found.append(
                Recommendation(
                    "buy_technology",
                    "now" if capped else "soon",
                    f"Buy {label} technology {tech.level}",
                    [
                        f"costs {tech.cost}, you have {points} "
                        f"(+{power.monthly.get(category, 0):.1f} a month)"
                        + (
                            "; it is ahead of its time, so it costs more now"
                            if tech.months_ahead
                            else ""
                        )
                    ],
                    category,
                    "get_country_briefing",
                )
            )
        elif capped:
            found.append(
                Recommendation(
                    "spend_power",
                    "now",
                    f"Spend {label} power",
                    [f"{points} of 999 points: anything gained beyond the cap is lost"],
                    category,
                    "get_country_briefing",
                )
            )
        elif tech is not None:
            months = months_until_affordable(power, category)
            if months is not None and 0 < months <= 6 and not tech.months_ahead:
                found.append(
                    Recommendation(
                        "save_power",
                        "consider",
                        f"Save {label} power for technology {tech.level}",
                        [f"affordable in about {months} months at the current gain"],
                        category,
                        "get_country_briefing",
                    )
                )
    open_groups = [name for name, taken in power.idea_groups if taken < MAX_IDEAS]
    free_slot = len(power.idea_groups) < power.idea_slots
    if open_groups or free_slot:
        for category, label in _LABELS.items():
            if power.points.get(category, 0) >= power.idea_cost + 200:
                where = f"in {', '.join(open_groups)}" if open_groups else "in a new group"
                found.append(
                    Recommendation(
                        "buy_idea",
                        "consider",
                        f"Take the next idea with {label} power",
                        [
                            f"an idea costs {power.idea_cost}; you have "
                            f"{power.points[category]}; open: {where}"
                        ],
                        category,
                        "get_country_briefing",
                    )
                )
                break
    if power.stability < 1 and power.stability_cost <= power.points.get("adm", 0):
        found.append(
            Recommendation(
                "raise_stability",
                "soon",
                "Raise stability",
                [
                    f"stability {power.stability:+.0f}; a point costs {power.stability_cost} "
                    "administrative power"
                ],
                "adm",
                "get_country_briefing",
            )
        )
    return found


def _coring(
    campaign: Campaign, tag: str, coring: list[CoringCost], power: PowerReport | None
) -> list[Recommendation]:
    country = campaign.country(tag) or {}
    overextension = 100 * float(country.get("overextension_percentage") or 0.0)
    if overextension <= 0 or not coring:
        return []
    cheapest = coring[:CORING_SHOWN]
    points = power.points.get("adm") if power else None
    return [
        Recommendation(
            "core_province",
            "now" if overextension >= 50 else "soon",
            "Core " + ", ".join(c.name for c in cheapest),
            [
                f"overextension {overextension:.0f}% (unrest, and more above 50%)",
                "; ".join(f"{c.name} {c.cost} adm, {c.months} months" for c in cheapest)
                + (f"; you have {points} administrative power" if points is not None else ""),
            ],
            str(cheapest[0].province),
            "get_country_briefing",
        )
    ]


def _expansion(
    campaign: Campaign,
    report: TargetReport,
    data: CasusBelliData | None,
    ready_missions: list[str] | None = None,
    waiting: list[str] | None = None,
) -> list[Recommendation]:
    good = [
        t
        for t in report.targets
        if not t.peaceful and not t.blocked and not t.risky and t.odds >= GOOD_ODDS
    ]
    found = []
    for target in good:
        if len(found) == TARGETS_SHOWN:
            break
        # A mission that can be completed already needs no war (D-056).
        wanted = [
            r
            for r in target.reasons
            if not any(r.startswith(f"mission: {m}") for m in ready_missions or [])
        ]
        if not wanted:
            continue
        reasons = [
            f"wanted for: {'; '.join(wanted)}",
            f"{len(target.provinces)} provinces, {target.development:.0f} development",
            f"odds {target.odds:.1f}x ({target.attacker_regiments} regiments vs "
            f"{target.defender_regiments})",
        ]
        if target.coalition_risk is not None:
            reasons.append(f"coalition risk: {target.coalition_risk.level}")
        name = campaign.name(target.owner)
        for line in waiting or []:  # a mission waits for this country to shrink (D-057)
            if line.startswith(f"now {name}:"):
                reasons.append(
                    f"taking land also brings a mission's better reward closer ({line[4:]})"
                )
        against = data.against(target.owner) if data is not None else []
        if against:
            shown = ", ".join(
                _cb_name(campaign, cb) + ("" if who is None else f" ({campaign.name(who)})")
                for who, cb in against
            )
            found.append(
                Recommendation(
                    "declare_war",
                    "soon",
                    f"War on {name}",
                    [*reasons, f"casus belli: {shown}"],
                    target.owner,
                    "check_war",
                )
            )
        elif data is not None and data.covers(target.owner):
            found.append(
                Recommendation(
                    "get_casus_belli",
                    "consider",
                    f"Get a casus belli on {name} (fabricate a claim)",
                    [*reasons, "no casus belli against it now"],
                    target.owner,
                    "check_war",
                )
            )
        else:
            found.append(
                Recommendation(
                    "declare_war",
                    "consider",
                    f"War on {name}, if you have a casus belli",
                    [*reasons, "casus belli not checked (the save does not hold them)"],
                    target.owner,
                    "check_war",
                )
            )
    return found


def _coalition(campaign: Campaign, tag: str) -> list[Recommendation]:
    angry = sorted(
        (g for g in campaign.aggressive_expansion_towards(tag) if g.value >= COALITION_AE),
        key=lambda g: -g.value,
    )
    if len(angry) < 3:
        return []
    worst = ", ".join(f"{campaign.name(g.tag)} {g.value:.0f}" for g in angry[:4])
    return [
        Recommendation(
            "hold_expansion",
            "soon",
            "Let aggressive expansion cool down before conquering near those countries",
            [
                f"{len(angry)} countries are at {COALITION_AE}+ AE and could join a coalition",
                f"worst: {worst}; improving relations lowers it faster",
            ],
            None,
            "get_expansion_targets",
        )
    ]


def _missions_close(tree: MissionTree) -> list[Recommendation]:
    found = []
    for state in tree.available():
        unmet = [r for r in state.requirements if r.met is False]
        if len(unmet) != 1 or state.count(None):
            continue
        missing = _compact(unmet[0].lines) or "one requirement"
        found.append(
            Recommendation(
                "work_towards_mission",
                "consider",
                f"Work towards «{state.title}»",
                [f"one requirement missing: {missing}"],
                state.mission.name,
                "get_missions",
            )
        )
    return found


def _compact(lines: list[str], limit: int = 160) -> str:
    """A described requirement on one line: "Provinces held...: value: 25; region: X"."""
    parts = [line.strip().removeprefix("- ").rstrip(":") for line in lines if line.strip()]
    text = parts[0] + (": " + "; ".join(parts[1:]) if len(parts) > 1 else "") if parts else ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cb_name(campaign: Campaign, cb: str) -> str:
    name = campaign.loc.get(cb, "")
    return name.rstrip(".").strip() or cb.removeprefix("cb_").replace("_", " ")


def _goals_touched(campaign: Campaign, item: Recommendation, goals: list[Goal]) -> list[int]:
    words = [item.action.lower()]
    if item.target and len(item.target) == 3 and item.target.isupper():
        words.append(campaign.name(item.target).lower())
    touched = []
    for goal in goals:
        text = goal.text.lower()
        names = [w for w in words[1:] if w and w in text]
        if names or (item.kind == "work_towards_mission" and _shares_name(item.action, text)):
            touched.append(goal.id)
    return touched


def _shares_name(action: str, goal: str) -> bool:
    """Whether a mission title and a goal share a capitalised word (Nápoles, Croacia)."""
    inner = action.split("«")[-1].rstrip("»")
    # Proper names only: a title's first word is capitalised anyway ("Liberar ...").
    words = inner.split()[1:]
    names = {w.strip(".,").lower() for w in words if w[:1].isupper() and len(w) > 3}
    return any(name in goal for name in names)


def goals_from(entries: list[object]) -> list[Goal]:
    """The player's recorded goals from their context entries."""
    return [
        Goal(int(getattr(e, "id", 0)), str(getattr(e, "text", "")))
        for e in entries
        if getattr(e, "kind", "") == "goal"
    ]
