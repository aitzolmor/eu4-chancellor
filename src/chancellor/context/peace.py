"""What a peace can demand, and what it costs in war score (D-064).

Each demand in a peace deal costs war score; a deal can spend up to the war score the
side has (and never more than 100). The costs here are the ones the game's peace screen
showed on the user's 1.37 campaign, which differ from the wiki (written for 1.24):

* **A province** costs 0.8 × its development: 25 development, 20.0%. No extra per
  province, for the capital, buildings, trade or for not being occupied: Poznan, Barlad,
  Varsovia and fifteen more Polish and Lithuanian provinces all matched to the decimal.
* **Releasing a subject** of the enemy costs 0.4 × what its provinces would cost, up to
  100 (``MAX_PEACE_COST_CANCEL_SUBJECT``): Lithuania, 393 development, costs 100.
* **Fixed treaties** from ``common/defines.lua``: war reparations 10, annul treaties 10,
  concede defeat 10 (alone), gold 5 per loan's worth (up to five).

A demand on a province you hold no claim or core on adds more aggressive expansion
(the peace screen showed about 1.3 per development for Poland's and 2 for its ally's,
and none on claims); the AE a conquest adds is estimated by ``check_war``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.context.wars import WarReport, development

PROVINCE_COST = 0.8  # war score per development, as the 1.37 peace screen shows it
RELEASE_SUBJECT = 0.4  # share of the subject's province costs
MAX_RELEASE_SUBJECT = 100.0  # MAX_PEACE_COST_CANCEL_SUBJECT
MAX_DEAL = 100.0  # MAX_WARSCORE
FIXED = (
    ("War reparations (10% of their income for 10 years)", 10.0),
    ("Annul their treaties with a country", 10.0),
    ("Gold: one loan's worth (up to five)", 5.0),
    ("Concede defeat (a white peace with prestige; alone)", 10.0),
)
_NON_SOVEREIGN = {"tributary_state"}


@dataclass
class ProvinceDemand:
    """One province that can be demanded.

    Attributes:
        province: Province id.
        name: Its name as the map shows it.
        owner: Its owner's tag.
        development: Its development.
        cost: War score it costs.
        occupied: Whether the winning side controls it.
        claimant: Who on the winning side has a claim or core on it (the country or
            one of its subjects; no AE then), or ``""``.
        war_goal: Whether it is the war goal.
    """

    province: int
    name: str
    owner: str
    development: float
    cost: float
    occupied: bool
    claimant: str
    war_goal: bool = False

    @property
    def justified(self) -> bool:
        """Whether a claim or core makes the demand free of aggressive expansion."""
        return bool(self.claimant)


@dataclass
class PeaceOptions:
    """What the winning side can demand in one war.

    Attributes:
        war: The war.
        score: The war score against the enemy leader, if known.
        source: Where the score comes from.
        provinces: Provinces of the enemy side that can be demanded.
        releases: Enemy subjects that can be released: ``(subject, overlord, cost)``.
        development: Enemy country → ``(own development, with its non-tributary subjects)``.
    """

    war: WarReport
    score: float | None
    source: str
    provinces: list[ProvinceDemand] = field(default_factory=list)
    releases: list[tuple[str, str, float]] = field(default_factory=list)
    development: dict[str, tuple[float, float]] = field(default_factory=dict)


def province_cost(development_points: float) -> float:
    """War score a province costs in a peace: 0.8 × development."""
    return round(PROVINCE_COST * development_points, 1)


def peace_options(
    campaign: Campaign, war: WarReport, tag: str | None = None, live: Any = None, wars: int = 1
) -> PeaceOptions:
    """What ``tag``'s side (the player's by default) can demand in a war.

    Args:
        campaign: The loaded save.
        war: The war, from :func:`chancellor.context.wars.war_reports`.
        tag: The country demanding.
        live: The probe mod's war score (``live.war_score.LiveWarScore``), if any.
        wars: How many wars the country is in (the exact live score needs one).
    """
    tag = tag or campaign.player
    score, source = None, "unknown"
    leader = war.their_side[0] if war.their_side else None
    reading = live.against(campaign, leader, wars) if live is not None and leader else None
    if reading is not None:
        score, how = reading
        source = f"the probe mod on {live.date}, {how}"
    elif war.quarterly_score is not None:
        score, source = war.quarterly_score, "the game's last quarterly check"
    if score is not None and war.side == "defender":
        score = -score  # the save keeps it from the attacker's side (an assumption)
    controllers = campaign.province_controllers
    ours = set(war.our_side)
    # Claims and cores of the country and its subjects count: the peace screen showed no
    # AE for Barlad, a claim of Austria's vassal Hungary.
    rightful = [tag] + [
        str(s)
        for s in as_list((campaign.country(tag) or {}).get("subjects"))
        if campaign.subject_type(tag, str(s)) not in _NON_SOVEREIGN
    ]
    goal = war.goal[1] if war.goal else None
    options = PeaceOptions(war, score, source)
    for enemy in war.their_side:
        country = campaign.country(enemy) or {}
        own = float(country.get("raw_development") or 0)
        subjects = [
            str(s)
            for s in as_list(country.get("subjects"))
            if campaign.subject_type(enemy, str(s)) not in _NON_SOVEREIGN
        ]
        with_subjects = own + sum(
            float((campaign.country(s) or {}).get("raw_development") or 0) for s in subjects
        )
        options.development[enemy] = (own, with_subjects)
        for province in as_list(country.get("owned_provinces")):
            if not isinstance(province, int):
                continue
            data = campaign.province(province) or {}
            occupied = controllers.get(province) in ours
            rights = [*as_list(data.get("cores")), *as_list(data.get("claims"))]
            claimant = next((t for t in rightful if t in rights), "")
            if not (occupied or claimant or province == goal):
                continue
            dev = development(campaign, province)
            options.provinces.append(
                ProvinceDemand(
                    province,
                    str(data.get("name") or campaign.loc.province(province)),
                    enemy,
                    dev,
                    province_cost(dev),
                    occupied,
                    claimant,
                    province == goal,
                )
            )
        for subject in subjects:
            dev = float((campaign.country(subject) or {}).get("raw_development") or 0)
            cost = min(MAX_RELEASE_SUBJECT, round(RELEASE_SUBJECT * province_cost(dev), 1))
            options.releases.append((subject, enemy, cost))
    options.provinces.sort(key=lambda p: (not p.war_goal, not p.justified, -p.development))
    return options


def render_peace(campaign: Campaign, all_options: list[PeaceOptions], listed: int = 12) -> str:
    """Markdown for ``get_peace_options``."""
    lines = [f"# Peace terms: {campaign.label(campaign.player)}, {campaign.date}", ""]
    if not all_options:
        return "\n".join([*lines, "At peace."]) + "\n"
    for options in all_options:
        war = options.war
        leader = war.their_side[0] if war.their_side else "?"
        budget = (
            f"{options.score:+.0f} against {campaign.name(leader)} ({options.source})"
            if options.score is not None
            else "unknown"
        )
        lines += [
            f"## {war.name}",
            "",
            f"- War score: {budget}. A deal spends up to it (100 at most).",
        ]
        for enemy, (own, total) in options.development.items():
            if total > own:
                lines.append(
                    f"- {campaign.label(enemy)}: development {own:.0f}, {total:.0f} with its "
                    "subjects"
                )
            else:
                lines.append(f"- {campaign.label(enemy)}: development {own:.0f}")
        if options.releases:
            lines += ["", "Release a subject (it leaves its overlord and becomes independent):"]
            for subject, overlord, cost in options.releases:
                fits = _fits(cost, options.score)
                lines.append(
                    f"- {campaign.label(subject)} from {campaign.name(overlord)}: {cost:.1f}{fits}"
                )
        if options.provinces:
            occupied = [p for p in options.provinces if p.occupied]
            lines += [
                "",
                f"Provinces ({len(options.provinces)}; {len(occupied)} occupied, "
                f"{sum(p.cost for p in occupied):.1f} for all the occupied ones):",
                "",
                "| Province | Owner | Dev | War score | Occupied | Claim or core |",
                "| --- | --- | ---: | ---: | --- | --- |",
            ]
            for p in options.provinces[:listed]:
                name = p.name + (" (war goal)" if p.war_goal else "")
                lines.append(
                    f"| {name} | {campaign.name(p.owner)} | {p.development:.0f} | {p.cost:.1f} "
                    f"| {'yes' if p.occupied else 'no'} | {_claimant(campaign, p.claimant)} |"
                )
            if len(options.provinces) > listed:
                lines.append(f"\n{len(options.provinces) - listed} more provinces not shown.")
        lines += ["", "Treaties: " + "; ".join(f"{name} {cost:.0f}" for name, cost in FIXED) + "."]
        lines.append("")
    lines.append(
        "_Costs as the 1.37 peace screen shows them: a province 0.8 × its development; a "
        "subject's release 0.4 × its provinces, at most 100. A demand without a claim or core "
        "adds more aggressive expansion, and the AI refuses to give up forts it still holds. "
        "A separate peace with an enemy's ally uses that ally's own score (the game's peace "
        "screen). Check the total on the peace screen before sending._"
    )
    return "\n".join(lines) + "\n"


def _claimant(campaign: Campaign, claimant: str) -> str:
    if not claimant:
        return "no"
    return "yours" if claimant == campaign.player else campaign.name(claimant)


def _fits(cost: float, score: float | None) -> str:
    if score is None:
        return ""
    return " (fits)" if cost <= max(min(score, MAX_DEAL), 0) else " (more than the war score)"
