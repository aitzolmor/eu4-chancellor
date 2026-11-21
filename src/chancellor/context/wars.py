"""A country's wars in detail: when they began, what is occupied, the battles (D-050).

The save's ``active_war`` blocks hold more than the briefing used:

* ``history``: dated entries, the first one the declaration (``add_attacker`` /
  ``add_defender``), then joins, leaves and ``battle`` blocks. The war began on the
  first date. (``action`` is *not* the start: it was the save's own date in a war that
  began three years earlier.)
* ``battle``: its name, ``result`` (whether the battle's attacker won), and per side the
  ``country``, its units and ``losses``.
* ``participants``: each country's ``value``, its participation score, and its
  ``losses``: 21 numbers, read as seven unit types (infantry, cavalry, artillery,
  heavy ships, light ships, galleys, transports) times three (lost in battle, to
  attrition, captured). These are complete, unlike the battles in ``history``, where
  the game keeps only some (the user's 1532 war: 19, none of Austria's land battles).
* ``last_warscore_quarter``: a war score the game records every quarter
  (``next_quarter_update``). Which score exactly is not confirmed yet; it is reported as
  such, beside the occupations, which are certain.

Occupations come from the provinces: owned by one side, controlled by the other
(:attr:`Campaign.province_controllers`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.save.parser import get_all


@dataclass
class Battle:
    """One battle, from the player's side.

    Attributes:
        date: When it was fought.
        name: Where.
        won: Whether the player's side won.
        ours: Our side's country in it.
        theirs: The other side's country.
        our_losses: Men (or ships) our side lost.
        their_losses: Men (or ships) the other side lost.
        naval: Whether it was at sea.
    """

    date: str
    name: str
    won: bool
    ours: str
    theirs: str
    our_losses: int
    their_losses: int
    naval: bool


@dataclass
class Losses:
    """What a country has lost in a war.

    Attributes:
        battle: Men lost in battle.
        attrition: Men lost to attrition.
        ships: Ships lost (in battle, to attrition or captured).
    """

    battle: int = 0
    attrition: int = 0
    ships: int = 0

    def add(self, other: Losses) -> Losses:
        """The sum of two."""
        return Losses(
            self.battle + other.battle, self.attrition + other.attrition, self.ships + other.ships
        )


def losses_from(members: list[Any]) -> Losses:
    """Losses from a participant's 21 numbers (unit types × battle, attrition, captured)."""
    numbers = [int(v) if isinstance(v, int | float) else 0 for v in members] + [0] * 21
    land = numbers[:9]  # infantry, cavalry, artillery
    return Losses(
        battle=sum(land[0::3]),
        attrition=sum(land[1::3]),
        ships=sum(numbers[9:21]),
    )


@dataclass
class WarReport:
    """One war of a country.

    Attributes:
        name: The war's name.
        started: The date of its first history entry (the declaration).
        side: ``attacker`` or ``defender``.
        our_side: Countries on the country's side (including those who left).
        their_side: Countries on the other side (including those who left).
        goal: ``(casus belli, province id)`` of the war goal, if any.
        occupied_by_us: Enemy provinces our side controls, as ``(id, owner)``.
        occupied_by_them: Our side's provinces they control, as ``(id, owner)``.
        battles: Every battle, oldest first.
        participation: Country → its participation score.
        losses: Country → its :class:`Losses` in the war.
        quarterly_score: The war score the game recorded at its last quarterly check.
        next_check: When the game checks it again.
    """

    name: str
    started: str
    side: str
    our_side: list[str]
    their_side: list[str]
    goal: tuple[str, int] | None
    occupied_by_us: list[tuple[int, str]] = field(default_factory=list)
    occupied_by_them: list[tuple[int, str]] = field(default_factory=list)
    battles: list[Battle] = field(default_factory=list)
    participation: dict[str, float] = field(default_factory=dict)
    losses: dict[str, Losses] = field(default_factory=dict)
    quarterly_score: float | None = None
    next_check: str | None = None


