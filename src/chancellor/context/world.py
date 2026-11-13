"""World overview: great powers, the largest countries, alliance blocs and major wars.

Gives the assistant the big picture that every long-term plan depends on: who is strong,
who is allied with whom, and where the fighting is. The result is structured
(:class:`WorldOverview`) so the chat agent can use it as a tool;
:func:`render_world` turns it into Markdown for the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chancellor.context.campaign import Campaign, as_list
from chancellor.save.parser import LazyBlock, get_all

_PERSONAL_UNIONS = {"personal_union", "integrated_personal_union", "theodoro_personal_union"}
# Subject types that fight for their overlord (see war_check), used to build blocs.
_NON_JOINING_SUBJECTS = {
    "tributary_state",
    "nahuatl_tributary",
    "eyalet",
    "trade_protectorate",
    "cultural_sphere_of_influence_subject",
}


@dataclass
class CountryStats:
    """Size of one country."""

    tag: str
    name: str
    development: float
    regiments: int


@dataclass
class GreatPower:
    """A great power and its score."""

    rank: int
    tag: str
    name: str
    score: float
    development: float
    regiments: int
    allies: list[str]
    at_war: bool


@dataclass
class Bloc:
    """A major power's direct network: itself, its allies and their fighting subjects.

    Attributes:
        members: Tags; the leading power first, then by army size.
        regiments: Combined regiments.
        development: Combined development.
        great_powers: Members that are great powers.
        includes_player: Whether the player belongs to the bloc.
    """

    members: list[str]
    regiments: int
    development: float
    great_powers: list[str]
    includes_player: bool


@dataclass
class WarSummary:
    """An ongoing war with the strength of each side."""

    name: str
    attackers: list[str]
    defenders: list[str]
    attacker_regiments: int
    defender_regiments: int
    involves_player: bool


@dataclass
class WorldOverview:
    """The state of the world at the save date."""

    date: str
    player: str
    living_countries: int
    great_powers: list[GreatPower]
    by_development: list[CountryStats]
    by_army: list[CountryStats]
    player_development_rank: int | None
    player_army_rank: int | None
    blocs: list[Bloc]
    wars: list[WarSummary]
    personal_unions: list[tuple[str, str]]
    emperor: str | None
    electors: list[str] = field(default_factory=list)


def world_overview(campaign: Campaign, top: int = 10, max_blocs: int = 6) -> WorldOverview:
    """Summarise the world.

    Args:
        campaign: The loaded save.
        top: How many countries to list in each ranking.
        max_blocs: How many alliance blocs to list.

    Returns:
        The overview.
    """
    stats = campaign.quick_stats
    player = campaign.player

    def ranking(index: int) -> list[str]:
        return sorted(stats, key=lambda t: (-stats[t][index], t))

    by_dev = ranking(0)
    by_army = ranking(1)

    def as_stats(tags: list[str]) -> list[CountryStats]:
        return [CountryStats(t, campaign.name(t), stats[t][0], stats[t][1]) for t in tags]

    return WorldOverview(
        date=campaign.date,
        player=player,
        living_countries=len(stats),
        great_powers=_great_powers(campaign),
        by_development=as_stats(by_dev[:top]),
        by_army=as_stats(by_army[:top]),
        player_development_rank=by_dev.index(player) + 1 if player in stats else None,
        player_army_rank=by_army.index(player) + 1 if player in stats else None,
        blocs=_blocs(campaign, top)[:max_blocs],
        wars=_wars(campaign),
        personal_unions=[
            (str(link["first"]), str(link["second"]))
            for link in campaign.active_links("dependency")
            if link.get("subject_type") in _PERSONAL_UNIONS
            and link.get("first") in stats
            and link.get("second") in stats
        ],
        emperor=campaign.emperor,
        electors=campaign.electors,
    )


def render_world(campaign: Campaign, world: WorldOverview, max_wars: int = 8) -> str:
    """Render a :class:`WorldOverview` as Markdown."""
    label = campaign.label
    lines = [
        f"# World overview, {world.date}",
        "",
        f"{world.living_countries} countries exist. The user plays {label(world.player)}"
        + (
            f", ranked #{world.player_development_rank} by development and "
            f"#{world.player_army_rank} by army size."
            if world.player_development_rank
            else "."
        ),
        "",
        "## Great powers",
        "",
        "| Rank | Country | Score | Development | Regiments | Allies | At war |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for gp in world.great_powers:
        allies = ", ".join(campaign.name(t) for t in gp.allies) or "none"
        lines.append(
            f"| {gp.rank} | {label(gp.tag)}{_you(gp.tag, world)} | {gp.score:.0f} "
            f"| {gp.development:.0f} | {gp.regiments} | {allies} | {'yes' if gp.at_war else ''} |"
        )

    lines += ["", "## Largest countries", "", *_ranking_table(campaign, world)]

    lines += ["", "## Alliance networks of the major powers", ""]
    if world.blocs:
        lines += [
            "Each major power with its allies and the subjects that fight for them: roughly "
            "who joins when it goes to war.",
            "",
            "| Power | Network | Regiments | Development | Great powers in it |",
            "| --- | --- | --- | --- | --- |",
        ]
        for bloc in world.blocs:
            leader, rest = bloc.members[0], bloc.members[1:]
            shown = ", ".join(campaign.name(t) for t in rest[:6])
            if len(rest) > 6:
                shown += f" and {len(rest) - 6} more"
            gps = ", ".join(campaign.name(t) for t in bloc.great_powers) or "none"
            lines.append(
                f"| {label(leader)}{_you(leader, world)} | {shown} | {bloc.regiments} "
                f"| {bloc.development:.0f} | {gps} |"
            )
    else:
        lines.append("No alliances.")

    lines += ["", "## Major wars", ""]
    if world.wars:
        lines += [
            "| War | Attackers | Defenders | Regiments (att. vs def.) |",
            "| --- | --- | --- | --- |",
        ]
        for war in world.wars[:max_wars]:
            mark = " **(you are involved)**" if war.involves_player else ""
            lines.append(
                f"| {war.name}{mark} | {_side(campaign, war.attackers)} "
                f"| {_side(campaign, war.defenders)} "
                f"| {war.attacker_regiments} vs {war.defender_regiments} |"
            )
        if len(world.wars) > max_wars:
            lines += ["", f"{len(world.wars) - max_wars} smaller wars not shown."]
    else:
        lines.append("The world is at peace.")

    if world.personal_unions:
        unions = ", ".join(f"{label(o)} over {label(s)}" for o, s in world.personal_unions)
        lines += ["", "## Personal unions", "", unions]

    if world.emperor:
        lines += ["", "## Holy Roman Empire", "", f"- Emperor: {label(world.emperor)}"]
        if world.electors:
            lines.append(f"- Electors: {', '.join(label(t) for t in world.electors)}")

    return "\n".join(lines) + "\n"


# --- builders --------------------------------------------------------------------------


def _great_powers(campaign: Campaign) -> list[GreatPower]:
    block = campaign.gamestate.get("great_powers")
    data = block.parse() if isinstance(block, LazyBlock) else block
    entries = get_all(data, "original") if isinstance(data, dict) else []
    stats = campaign.quick_stats
    powers = []
    for entry in entries:
        if not isinstance(entry, dict) or "country" not in entry:
            continue
        tag = str(entry["country"])
        country = campaign.country(tag) or {}
        development, regiments = stats.get(tag, (0.0, 0))
        powers.append(
            GreatPower(
                rank=int(entry.get("rank", 0)),
                tag=tag,
                name=campaign.name(tag),
                score=float(entry.get("value", 0.0)),
                development=development,
                regiments=regiments,
                allies=[str(t) for t in as_list(country.get("allies"))],
                at_war=bool(campaign.wars_of(tag)),
            )
        )
    return sorted(powers, key=lambda gp: gp.rank)


def _blocs(campaign: Campaign, top: int) -> list[Bloc]:
    """Direct alliance networks of the major powers.

    Chaining alliances transitively merges rivals into one giant group, which says
    nothing about a real war. Instead, each major power (great powers plus the largest
    armies) gets its own network: itself, its fighting subjects, its allies and their
    fighting subjects. That is roughly who shows up when it goes to war.
    """
    stats = campaign.quick_stats
    allies: dict[str, set[str]] = {}
    for link in campaign.active_links("alliance"):
        a, b = link.get("first"), link.get("second")
        if a in stats and b in stats:
            allies.setdefault(a, set()).add(b)
            allies.setdefault(b, set()).add(a)
    subjects: dict[str, set[str]] = {}
    for link in campaign.active_links("dependency"):
        overlord, subject = link.get("first"), link.get("second")
        if (
            overlord in stats
            and subject in stats
            and link.get("subject_type") not in _NON_JOINING_SUBJECTS
        ):
            subjects.setdefault(overlord, set()).add(subject)

    great = [gp.tag for gp in _great_powers(campaign)]
    biggest_armies = sorted(stats, key=lambda t: (-stats[t][1], t))[:top]
    leaders = list(dict.fromkeys([campaign.player, *great, *biggest_armies]))
    overlords = {s: o for o, subs in subjects.items() for s in subs}

    blocs = []
    seen: set[frozenset[str]] = set()
    for leader in leaders:
        if leader not in stats or leader in overlords:  # subjects follow their overlord
            continue
        members = {leader} | subjects.get(leader, set())
        for ally in allies.get(leader, set()):
            members |= {ally} | subjects.get(ally, set())
        if len(members) < 2 or frozenset(members) in seen:
            continue
        seen.add(frozenset(members))
        ordered = [leader, *sorted(members - {leader}, key=lambda t: (-stats[t][1], t))]
        blocs.append(
            Bloc(
                members=ordered,
                regiments=sum(stats[t][1] for t in members),
                development=sum(stats[t][0] for t in members),
                great_powers=[t for t in ordered if t in great],
                includes_player=campaign.player in members,
            )
        )
    mine = [b for b in blocs if b.members[0] == campaign.player]
    others = sorted(
        (b for b in blocs if b.members[0] != campaign.player), key=lambda b: -b.regiments
    )
    return mine + others


def _wars(campaign: Campaign) -> list[WarSummary]:
    stats = campaign.quick_stats
    wars = []
    for war in campaign.wars:
        attackers = [str(t) for t in as_list(war.get("attackers"))]
        defenders = [str(t) for t in as_list(war.get("defenders"))]
        if not attackers or not defenders:
            continue
        wars.append(
            WarSummary(
                name=str(war.get("name", "?")).strip(),
                attackers=attackers,
                defenders=defenders,
                attacker_regiments=sum(stats.get(t, (0, 0))[1] for t in attackers),
                defender_regiments=sum(stats.get(t, (0, 0))[1] for t in defenders),
                involves_player=campaign.player in attackers + defenders,
            )
        )
    return sorted(
        wars,
        key=lambda w: (not w.involves_player, -(w.attacker_regiments + w.defender_regiments)),
    )


# --- rendering helpers -----------------------------------------------------------------


def _you(tag: str, world: WorldOverview) -> str:
    return " **(you)**" if tag == world.player else ""


def _ranking_table(campaign: Campaign, world: WorldOverview) -> list[str]:
    rows = [
        "| # | By development | Development | By army | Regiments |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, (dev, army) in enumerate(zip(world.by_development, world.by_army, strict=False), 1):
        rows.append(
            f"| {i} | {campaign.label(dev.tag)}{_you(dev.tag, world)} | {dev.development:.0f} "
            f"| {campaign.label(army.tag)}{_you(army.tag, world)} | {army.regiments} |"
        )
    return rows


def _side(campaign: Campaign, tags: list[str]) -> str:
    shown = ", ".join(campaign.name(t) for t in tags[:4])
    return shown + (f" +{len(tags) - 4}" if len(tags) > 4 else "")
