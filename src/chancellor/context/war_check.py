"""War feasibility check: who would fight on each side, and how strong each side is.

Answers "should I declare war on X?" with data the save actually contains: the target's
allies, subjects, overlord, guarantors, the Holy Roman Emperor and any coalition against
the attacker, plus the attacker's own allies and subjects. Each participant gets a
likelihood of joining, because EU4's AI can refuse calls to arms.

The result is structured (:class:`WarCheck`) so the chat agent can use it as a tool;
:func:`render_war_check` turns it into Markdown for the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from chancellor.context.campaign import Campaign, Grievance, Truce, as_list, count_regiments
from chancellor.save.parser import get_all

Likelihood = Literal["certain", "likely", "possible"]
_LIKELIHOOD_ORDER = {"certain": 0, "likely": 1, "possible": 2}

RiskLevel = Literal["low", "medium", "high"]

# common/defines.lua (1.37): AE_COALITION_THRESHOLD = -50, the AE opinion at which a
# country can join a coalition. AE decays by 2 a year at base (see summarizer).
COALITION_AE = 50.0
AE_YEARLY_DECAY = 2.0
# A conquest usually adds tens of AE to the target and its neighbours, so countries
# this far below the threshold can cross it in a single war.
NEAR_COALITION_AE = 35.0
# Neighbours at the threshold that make the risk high on their own.
_HIGH_RISK_NEIGHBOURS = 3

# Subject types with `joins_overlords_wars = no` in common/subject_types (game 1.37).
# Every other type inherits `joins_overlords_wars = yes` from the default.
_NON_JOINING_SUBJECTS = {
    "tributary_state",
    "nahuatl_tributary",
    "eyalet",
    "trade_protectorate",
    "cultural_sphere_of_influence_subject",
}


@dataclass
class Participant:
    """A country that would (or might) fight in the war.

    Attributes:
        tag: Country tag.
        name: Display name.
        roles: Why it is involved, e.g. ``["ally"]`` or ``["guarantor", "coalition member"]``.
        likelihood: How likely it is to actually join.
        regiments: Land regiments currently raised.
        manpower: Available manpower, in thousands.
        max_manpower: Maximum manpower, in thousands.
        development: Total development.
        mil_tech: Military technology level.
        current_wars: Names of wars the country is already fighting.
    """

    tag: str
    name: str
    roles: list[str]
    likelihood: Likelihood
    regiments: int
    manpower: float
    max_manpower: float
    development: float
    mil_tech: int | None
    current_wars: list[str] = field(default_factory=list)


@dataclass
class SideTotals:
    """Aggregated strength of one side for a given set of likelihoods."""

    regiments: int
    manpower: float
    countries: int


@dataclass
class CoalitionRisk:
    """How close a war on the target brings the attacker to a coalition.

    Conquering land adds aggressive expansion (AE) mostly to the target and the countries
    around it, so the risk is read from the AE they already hold against the attacker.
    The attacker's own subjects and allies are left out: they cannot join a coalition
    against it. The AE a peace deal would add is not estimated.

    Attributes:
        level: ``"high"`` when the target is already at the coalition threshold or
            several neighbours are; ``"medium"`` when the target is close to it or one
            neighbour is at it; ``"low"`` otherwise.
        target_ae: AE the target holds against the attacker (0 if none).
        neighbours: The target's neighbours holding AE against the attacker, highest
            first.
        at_threshold: Countries in the world at or above the threshold (50).
        in_coalition: Whether a coalition against the attacker already exists.
    """

    level: RiskLevel
    target_ae: float
    neighbours: list[Grievance]
    at_threshold: int
    in_coalition: bool

    @property
    def neighbours_at_threshold(self) -> list[Grievance]:
        """Neighbours of the target that can already join a coalition."""
        return [g for g in self.neighbours if g.value >= COALITION_AE]

    @property
    def neighbours_near_threshold(self) -> list[Grievance]:
        """Neighbours a single war could push over the threshold."""
        return [g for g in self.neighbours if NEAR_COALITION_AE <= g.value < COALITION_AE]

    @property
    def years_below_threshold(self) -> int | None:
        """Years until the target's AE decays below the threshold at the base rate."""
        if self.target_ae < COALITION_AE:
            return None
        return int((self.target_ae - COALITION_AE) // AE_YEARLY_DECAY) + 1


@dataclass
class WarCheck:
    """Expected participants and strength of a hypothetical war.

    Attributes:
        attacker: Tag of the country declaring war.
        target: Tag of the country being attacked.
        date: Save date.
        attackers: Attacker and countries that would join it.
        defenders: Target and countries that would defend it.
        neutral: Countries tied to both sides, unlikely to join either.
        notes: Extra facts worth considering (ongoing wars, HRE, coalitions, truces).
        truce: The truce between attacker and target, if any: declaring war breaks it.
        allied_defenders: The attacker's allies that are bound to defend the target (its
            overlord, subjects or coalition), so the war would turn them into enemies.
        coalition_risk: How close conquering from the target brings a coalition.
    """

    attacker: str
    target: str
    date: str
    attackers: list[Participant]
    defenders: list[Participant]
    neutral: list[Participant]
    notes: list[str]
    truce: Truce | None = None
    allied_defenders: list[str] = field(default_factory=list)
    coalition_risk: CoalitionRisk | None = None

    def totals(self, side: Literal["attackers", "defenders"], worst_case: bool) -> SideTotals:
        """Sum the strength of one side.

        Args:
            side: ``"attackers"`` or ``"defenders"``.
            worst_case: Include ``possible`` participants (otherwise only certain/likely).
        """
        members = [
            p for p in getattr(self, side) if worst_case or p.likelihood in ("certain", "likely")
        ]
        return SideTotals(
            regiments=sum(p.regiments for p in members),
            manpower=sum(p.manpower for p in members),
            countries=len(members),
        )


def check_war(campaign: Campaign, target: str, attacker: str | None = None) -> WarCheck:
    """Work out who would fight if ``attacker`` declared war on ``target``.

    Args:
        campaign: The loaded save.
        target: Tag of the country to attack.
        attacker: Tag of the attacking country. Defaults to the player.

    Returns:
        The expected participants and notes.

    Raises:
        KeyError: If either country is not in the save.
        ValueError: If attacker and target are the same country.
    """
    attacker = attacker or campaign.player
    if attacker == target:
        raise ValueError("A country cannot declare war on itself")
    att = campaign.country(attacker)
    tgt = campaign.country(target)
    if att is None or tgt is None:
        raise KeyError(f"{attacker if att is None else target} is not in the save")

    defenders: dict[str, tuple[list[str], Likelihood]] = {}
    attackers: dict[str, tuple[list[str], Likelihood]] = {}

    def add(side: dict[str, tuple[list[str], Likelihood]], tag: str, role: str, how: Likelihood):
        # The two belligerents can only ever be on their own side.
        if (side is defenders and tag == attacker) or (side is attackers and tag == target):
            return
        if tag in side:
            roles, current = side[tag]
            roles.append(role)
            if _LIKELIHOOD_ORDER[how] < _LIKELIHOOD_ORDER[current]:
                side[tag] = (roles, how)
        else:
            side[tag] = ([role], how)

    # Defending side.
    add(defenders, target, "target", "certain")
    overlord = tgt.get("overlord")
    if isinstance(overlord, str) and overlord != attacker:
        add(defenders, overlord, "overlord", "certain")
    for subject in as_list(tgt.get("subjects")):
        kind = campaign.subject_type(target, subject) or "subject"
        add(defenders, subject, f"subject ({campaign.text(kind)})", _subject_likelihood(kind))
    if target in _coalition(att):
        for member in _coalition(att):
            add(defenders, member, "coalition member", "certain")
    for ally in as_list(tgt.get("allies")):
        add(defenders, ally, "ally", "likely")
    for guarantor in campaign.guarantors_of(target):
        add(defenders, guarantor, "guarantor", "possible")
    emperor = campaign.emperor
    hre_target = campaign.in_hre(target)
    if (
        emperor
        and emperor not in (target, attacker)
        and hre_target
        and not campaign.in_hre(attacker)
    ):
        add(defenders, emperor, "Holy Roman Emperor", "possible")

    # Attacking side.
    add(attackers, attacker, "attacker", "certain")
    for subject in as_list(att.get("subjects")):
        if subject == target:
            continue
        kind = campaign.subject_type(attacker, subject) or "subject"
        add(attackers, subject, f"subject ({campaign.text(kind)})", _subject_likelihood(kind))
    for ally in as_list(att.get("allies")):
        add(attackers, ally, "ally", "likely")

    # Countries on both lists will not fight their own ally; treat them as neutral,
    # unless they are bound to one side (the target itself, subjects, coalition).
    neutral: dict[str, tuple[list[str], Likelihood]] = {}
    for tag in list(attackers):
        if tag in defenders and tag not in (attacker, target):
            att_roles, _ = attackers[tag]
            def_roles, def_how = defenders[tag]
            if def_how == "certain":
                del attackers[tag]
            elif att_roles[0].startswith("subject"):
                del defenders[tag]
            else:
                neutral[tag] = ([*att_roles, *def_roles], "possible")
                del attackers[tag]
                del defenders[tag]

    notes = _notes(campaign, attacker, target, hre_target)

    def build(side: dict[str, tuple[list[str], Likelihood]]) -> list[Participant]:
        people = [
            _participant(campaign, tag, roles, how)
            for tag, (roles, how) in side.items()
            if campaign.exists(tag)
        ]
        return sorted(people, key=lambda p: (_LIKELIHOOD_ORDER[p.likelihood], -p.regiments))

    attacking, defending = build(attackers), build(defenders)
    allied = set(as_list(att.get("allies")))
    turned = [p for p in defending if p.tag in allied and p.tag != target]
    for person in turned:
        notes.append(
            f"{person.name} ({person.tag}) is allied with {campaign.name(attacker)} but would "
            f"defend {campaign.name(target)} ({', '.join(person.roles)}): this war turns an ally "
            "into an enemy and ends the alliance."
        )
    notes += _participant_truces(campaign, attacker, target, attacking, defending)
    return WarCheck(
        attacker=attacker,
        target=target,
        date=campaign.date,
        attackers=attacking,
        defenders=defending,
        neutral=build(neutral),
        notes=notes,
        truce=campaign.truce(attacker, target),
        allied_defenders=[p.tag for p in turned],
        coalition_risk=coalition_risk(campaign, attacker, target),
    )


def coalition_risk(campaign: Campaign, attacker: str, target: str) -> CoalitionRisk:
    """Read the coalition risk of taking land from ``target``; see :class:`CoalitionRisk`.

    Args:
        campaign: The loaded save.
        attacker: The country that would conquer.
        target: The country losing land.
    """
    att = campaign.country(attacker) or {}
    friends = {*as_list(att.get("subjects")), *as_list(att.get("allies")), attacker}
    grievances = {
        g.tag: g for g in campaign.aggressive_expansion_towards(attacker) if g.tag not in friends
    }
    target_ae = grievances[target].value if target in grievances else 0.0
    around = {str(t) for t in as_list((campaign.country(target) or {}).get("neighbours"))}
    neighbours = sorted(
        (g for tag, g in grievances.items() if tag in around and tag != target),
        key=lambda g: -g.value,
    )
    at_threshold = sum(1 for g in grievances.values() if g.value >= COALITION_AE)
    risk = CoalitionRisk(
        level="low",
        target_ae=target_ae,
        neighbours=neighbours,
        at_threshold=at_threshold,
        in_coalition=bool(_coalition(att)),
    )
    hot = len(risk.neighbours_at_threshold)
    if target_ae >= COALITION_AE or hot >= _HIGH_RISK_NEIGHBOURS:
        risk.level = "high"
    elif target_ae >= NEAR_COALITION_AE or hot or len(risk.neighbours_near_threshold) >= 2:
        risk.level = "medium"
    return risk


def describe_coalition_risk(campaign: Campaign, risk: CoalitionRisk, attacker: str) -> str:
    """One paragraph on the coalition risk, e.g. for the war check's Markdown."""
    target_part = (
        f"the target holds {int(risk.target_ae)} AE against {campaign.name(attacker)}"
        if risk.target_ae
        else "the target holds no AE against you"
    )
    if risk.years_below_threshold:
        target_part += (
            f" (at or above the coalition threshold of {COALITION_AE:.0f}; about "
            f"{risk.years_below_threshold} years to fall below it at the base decay)"
        )
    hot = risk.neighbours_at_threshold
    near = risk.neighbours_near_threshold
    parts = [f"**{risk.level.capitalize()}**: {target_part}"]
    if hot:
        parts.append(
            f"{len(hot)} of its neighbours {'is' if len(hot) == 1 else 'are'} already at "
            f"{COALITION_AE:.0f}+ ({_grievance_list(campaign, hot)})"
        )
    if near:
        parts.append(
            f"{len(near)} {'more ' if hot else ''}"
            f"{'neighbour is' if len(near) == 1 else 'neighbours are'} at "
            f"{NEAR_COALITION_AE:.0f}-{COALITION_AE:.0f}, where one war can push "
            f"{'it' if len(near) == 1 else 'them'} over ({_grievance_list(campaign, near)})"
        )
    text = "; ".join(parts) + "."
    text += (
        f" Worldwide, {risk.at_threshold} countries that are not your allies or subjects "
        f"are at {COALITION_AE:.0f}+ AE"
    )
    exists = (
        "; a coalition against you already exists."
        if risk.in_coalition
        else (" and no coalition exists yet.")
    )
    return text + exists


def _grievance_list(campaign: Campaign, grievances: list[Grievance], limit: int = 6) -> str:
    shown = ", ".join(f"{campaign.name(g.tag)} {int(g.value)}" for g in grievances[:limit])
    return shown + (f" and {len(grievances) - limit} more" if len(grievances) > limit else "")


def render_war_check(campaign: Campaign, check: WarCheck) -> str:
    """Render a :class:`WarCheck` as Markdown."""
    lines = [
        f"# War check: {campaign.label(check.attacker)} vs {campaign.label(check.target)}, "
        f"{check.date}",
        "",
        "Who would fight if "
        f"{campaign.name(check.attacker)} declared war on {campaign.name(check.target)} today.",
        "",
    ]
    if check.truce:
        lines += [f"**{_truce_warning(campaign, check)}**", ""]
    lines += [
        "## Balance of forces",
        "",
        "| Side | Countries | Regiments | Manpower | Worst case regiments | Worst case manpower |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for side, label in (("attackers", "Attackers"), ("defenders", "Defenders")):
        expected = check.totals(side, worst_case=False)  # type: ignore[arg-type]
        worst = check.totals(side, worst_case=True)  # type: ignore[arg-type]
        lines.append(
            f"| {label} | {expected.countries} | {expected.regiments} "
            f"| {_k(expected.manpower)} | {worst.regiments} | {_k(worst.manpower)} |"
        )
    lines += [
        "",
        "Expected counts certain and likely participants; worst case adds possible ones.",
    ]
    if check.coalition_risk:
        lines += [
            "",
            "## Coalition risk",
            "",
            "Taking land adds aggressive expansion (AE), mostly to the target and its "
            "neighbours; at 50 they can join a coalition. The AE of the peace deal itself "
            "is not estimated.",
            "",
            describe_coalition_risk(campaign, check.coalition_risk, check.attacker),
        ]
    lines += [
        "",
        "## Defenders",
        "",
        *_table(check.defenders),
        "",
        "## Attackers",
        "",
        *_table(check.attackers),
    ]
    if check.neutral:
        lines += [
            "",
            "## Tied to both sides",
            "",
            "These countries have obligations to both sides and would most likely stay out.",
            "",
            *_table(check.neutral),
        ]
    if check.notes:
        lines += ["", "## Notes", "", *(f"- {note}" for note in check.notes)]
    lines += [
        "",
        "_Likelihoods are estimates. Allies can refuse a call to arms, and guarantors and the "
        "Emperor decide case by case. War score and the casus belli are not checked; truce "
        "end dates are estimates._",
    ]
    return "\n".join(lines) + "\n"


# --- helpers ---------------------------------------------------------------------------


def _coalition(country: dict) -> list[str]:
    """Coalition members against ``country``; saves repeat the key once per member."""
    members: list[str] = []
    for value in get_all(country, "coalition_against_us"):
        members.extend(as_list(value))
    return members


def _subject_likelihood(kind: str) -> Likelihood:
    return "possible" if kind in _NON_JOINING_SUBJECTS else "certain"


def _participant(
    campaign: Campaign, tag: str, roles: list[str], likelihood: Likelihood
) -> Participant:
    country = campaign.country(tag) or {}
    tech = country.get("technology") or {}
    return Participant(
        tag=tag,
        name=campaign.name(tag),
        roles=list(dict.fromkeys(roles)),
        likelihood=likelihood,
        regiments=count_regiments(country),
        manpower=float(country.get("manpower") or 0.0),
        max_manpower=float(country.get("max_manpower") or 0.0),
        development=float(country.get("raw_development") or 0.0),
        mil_tech=tech.get("mil_tech") if isinstance(tech, dict) else None,
        current_wars=[str(w.get("name", "?")).strip() for w in campaign.wars_of(tag)],
    )


def _notes(campaign: Campaign, attacker: str, target: str, hre_target: bool) -> list[str]:
    notes = []
    for tag in (target, attacker):
        for war in campaign.wars_of(tag):
            notes.append(
                f"{campaign.label(tag)} is already at war: {str(war.get('name', '?')).strip()}."
            )
    att = campaign.country(attacker) or {}
    if target in _coalition(att):
        size = len(_coalition(att))
        notes.append(
            f"{campaign.label(target)} belongs to a coalition of {size} countries against "
            f"{campaign.name(attacker)}; attacking any member brings in the whole coalition."
        )
    if hre_target:
        emperor = campaign.emperor
        if emperor == attacker:
            notes.append(
                f"{campaign.name(target)} is a member of the Holy Roman Empire and "
                f"{campaign.name(attacker)} is the Emperor: attacking a member hurts imperial "
                "authority."
            )
        elif campaign.in_hre(attacker):
            notes.append(
                "Both countries are inside the Holy Roman Empire: the Emperor is not called "
                "to defend members against other members."
            )
    if target in as_list(att.get("subjects")):
        notes.append(
            f"{campaign.label(target)} is a subject of {campaign.name(attacker)}: subjects "
            "cannot be attacked by their overlord."
        )
    if attacker in as_list((campaign.country(target) or {}).get("subjects")):
        notes.append(
            f"{campaign.name(attacker)} is a subject of {campaign.label(target)}: this would be "
            "an independence war."
        )
    if target in as_list(att.get("allies")):
        notes.append(f"{campaign.label(target)} is currently allied with the attacker.")
    return notes


def _truce_text(truce: Truce) -> str:
    """``since 1475.6.21 (war score 41), ends around 1484.7.28 (estimate)``."""
    parts = []
    if truce.last_war:
        score = f" (war score {truce.warscore})" if truce.warscore is not None else ""
        parts.append(f"since {truce.last_war}{score}")
    parts.append(
        f"ends around {truce.estimated_end} (estimate)" if truce.estimated_end else "end unknown"
    )
    return ", ".join(parts)


def _truce_warning(campaign: Campaign, check: WarCheck) -> str:
    assert check.truce is not None
    return (
        f"Truce: {campaign.name(check.attacker)} and {campaign.name(check.target)} are under a "
        f"truce {_truce_text(check.truce)}. Declaring war now means breaking it."
    )


def _participant_truces(
    campaign: Campaign,
    attacker: str,
    target: str,
    attackers: list[Participant],
    defenders: list[Participant],
) -> list[str]:
    """Notes on participants that have a truce with the leader of the other side."""
    notes = []
    for people, enemy in ((defenders, attacker), (attackers, target)):
        for person in people:
            if person.tag in (attacker, target):
                continue
            truce = campaign.truce(person.tag, enemy)
            if truce:
                notes.append(
                    f"{campaign.label(person.tag)} has a truce with {campaign.name(enemy)}: "
                    f"{_truce_text(truce)}."
                )
    return notes


def _table(people: list[Participant]) -> list[str]:
    rows = [
        "| Country | Role | Joins | Regiments | Manpower | Mil tech | Development | At war |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in people:
        rows.append(
            f"| {p.name} ({p.tag}) | {', '.join(p.roles)} | {p.likelihood} | {p.regiments} "
            f"| {_k(p.manpower)} / {_k(p.max_manpower)} | {p.mil_tech if p.mil_tech else '?'} "
            f"| {p.development:.0f} | {len(p.current_wars) or ''} |"
        )
    return rows


def _k(thousands: float) -> str:
    """Format manpower stored in thousands, e.g. ``33.3k``."""
    return f"{thousands:.1f}k"
