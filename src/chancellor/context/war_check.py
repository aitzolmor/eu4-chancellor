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

from chancellor.context.campaign import Campaign, as_list
from chancellor.save.parser import get_all

Likelihood = Literal["certain", "likely", "possible"]
_LIKELIHOOD_ORDER = {"certain": 0, "likely": 1, "possible": 2}

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
class WarCheck:
    """Expected participants and strength of a hypothetical war.

    Attributes:
        attacker: Tag of the country declaring war.
        target: Tag of the country being attacked.
        date: Save date.
        attackers: Attacker and countries that would join it.
        defenders: Target and countries that would defend it.
        neutral: Countries tied to both sides, unlikely to join either.
        notes: Extra facts worth considering (ongoing wars, HRE, coalitions).
    """

    attacker: str
    target: str
    date: str
    attackers: list[Participant]
    defenders: list[Participant]
    neutral: list[Participant]
    notes: list[str]

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

    return WarCheck(
        attacker=attacker,
        target=target,
        date=campaign.date,
        attackers=build(attackers),
        defenders=build(defenders),
        neutral=build(neutral),
        notes=notes,
    )


def render_war_check(campaign: Campaign, check: WarCheck) -> str:
    """Render a :class:`WarCheck` as Markdown."""
    lines = [
        f"# War check: {campaign.label(check.attacker)} vs {campaign.label(check.target)}, "
        f"{check.date}",
        "",
        "Who would fight if "
        f"{campaign.name(check.attacker)} declared war on {campaign.name(check.target)} today.",
        "",
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
        "Emperor decide case by case. Truces, war score and the casus belli are not checked._",
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
    armies = [a for a in get_all(country, "army") if isinstance(a, dict)]
    tech = country.get("technology") or {}
    return Participant(
        tag=tag,
        name=campaign.name(tag),
        roles=list(dict.fromkeys(roles)),
        likelihood=likelihood,
        regiments=sum(len(get_all(a, "regiment")) for a in armies),
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
