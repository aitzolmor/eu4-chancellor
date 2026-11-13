"""Expansion targets: where the game points a country, who holds it, and how hard it is.

Crosses three things that are otherwise separate queries:

1. **Where to go.** Provinces named by the country's available missions, by the
   requirements of the formable nations it can see, by its claims and by cores it does
   not own. Province ids, areas and regions in those conditions are expanded to
   provinces using the game's geography. When a condition only counts provinces ("own
   4 provinces in Iberia"), the reason says so ("any 4 of 54 provinces in Iberia").
2. **Who holds them.** Wanted provinces are grouped by their current owner.
3. **How hard it is.** A :func:`chancellor.context.war_check.check_war` against each
   owner gives the expected and worst-case strength of both sides. Subjects, allies,
   coalition members and countries already at war are flagged.

The result (:class:`TargetReport`) is structured so the chat agent can use it as a tool;
:func:`render_targets` turns it into Markdown for the CLI.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, Truce, as_list
from chancellor.context.decisions import check_decisions
from chancellor.context.missions import mission_tree
from chancellor.context.war_check import check_war
from chancellor.game.decisions import DecisionLibrary
from chancellor.game.missions import MissionLibrary
from chancellor.game.rules import GameRules
from chancellor.save.parser import Repeated, get_all

# Condition keys whose integer value is a province id.
_PROVINCE_VALUE_KEYS = {
    "owns",
    "owns_core_province",
    "owns_or_non_sovereign_subject_of",
    "owns_or_subject_of",
    "controls",
    "province_id",
}
# Conditions that count owned provinces matching a filter.
_COUNT_KEYS = {
    "num_of_owned_provinces_with",
    "num_of_provinces_owned_or_owned_by_non_sovereign_subjects_with",
    "num_of_owned_and_controlled_institutions",
}
# Province-scope conditions about who owns or holds the province.
_OWNERSHIP_KEYS = {
    "owned_by",
    "country_or_non_sovereign_subject_holds",
    "country_or_subject_holds",
    "is_core",
    "controlled_by",
}
# Geography that is narrow enough to be a real target (continents and superregions are not).
_TARGET_GEOGRAPHY_KEYS = {"area", "region"}
_GEOGRAPHY_SUFFIXES = ("_area", "_region")
_MAX_GEOGRAPHY = 120  # ignore huge scopes such as whole continents
_HARD_SHOWN = 8


@dataclass(frozen=True)
class Quota:
    """A counted requirement: own ``needed`` of the provinces in some areas or regions.

    Attributes:
        needed: How many provinces the condition asks for.
        scope: The area or region names the provinces come from.
        size: How many provinces those scopes hold.
        optional: Whether the requirement sits inside an ``OR``, so other paths exist.
    """

    needed: int
    scope: tuple[str, ...]
    size: int
    optional: bool


@dataclass
class Target:
    """Wanted provinces held by one country.

    Attributes:
        owner: Tag of the current owner.
        provinces: Wanted province ids it owns.
        development: Total development of those provinces.
        reasons: Why they are wanted (mission titles, formables, "claims", "cores").
        relation: ``"subject"``, ``"ally"``, ``"overlord"`` or ``""``.
        coalition: Whether the owner is in a coalition against the country.
        owner_at_war: Whether the owner is already fighting someone.
        attacker_regiments: Expected regiments on the country's side.
        defender_regiments: Expected regiments defending the owner.
        defender_worst_case: Defending regiments including possible joiners.
        defenders: Main defenders (owner first), for display.
        truce: The country's truce with the owner, if any (war would break it).
        allied_defenders: The country's allies bound to defend the owner (its overlord,
            subjects or coalition); the war would turn them into enemies.
    """

    owner: str
    provinces: list[int]
    development: float
    reasons: list[str]
    relation: str = ""
    coalition: bool = False
    owner_at_war: bool = False
    attacker_regiments: int = 0
    defender_regiments: int = 0
    defender_worst_case: int = 0
    defenders: list[str] = field(default_factory=list)
    truce: Truce | None = None
    allied_defenders: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """Whether war has a cost beyond the fighting: breaking a truce or an alliance."""
        return self.truce is not None or bool(self.allied_defenders)

    @property
    def odds(self) -> float:
        """Attacker regiments per defending regiment (higher is easier)."""
        return self.attacker_regiments / max(self.defender_regiments, 1)

    @property
    def peaceful(self) -> bool:
        """Whether war is not the way to get these provinces (own subject or ally)."""
        return self.relation in ("subject", "ally", "overlord")


@dataclass
class TargetReport:
    """All expansion targets of a country.

    Attributes:
        tag: The country looking to expand.
        date: Save date.
        targets: One entry per owner, most attractive first.
        unowned: Wanted provinces nobody owns (colonisable or wasteland).
    """

    tag: str
    date: str
    targets: list[Target]
    unowned: list[int]


def find_targets(
    campaign: Campaign,
    rules: GameRules,
    missions: MissionLibrary,
    decisions: DecisionLibrary,
    tag: str | None = None,
) -> TargetReport:
    """Find where a country should expand and how hard each target is.

    Args:
        campaign: The loaded save.
        rules: Game data (geography for areas and regions).
        missions: Mission definitions.
        decisions: Decision definitions (for formable nations).
        tag: The expanding country; defaults to the player.

    Returns:
        The report.
    """
    tag = tag or campaign.player
    country = campaign.country(tag) or {}
    wanted: dict[int, list[str]] = {}

    def want(provinces: Iterable[int], reason: str) -> None:
        for province in provinces:
            reasons = wanted.setdefault(province, [])
            if reason not in reasons:
                reasons.append(reason)

    def want_script(script: Any, reason: str) -> None:
        by_quota: dict[Quota | None, list[int]] = {}
        for province, quota in wanted_provinces(script, rules).items():
            by_quota.setdefault(quota, []).append(province)
        for quota, provinces in by_quota.items():
            want(provinces, reason + (f" ({_describe_quota(campaign, quota)})" if quota else ""))

    tree = mission_tree(campaign, missions, tag)
    for column in tree.columns:
        for state in column.missions:
            if state.status == "available":
                want_script(state.mission.trigger, f"mission: {state.title}")

    for check in check_decisions(campaign, rules, decisions, tag, missions, formables_only=True):
        if check.visible is not True:  # only formables the country certainly sees
            continue
        forms = campaign.name(check.decision.forms or "")
        want_script(check.decision.allow, f"formable: {forms}")

    owned = {p for p in as_list(country.get("owned_provinces")) if isinstance(p, int)}
    want([p for p in as_list(country.get("claim_provinces")) if isinstance(p, int)], "claims")
    cores = {p for p in as_list(country.get("core_provinces")) if isinstance(p, int)}
    want(sorted(cores - owned), "cores")

    by_owner: dict[str, list[int]] = {}
    unowned = []
    for province_id in sorted(wanted):
        if province_id in owned:
            continue
        data = campaign.province(province_id) or {}
        owner = data.get("owner")
        if isinstance(owner, str):
            by_owner.setdefault(owner, []).append(province_id)
        elif data:
            unowned.append(province_id)

    targets = [
        _target(campaign, tag, owner, provinces, wanted) for owner, provinces in by_owner.items()
    ]
    targets.sort(key=_attractiveness)
    return TargetReport(tag=tag, date=campaign.date, targets=targets, unowned=unowned)


def provinces_in(script: Any, rules: GameRules) -> set[int]:
    """Province ids a condition asks to own; see :func:`wanted_provinces`."""
    return set(wanted_provinces(script, rules))


def wanted_provinces(script: Any, rules: GameRules) -> dict[int, Quota | None]:
    """Province ids a condition asks to own, with areas and regions expanded.

    Only ownership counts: ``owns``-style conditions, province counts
    (``num_of_owned_provinces_with`` and friends) and province or geography scopes whose
    conditions are about ownership (``owned_by``, ``is_core``, ...). A region merely
    mentioned for another reason is not a target. Continents and superregions are too
    broad to be targets and are ignored.

    Returns:
        Each wanted province with the :class:`Quota` it counts towards, or ``None`` when
        the condition names it on its own. A province named on its own anywhere is
        ``None``.
    """
    found: dict[int, Quota | None] = {}

    def add(provinces: Iterable[int], quota: Quota | None = None) -> None:
        for province in provinces:
            if quota is None or province not in found:
                found[province] = quota

    def walk(node: Any, in_or: bool) -> None:
        if isinstance(node, Repeated | list):
            for item in node:
                walk(item, in_or)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            for item in value if isinstance(value, Repeated) else [value]:
                if key in _PROVINCE_VALUE_KEYS:
                    add(v for v in as_list(item) if isinstance(v, int))
                elif key in _COUNT_KEYS:
                    _count(item, in_or)
                    continue
                elif key.lstrip("-").isdigit() and _about_ownership(item):
                    add([int(key.lstrip("-"))])
                elif (
                    key.endswith(_GEOGRAPHY_SUFFIXES)
                    and key in rules.geography
                    and _about_ownership(item)
                ):
                    add(_geography(key, rules))
                walk(item, in_or or key == "OR")

    def _count(block: Any, in_or: bool) -> None:
        """A counted condition: its areas and regions, and how many it asks for."""
        names: list[str] = []
        _scopes(block, names)
        provinces: set[int] = set()
        for name in names:
            provinces |= _geography(name, rules)
        needed = block.get("value") if isinstance(block, dict) else None
        if not provinces:
            return
        quota = (
            Quota(needed, tuple(names), len(provinces), in_or)
            if isinstance(needed, int) and needed < len(provinces)
            else None
        )
        add(sorted(provinces), quota)

    walk(script, False)
    return found


def _scopes(node: Any, names: list[str]) -> None:
    """Collect the area and region names inside a counted condition."""
    if isinstance(node, Repeated | list):
        for item in node:
            _scopes(item, names)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        for item in value if isinstance(value, Repeated) else [value]:
            if key in _TARGET_GEOGRAPHY_KEYS:
                names.extend(n for n in as_list(item) if isinstance(n, str) and n not in names)
            else:
                _scopes(item, names)


def _describe_quota(campaign: Campaign, quota: Quota) -> str:
    """``any 4 of 34 provinces in Iberia; one of several ways``."""
    names = [campaign.text(name) for name in quota.scope]
    where = ", ".join(names) if len(names) <= 2 else f"{names[0]}, {names[1]} and nearby"
    text = f"any {quota.needed} of {quota.size} provinces in {where}"
    return text + ("; one of several ways" if quota.optional else "")


def _about_ownership(block: Any) -> bool:
    """Whether a province or geography scope checks who owns or holds it."""
    if isinstance(block, Repeated | list):
        return any(_about_ownership(item) for item in block)
    if not isinstance(block, dict):
        return False
    return any(key in _OWNERSHIP_KEYS or _about_ownership(value) for key, value in block.items())


def render_targets(campaign: Campaign, report: TargetReport, top: int = 15) -> str:
    """Render a :class:`TargetReport` as Markdown.

    War targets come first, best odds first. Provinces held by the country's own subjects,
    allies or overlord are listed apart, because they are gained by diplomacy, not war.
    """
    label = campaign.label
    lines = [f"# Expansion targets: {label(report.tag)}, {report.date}", ""]
    if not report.targets:
        lines.append(
            "No foreign-held provinces are wanted by available missions, formable nations, "
            "claims or cores."
        )
        return "\n".join(lines) + "\n"

    war = [t for t in report.targets if not t.peaceful and t.odds >= 1]
    hard = sorted(
        (t for t in report.targets if not t.peaceful and t.odds < 1),
        key=lambda t: -t.development,
    )
    peaceful = [t for t in report.targets if t.peaceful]
    lines.append(
        "Provinces wanted by available missions, visible formable nations, claims and cores, "
        "grouped by who holds them now."
    )

    if war:
        lines += [
            "",
            "## War targets",
            "",
            "Odds compare the regiments expected on each side if war were declared today "
            "(certain and likely participants). Owners you have a truce with, or that "
            "your own allies would defend, come last. "
            "Favourable odds (2x or more) first, then even ones; within each, the most "
            "development first.",
            "",
            "| # | Held by | Provinces | Dev | Wanted for | You vs defenders | Odds | Notes |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for index, target in enumerate(war[:top], 1):
            sides = f"{target.attacker_regiments} vs {target.defender_regiments}"
            if target.defender_worst_case > target.defender_regiments:
                sides += f" (up to {target.defender_worst_case})"
            lines.append(
                f"| {index} | {label(target.owner)} | {len(target.provinces)} "
                f"| {target.development:.0f} | {_reasons(target)} | {sides} "
                f"| {target.odds:.1f}x | {_notes(campaign, target)} |"
            )
        if len(war) > top:
            lines += ["", f"{len(war) - top} more war targets not shown."]
            blocked = [t for t in war[top:] if t.blocked]
            if blocked:
                names = ", ".join(
                    f"{label(t.owner)} ({_obstacles(campaign, t)})" for t in blocked[:8]
                )
                more = f" and {len(blocked) - 8} more" if len(blocked) > 8 else ""
                lines.append(f"Not shown because of a truce or an allied defender: {names}{more}.")

    if hard:
        lines += [
            "",
            "## Hard targets (defenders outnumber you)",
            "",
            "| Held by | Provinces | Dev | Wanted for | You vs defenders | Odds | Notes |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for target in hard[:_HARD_SHOWN]:
            lines.append(
                f"| {label(target.owner)} | {len(target.provinces)} "
                f"| {target.development:.0f} | {_reasons(target)} "
                f"| {target.attacker_regiments} vs {target.defender_regiments} "
                f"| {target.odds:.1f}x | {_notes(campaign, target)} |"
            )
        if len(hard) > _HARD_SHOWN:
            lines += ["", f"{len(hard) - _HARD_SHOWN} more hard targets not shown."]

    if peaceful:
        lines += ["", "## Held by your subjects, allies or overlord", ""]
        for target in peaceful:
            lines.append(
                f"- {label(target.owner)} ({_notes(campaign, target)}): "
                f"{len(target.provinces)} provinces, {target.development:.0f} development; "
                f"wanted for {_reasons(target)}."
            )

    lines += ["", "## Details", ""]
    for target in [*war[:top], *hard[:_HARD_SHOWN]]:
        names = ", ".join(campaign.loc.province(p) for p in target.provinces[:10])
        if len(target.provinces) > 10:
            names += f" and {len(target.provinces) - 10} more"
        defenders = ", ".join(campaign.name(t) for t in target.defenders[:6])
        lines.append(f"- **{label(target.owner)}**: {names}.")
        lines.append(f"  - Wanted for: {'; '.join(target.reasons)}.")
        if defenders:
            lines.append(f"  - Defenders: {defenders}.")
    if report.unowned:
        lines += [
            "",
            f"{len(report.unowned)} wanted provinces are not owned by anyone "
            "(colonisable or wasteland).",
        ]
    lines += [
        "",
        "_Odds ignore casus belli, fort levels, generals and terrain; truce end dates are "
        "estimates. Missions only count when available now; formables only when visible to "
        "the country._",
    ]
    return "\n".join(lines) + "\n"


# --- helpers ---------------------------------------------------------------------------


def _geography(name: str, rules: GameRules) -> frozenset[int]:
    provinces = rules.geography.get(name, frozenset())
    return provinces if len(provinces) <= _MAX_GEOGRAPHY else frozenset()


def _target(
    campaign: Campaign, tag: str, owner: str, provinces: list[int], wanted: dict[int, list[str]]
) -> Target:
    reasons: list[str] = []
    for province in provinces:
        for reason in wanted[province]:
            if reason not in reasons:
                reasons.append(reason)
    # "form Alemania" (a named province) next to "form Alemania (any 50 of 119 ...)":
    # merge them into "form Alemania (specific provinces, plus any 50 of 119 ...)".
    named = {r for r in reasons if any(o.startswith(f"{r} (") for o in reasons)}
    merged = []
    for reason in reasons:
        if reason in named:
            continue
        base, _, detail = reason.partition(" (")
        if base in named and detail:
            reason = f"{base} (specific provinces, plus {detail}"
        merged.append(reason)
    reasons = merged
    development = 0.0
    for province in provinces:
        data = campaign.province(province) or {}
        development += sum(
            float(data.get(k) or 0) for k in ("base_tax", "base_production", "base_manpower")
        )
    country = campaign.country(tag) or {}
    owner_data = campaign.country(owner) or {}
    relation = ""
    if owner in as_list(country.get("subjects")):
        relation = "subject"
    elif owner in as_list(country.get("allies")):
        relation = "ally"
    elif owner_data.get("subjects") and tag in as_list(owner_data.get("subjects")):
        relation = "overlord"
    coalition = any(owner in as_list(v) for v in get_all(country, "coalition_against_us"))
    target = Target(
        owner=owner,
        provinces=provinces,
        development=development,
        reasons=reasons,
        relation=relation,
        coalition=coalition,
        owner_at_war=bool(campaign.wars_of(owner)),
    )
    if not target.peaceful:
        check = check_war(campaign, owner, tag)
        expected_attackers = check.totals("attackers", worst_case=False)
        target.attacker_regiments = expected_attackers.regiments
        target.defender_regiments = check.totals("defenders", worst_case=False).regiments
        target.defender_worst_case = check.totals("defenders", worst_case=True).regiments
        target.defenders = [p.tag for p in check.defenders]
        target.truce = check.truce
        target.allied_defenders = check.allied_defenders
    return target


def _attractiveness(target: Target) -> tuple[Any, ...]:
    """Peaceful targets apart; war targets by obstacles, odds tier, then development.

    Owners under a truce or defended by the country's own allies come after every other
    war target. Ranking by raw odds alone
    would put one-province minors above rich, slightly harder
    targets, so odds are bucketed: favourable (2x or more), even (1x-2x), unfavourable.
    """
    if target.peaceful:
        return (0, 0, 0, -target.development)
    tier = 0 if target.odds >= 2 else 1 if target.odds >= 1 else 2
    return (1, target.blocked, tier, -target.development)


def _notes(campaign: Campaign, target: Target) -> str:
    notes = []
    if target.relation == "subject":
        notes.append("your subject: annex or integrate")
    elif target.relation == "ally":
        notes.append("your ally")
    elif target.relation == "overlord":
        notes.append("your overlord")
    if target.coalition:
        notes.append("in a coalition against you")
    if target.owner_at_war:
        notes.append("already at war")
    obstacles = _obstacles(campaign, target)
    if obstacles:
        notes.append(obstacles)
    return "; ".join(notes)


def _obstacles(campaign: Campaign, target: Target) -> str:
    """The notes that make a war costly beyond the fighting."""
    notes = []
    if target.allied_defenders:
        allies = ", ".join(campaign.name(t) for t in target.allied_defenders)
        notes.append(f"defended by your ally {allies}")
    if target.truce:
        notes.append(_truce_note(target))
    return "; ".join(notes)


def _truce_note(target: Target) -> str:
    end = target.truce.estimated_end if target.truce else None
    return f"truce until about {end}" if end else "truce"


def _reasons(target: Target) -> str:
    return "; ".join(_short(r) for r in _summarise_reasons(target.reasons))


def _summarise_reasons(reasons: list[str]) -> list[str]:
    missions = [r for r in reasons if r.startswith("mission: ")]
    others = [r for r in reasons if not r.startswith("mission: ")]
    summary = others
    if len(missions) > 2:
        summary = [*missions[:2], f"+{len(missions) - 2} missions", *others]
    else:
        summary = [*missions, *others]
    return summary


def _short(reason: str) -> str:
    return reason.replace("mission: ", "").replace("formable: ", "form ")