def war_reports(campaign: Campaign, tag: str | None = None) -> list[WarReport]:
    """The country's wars (the player's by default), with their details."""
    tag = tag or campaign.player
    owners = campaign.province_owners
    controllers = campaign.province_controllers
    reports = []
    for war in campaign.wars_of(tag):
        attackers = _tags(war, "persistent_attackers") or _tags(war, "attackers")
        defenders = _tags(war, "persistent_defenders") or _tags(war, "defenders")
        side = "attacker" if tag in attackers else "defender"
        ours, theirs = (attackers, defenders) if side == "attacker" else (defenders, attackers)
        goal_block = war.get("take_province")
        goal = None
        if isinstance(goal_block, dict) and isinstance(goal_block.get("province"), int):
            goal = (
                str(goal_block.get("casus_belli") or goal_block.get("type") or ""),
                goal_block["province"],
            )
        ours_set, theirs_set = set(ours), set(theirs)
        reports.append(
            WarReport(
                name=str(war.get("name", "?")).strip(),
                started=war_start(war) or str(war.get("action", "?")),
                side=side,
                our_side=ours,
                their_side=theirs,
                goal=goal,
                occupied_by_us=sorted(
                    (p, o)
                    for p, o in owners.items()
                    if o in theirs_set and controllers.get(p) in ours_set
                ),
                occupied_by_them=sorted(
                    (p, o)
                    for p, o in owners.items()
                    if o in ours_set and controllers.get(p) in theirs_set
                ),
                battles=_battles(war, ours_set),
                participation={
                    str(p["tag"]): float(p.get("value") or 0.0)
                    for p in get_all(war, "participants")
                    if isinstance(p, dict) and p.get("tag")
                },
                losses={
                    str(p["tag"]): losses_from(as_list((p.get("losses") or {}).get("members")))
                    for p in get_all(war, "participants")
                    if isinstance(p, dict) and p.get("tag")
                },
                quarterly_score=_number(war.get("last_warscore_quarter")),
                next_check=str(war["next_quarter_update"])
                if war.get("next_quarter_update")
                else None,
            )
        )
    return reports


def war_start(war: dict[str, Any]) -> str | None:
    """The date of a war's first history entry: when it was declared."""
    history = war.get("history")
    if not isinstance(history, dict):
        return None
    dates = [str(d) for d in history if str(d)[:1].isdigit()]
    return min(dates, key=_date) if dates else None


def development(campaign: Campaign, province: int) -> float:
    """A province's development (base tax, production and manpower)."""
    data = campaign.province(province) or {}
    return sum(float(data.get(k) or 0) for k in ("base_tax", "base_production", "base_manpower"))


def live_score(war: WarReport, live: Any, wars: int, campaign: Campaign) -> str | None:
    """The live war score against a war's enemy leader, as a phrase (D-063), or ``None``.

    Args:
        war: The war.
        live: The probe mod's reading (``live.war_score.LiveWarScore``), or ``None``.
        wars: How many wars the player is in.
        campaign: The loaded save.
    """
    if live is None or not war.their_side:
        return None
    leader = war.their_side[0]
    found = live.against(campaign, leader, wars)
    if found is None:
        return None
    score, how = found
    return f"{score:+.0f} against {campaign.name(leader)} ({how}, the probe mod on {live.date})"


def render_wars(
    campaign: Campaign, reports: list[WarReport], listed: int = 15, live: Any = None
) -> str:
    """Markdown for ``get_wars``.

    Args:
        campaign: The loaded save.
        reports: The wars.
        listed: Occupied provinces named per owner.
        live: The probe mod's war score (``live.war_score.LiveWarScore``), when it runs.
    """
    lines = [f"# Wars of {campaign.label(campaign.player)}", ""]
    if not reports:
        lines.append("At peace.")
        return "\n".join(lines) + "\n"
    for war in reports:
        lines += [f"## {war.name}", ""]
        lines.append(f"- Began {war.started}; {campaign.name(campaign.player)} is the {war.side}.")
        if war.goal:
            cb, province = war.goal
            holder = campaign.province_controllers.get(province)
            lines.append(
                f"- War goal: {campaign.text(cb)}, {campaign.loc.province(province)}"
                + (f" (controlled by {campaign.name(holder)})" if holder else "")
                + "."
            )
        lines.append(f"- Our side: {_names(campaign, war.our_side)}.")
        lines.append(f"- Their side: {_names(campaign, war.their_side)}.")
        now = live_score(war, live, len(reports), campaign)
        if now:
            lines.append(f"- War score: {now}.")
        if war.quarterly_score is not None:
            lines.append(
                f"- War score recorded by the game at its last quarterly check: "
                f"{war.quarterly_score:g}"
                + (f" (next check {war.next_check})" if war.next_check else "")
                + (
                    "."
                    if now
                    else ". The live score is on the game's peace screen, or monthly from "
                    "the probe mod."
                )
            )
        lines += _occupation_lines(campaign, war, listed)
        lines += _battle_lines(campaign, war)
        top = sorted(war.participation.items(), key=lambda item: -item[1])[:6]
        if top:
            lines.append(
                "- Participation: "
                + ", ".join(f"{campaign.name(t)} {v:.0f}" for t, v in top if v > 0)
                + "."
            )
        lines.append("")
    lines.append(
        "_From the save: occupations are provinces one side owns and the other controls; "
        "battles come from the war's history. The war score is against the enemy war "
        "leader (a separate peace with one of its allies has its own score, on the game's "
        "peace screen). What a peace can demand, and its cost: get_peace_options._"
    )
    return "\n".join(lines) + "\n"


def war_line(campaign: Campaign, war: WarReport) -> str:
    """One briefing line on a war's state."""
    ours, theirs = side_losses(war, war.our_side), side_losses(war, war.their_side)
    parts = [
        f"began {war.started}",
        f"we occupy {len(war.occupied_by_us)} of their provinces",
        f"they occupy {len(war.occupied_by_them)} of ours",
        f"men lost: ours {ours.battle + ours.attrition:,}, theirs "
        f"{theirs.battle + theirs.attrition:,}",
    ]
    if war.quarterly_score is not None:
        parts.append(f"war score at the game's last quarterly check {war.quarterly_score:g}")
    return "; ".join(parts) + " (details: get_wars)"


def _occupation_lines(campaign: Campaign, war: WarReport, listed: int) -> list[str]:
    lines = []
    for label, occupied in (
        ("We occupy", war.occupied_by_us),
        ("They occupy", war.occupied_by_them),
    ):
        if not occupied:
            lines.append(f"- {label} nothing.")
            continue
        by_owner: dict[str, list[int]] = {}
        for province, owner in occupied:
            by_owner.setdefault(owner, []).append(province)
        total = sum(development(campaign, p) for p, _ in occupied)
        noun = "province" if len(occupied) == 1 else "provinces"
        lines.append(f"- {label} {len(occupied)} {noun} ({total:.0f} development):")
        for owner, provinces in sorted(by_owner.items(), key=lambda item: -len(item[1])):
            ranked = sorted(provinces, key=lambda p: -development(campaign, p))
            shown = ", ".join(
                f"{campaign.loc.province(p)} {development(campaign, p):.0f}"
                for p in ranked[:listed]
            )
            more = f" and {len(ranked) - listed} more" if len(ranked) > listed else ""
            lines.append(f"  - of {campaign.name(owner)} ({len(provinces)}): {shown}{more}")
    return lines


def side_losses(war: WarReport, side: list[str]) -> Losses:
    """The losses of one side, summed over its countries."""
    total = Losses()
    for tag in side:
        total = total.add(war.losses.get(tag, Losses()))
    return total


def _battle_lines(campaign: Campaign, war: WarReport) -> list[str]:
    ours, theirs = side_losses(war, war.our_side), side_losses(war, war.their_side)
    lines = [
        f"- Losses so far: our side {ours.battle:,} men in battle and {ours.attrition:,} to "
        f"attrition, {ours.ships} ships; their side {theirs.battle:,} in battle and "
        f"{theirs.attrition:,} to attrition, {theirs.ships} ships.",
    ]
    # The player, and the enemy that has fought most (not always the war's leader).
    enemies = sorted(war.their_side, key=lambda t: -war.participation.get(t, 0.0))
    main = [t for t in (campaign.player, *enemies[:1]) if t in war.losses]
    for tag in main:
        lost = war.losses[tag]
        lines.append(
            f"  - {campaign.name(tag)}: {lost.battle:,} in battle, {lost.attrition:,} to "
            f"attrition, {lost.ships} ships"
        )
    if not war.battles:
        return lines
    lines.append(
        f"- Some battles the save recorded ({len(war.battles)}; the game keeps only some, "
        "so they are not a tally):"
    )
    for battle in war.battles[-4:]:
        outcome = "won" if battle.won else "lost"
        kind = "naval " if battle.naval else ""
        lines.append(
            f"  - {battle.date} {kind}battle of {battle.name}: {outcome} "
            f"({campaign.name(battle.ours)} lost {battle.our_losses:,}, "
            f"{campaign.name(battle.theirs)} {battle.their_losses:,})"
        )
    return lines


_NAVAL = ("heavy_ship", "light_ship", "galley", "transport")


def _battles(war: dict[str, Any], ours: set[str]) -> list[Battle]:
    history = war.get("history")
    if not isinstance(history, dict):
        return []
    battles = []
    for date in sorted((str(d) for d in history if str(d)[:1].isdigit()), key=_date):
        for entry in get_all(history, date):
            for event in as_list(entry):
                if not isinstance(event, dict):
                    continue
                for battle in get_all(event, "battle"):
                    if not isinstance(battle, dict):
                        continue
                    attacker = battle.get("attacker") or {}
                    defender = battle.get("defender") or {}
                    we_attacked = attacker.get("country") in ours
                    us, them = (attacker, defender) if we_attacked else (defender, attacker)
                    attacker_won = battle.get("result") is True
                    battles.append(
                        Battle(
                            date=date,
                            name=str(battle.get("name", "?")),
                            won=attacker_won == we_attacked,
                            ours=str(us.get("country", "?")),
                            theirs=str(them.get("country", "?")),
                            our_losses=int(_number(us.get("losses")) or 0),
                            their_losses=int(_number(them.get("losses")) or 0),
                            naval=any(k in attacker or k in defender for k in _NAVAL),
                        )
                    )
    return battles


def _tags(war: dict[str, Any], key: str) -> list[str]:
    return [str(t) for t in as_list(war.get(key)) if isinstance(t, str)]


def _names(campaign: Campaign, tags: list[str]) -> str:
    return ", ".join(campaign.name(t) for t in tags) or "nobody"


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _date(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return (0,)
