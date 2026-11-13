"""Build a compact, LLM-friendly briefing of a country's situation.

The briefing is Markdown: short sections of key facts plus a table of the countries that
matter most to the subject country (allies, rivals, subjects, enemies at war, neighbours).
It can be written from any country's perspective; when the subject is not the player, a
section on its relation to the player is added. It is designed to fit comfortably in a
prompt (a few thousand tokens), never raw save data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from chancellor.context.campaign import Campaign, as_list, count_regiments, land_armies
from chancellor.game.localisation import Localisation
from chancellor.save.loader import RawSave
from chancellor.save.parser import get_all

# From the game files: ``AE_COALITION_THRESHOLD = -50`` in common/defines.lua and
# ``yearly_decay = 2`` of the ``aggressive_expansion`` opinion modifier.
AE_COALITION_THRESHOLD = 50
AE_YEARLY_DECAY = 2

_MONARCH_KEYS = (
    "monarch",
    "heir",
    "monarch_heir",
    "foreign_heir",  # elective monarchies such as Poland and Lithuania
    "queen",
    "monarch_consort",
)


@dataclass
class _Context:
    """The campaign plus the country the briefing is about."""

    campaign: Campaign
    tag: str
    country: dict[str, Any]

    @property
    def date(self) -> str:
        return self.campaign.date

    @property
    def loc(self) -> Localisation:
        return self.campaign.loc

    @property
    def is_player(self) -> bool:
        return self.tag == self.campaign.player

    def other(self, tag: str) -> dict[str, Any] | None:
        return self.campaign.country(tag)

    def name(self, tag: str) -> str:
        return self.campaign.name(tag)

    def text(self, key: str) -> str:
        return self.campaign.text(key)


def summarize_save(raw: RawSave, loc: Localisation | None = None, tag: str | None = None) -> str:
    """Produce a briefing from a loaded save.

    Args:
        raw: Save sections returned by :func:`chancellor.save.loader.load_save`.
        loc: Localisation for readable names. Without it, game keys are shown.
        tag: Country to describe. Defaults to the player.

    Returns:
        Markdown briefing.
    """
    return summarize(Campaign.from_raw(raw, loc), tag)


def summarize(campaign: Campaign, tag: str | None = None) -> str:
    """Produce a briefing of a country and its surroundings.

    Args:
        campaign: The loaded save.
        tag: Country to describe. Defaults to the player.

    Returns:
        Markdown briefing.

    Raises:
        KeyError: If the country is not in the save.
    """
    tag = tag or campaign.player
    country = campaign.country(tag)
    if country is None:
        raise KeyError(f"Country {tag} is not in the save")
    ctx = _Context(campaign=campaign, tag=tag, country=country)

    sections = [
        _header(ctx),
        _relation_to_player(ctx),
        _government(ctx),
        _economy(ctx),
        _military(ctx),
        _territory(ctx),
        _progress(ctx),
        _estates(ctx),
        _diplomacy(ctx),
        _aggressive_expansion(ctx),
        _empire(ctx),
        _wars(ctx),
        _key_countries(ctx),
    ]
    return "\n\n".join(s for s in sections if s) + "\n"


# --- sections --------------------------------------------------------------------------


def _header(ctx: _Context) -> str:
    c = ctx.country
    rank = {1: "Duchy", 2: "Kingdom", 3: "Empire"}.get(c.get("government_rank"), "")
    flags = []
    if c.get("is_great_power"):
        flags.append("Great Power")
    if c.get("score_place"):
        flags.append(f"rank #{c['score_place']} in score")
    lines = [
        f"# {'Campaign' if ctx.is_player else 'Country'} briefing: "
        f"{ctx.name(ctx.tag)} ({ctx.tag}), {ctx.date}",
        "",
        "Played by the user." if ctx.is_player else _ai_note(ctx),
        "",
        _bullets(
            [
                ("Government", " ".join(filter(None, [rank, ctx.text(_gov_type(c))]))),
                ("Culture", ctx.text(c.get("primary_culture", "?"))),
                ("Religion", ctx.text(c.get("religion", "?"))),
                ("Capital", ctx.loc.province(c["capital"]) if "capital" in c else None),
                ("Status", ", ".join(flags) or None),
            ]
        ),
    ]
    return "\n".join(lines)


def _government(ctx: _Context) -> str:
    c = ctx.country
    ruler = _find_person(c, c.get("monarch"))
    heir = _find_person(c, c.get("heir"))
    reforms = (c.get("government") or {}).get("reform_stack", {}).get("reforms", [])
    return _section(
        "Ruler and stability",
        [
            ("Ruler", _describe_person(ctx, ruler)),
            ("Heir", _describe_person(ctx, heir) if heir else "none"),
            ("Stability", _signed(c.get("stability"))),
            ("Legitimacy", _num(c.get("legitimacy"))),
            ("Prestige", _num(c.get("prestige"))),
            ("Corruption", _num(c.get("corruption"), 2)),
            ("Religious unity", _pct(c.get("religious_unity"))),
            ("Government reforms", ", ".join(ctx.text(r) for r in reforms) or None),
        ],
    )


def _economy(ctx: _Context) -> str:
    c = ctx.country
    ledger = c.get("ledger") or {}
    loans = [loan for loan in get_all(c, "loan") if isinstance(loan, dict)]
    debt = sum(loan.get("amount", 0) for loan in loans)
    income = ledger.get("lastmonthincome")
    expense = ledger.get("lastmonthexpense")
    balance = income - expense if isinstance(income, float) and isinstance(expense, float) else None
    return _section(
        "Economy",
        [
            ("Treasury", _ducats(c.get("treasury"))),
            ("Last month income", _ducats(income)),
            ("Last month expenses", _ducats(expense)),
            ("Last month balance", _ducats(balance, signed=True)),
            ("Loans", f"{len(loans)} totalling {_ducats(debt)}" if loans else "none"),
            ("Inflation", _num(c.get("inflation"), 2)),
            ("Mercantilism", _num(c.get("mercantilism"))),
        ],
    )


def _military(ctx: _Context) -> str:
    c = ctx.country
    armies = land_armies(c)
    navies = [n for n in get_all(c, "navy") if isinstance(n, dict)]
    regiments = count_regiments(c)
    ships = sum(len(get_all(n, "ship")) for n in navies)
    mercs = len(get_all(c, "mercenary_company"))
    return _section(
        "Military",
        [
            ("Manpower", _thousands(c.get("manpower"), c.get("max_manpower"))),
            ("Sailors", _pair(c.get("sailors"), c.get("max_sailors"))),
            ("Land forces", f"{regiments} regiments in {len(armies)} armies"),
            ("Composition", _composition(c)),
            ("Navy", f"{ships} ships in {len(navies)} fleets"),
            ("Mercenary companies", str(mercs) if mercs else None),
            ("Army tradition", _num(c.get("army_tradition"))),
            ("Navy tradition", _num(c.get("navy_tradition"))),
            ("Army professionalism", _pct(c.get("army_professionalism"))),
            ("War exhaustion", _num(c.get("war_exhaustion"), 2)),
        ],
    )


def _territory(ctx: _Context) -> str:
    c = ctx.country
    return _section(
        "Territory",
        [
            ("Development", _num(c.get("raw_development"), 0)),
            ("Provinces owned", _count(c.get("owned_provinces"))),
            ("Cores", _count(c.get("core_provinces"))),
            ("Claims", _count(c.get("claim_provinces"))),
            # The save omits the key when there is no overextension.
            ("Overextension", _pct(c.get("overextension_percentage") or 0.0)),
            ("Average unrest", _num(c.get("average_unrest"), 2)),
            ("Average autonomy", _num(c.get("average_autonomy"))),
            ("Colonies", str(c["num_of_colonies"]) if c.get("num_of_colonies") else None),
        ],
    )


def _progress(ctx: _Context) -> str:
    c = ctx.country
    tech = c.get("technology") or {}
    ideas = c.get("active_idea_groups") or {}
    return _section(
        "Technology and ideas",
        [
            (
                "Technology (adm/dip/mil)",
                "/".join(str(tech.get(k, "?")) for k in ("adm_tech", "dip_tech", "mil_tech")),
            ),
            ("Idea groups", ", ".join(f"{ctx.text(k)} {v}/7" for k, v in ideas.items()) or None),
            ("Innovativeness", _num(c.get("innovativeness"))),
            ("Monarch power (adm/dip/mil)", _monarch_power(c.get("powers"))),
        ],
    )


def _monarch_power(powers: Any) -> str | None:
    values = as_list(powers)
    if len(values) != 3:
        return None
    return "/".join(str(v) for v in values)


def _estates(ctx: _Context) -> str:
    rows = []
    for estate in get_all(ctx.country, "estate"):
        if not isinstance(estate, dict) or "type" not in estate:
            continue
        land = _num(estate.get("territory"))
        rows.append(
            (
                ctx.text(estate["type"]),
                f"loyalty {_num(estate.get('loyalty'))}, land share {land or '0'}%",
            )
        )
    return _section("Estates", rows) if rows else ""


def _diplomacy(ctx: _Context) -> str:
    c = ctx.country
    rivals = _rivals(c)
    return _section(
        "Diplomacy",
        [
            ("Allies", _tags(ctx, c.get("allies"))),
            ("Subjects", _tags(ctx, c.get("subjects"))),
            ("Rivals", _tags(ctx, rivals)),
            ("Rivalled by", _tags(ctx, get_all(c, "enemy"))),
            ("Coalition against it", _tags(ctx, get_all(c, "coalition_against_us"))),
            ("Trade embargoes against it", _tags(ctx, c.get("trade_embargoed_by"))),
        ],
    )


def _aggressive_expansion(ctx: _Context, top: int = 12) -> str:
    """Who holds aggressive expansion against the country, and how close to a coalition."""
    grievances = ctx.campaign.aggressive_expansion_towards(ctx.tag)
    if not grievances:
        return ""
    coalition = {str(t) for t in as_list(ctx.country.get("coalition_against_us"))}
    over = sum(1 for g in grievances if g.value >= AE_COALITION_THRESHOLD)
    lines = [
        "## Aggressive expansion",
        "",
        f"{len(grievances)} countries hold aggressive expansion (AE) against "
        f"{ctx.name(ctx.tag)}; {over} at {AE_COALITION_THRESHOLD} or more, the level at "
        f"which they can join a coalition. {len(coalition)} are in a coalition against it. "
        f"AE decays by {AE_YEARLY_DECAY} a year at base.",
        "",
        "| Country | AE | Status | Attitude |",
        "| --- | --- | --- | --- |",
    ]
    allies = {str(t) for t in as_list(ctx.country.get("allies"))}
    for g in grievances[:top]:
        attitude = ctx.text(g.attitude) if g.attitude else ""
        if g.tag in coalition:
            status = "in coalition"
        elif ctx.campaign.subject_type(ctx.tag, g.tag):
            status = "subject"
        elif g.tag in allies:
            status = "ally"
        else:
            status = ""
        lines.append(f"| {ctx.name(g.tag)} ({g.tag}) | {g.value:.0f} | {status} | {attitude} |")
    if len(grievances) > top:
        lines += ["", f"{len(grievances) - top} more with less AE not shown."]
    return "\n".join(lines)


def _empire(ctx: _Context) -> str:
    """The country's place in the Holy Roman Empire; empty if it has none."""
    campaign = ctx.campaign
    emperor = campaign.emperor
    electors = campaign.electors
    is_emperor = ctx.tag == emperor
    is_elector = ctx.tag in electors
    if not (is_emperor or is_elector or campaign.in_hre(ctx.tag)):
        return ""
    roles = [r for r, held in (("Emperor", is_emperor), ("elector", is_elector)) if held]
    role = " and ".join(roles) if roles else "member"
    empire = campaign.empire
    reforms = [_reform_title(ctx, str(r)) for r in as_list(empire.get("passed_reform"))]
    return _section(
        "Holy Roman Empire",
        [
            ("Role", role[0].upper() + role[1:]),
            ("Emperor", None if is_emperor or not emperor else f"{ctx.name(emperor)} ({emperor})"),
            ("Imperial authority", _num(empire.get("imperial_influence"))),
            (
                "Imperial reforms passed",
                f"{len(reforms)}: {', '.join(reforms)}" if reforms else "none",
            ),
            ("Electors", _elector_preferences(ctx, electors)),
        ],
    )


def _reform_title(ctx: _Context, reform: str) -> str:
    title = ctx.loc.get(f"{reform}_title", "")
    return title or ctx.text(reform)


def _elector_preferences(ctx: _Context, electors: list[str]) -> str | None:
    """Electors grouped by the candidate they favour for the next election."""
    if not electors:
        return None
    backers: dict[str, list[str]] = {}
    for elector in electors:
        preferred = (ctx.other(elector) or {}).get("preferred_emperor")
        backers.setdefault(str(preferred) if preferred else "", []).append(elector)
    emperor = ctx.campaign.emperor
    groups = sorted(
        backers.items(),
        key=lambda item: (not item[0], -len(item[1]), item[0] != emperor, item[0]),
    )
    parts = []
    for candidate, tags in groups:
        who = f"{ctx.name(candidate)} ({candidate})" if candidate else "no preference"
        verb = "favours" if len(tags) == 1 else "favour"
        parts.append(f"{len(tags)} {verb} {who} ({', '.join(ctx.name(t) for t in tags)})")
    return f"{len(electors)}; " + "; ".join(parts)


def _wars(ctx: _Context) -> str:
    lines = []
    for war in ctx.campaign.wars_of(ctx.tag):
        attackers = as_list(war.get("attackers"))
        defenders = as_list(war.get("defenders"))
        side = "attacker" if ctx.tag in attackers else "defender"
        goal = war.get("take_province") or {}
        goal_text = ""
        if isinstance(goal, dict) and goal:
            cb = ctx.text(goal.get("casus_belli", goal.get("type", "")))
            target = ctx.loc.province(goal["province"]) if "province" in goal else ""
            goal_text = f"; war goal: {cb} {target}".rstrip()
        lines.append(
            f"- **{str(war.get('name', '?')).strip()}** ({ctx.tag} is {side}; started "
            f"{war.get('action', '?')}{goal_text})\n"
            f"  - Attackers: {_tags(ctx, attackers)}\n"
            f"  - Defenders: {_tags(ctx, defenders)}"
        )
    body = "\n".join(lines) if lines else "At peace."
    return f"## Wars\n\n{body}"


def _key_countries(ctx: _Context) -> str:
    c = ctx.country
    relations: dict[str, list[str]] = {}

    def add(tags: Iterable[str], label: str) -> None:
        for t in tags:
            if t != ctx.tag:
                relations.setdefault(t, []).append(label)

    if not ctx.is_player:
        add([ctx.campaign.player], "player")
    add(as_list(c.get("allies")), "ally")
    add(as_list(c.get("subjects")), "subject")
    add(_rivals(c), "rival")
    add(get_all(c, "enemy"), "rivals it")
    for war in ctx.campaign.wars_of(ctx.tag):
        attackers = as_list(war.get("attackers"))
        defenders = as_list(war.get("defenders"))
        add(defenders if ctx.tag in attackers else attackers, "at war")
    add(as_list(c.get("neighbours")), "neighbour")

    rows = [
        f"| Country | Relation | Development | Regiments | Mil tech | Their opinion of {ctx.tag} |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for t, labels in relations.items():
        other = ctx.other(t)
        if other is None:
            continue
        rows.append(
            f"| {ctx.name(t)} ({t}) | {', '.join(dict.fromkeys(labels))} "
            f"| {_num(other.get('raw_development'), 0)} | {_regiments(other)} "
            f"| {_mil_tech(other)} | {_opinion(ctx, other, ctx.tag)} |"
        )
    if len(rows) == 2:
        return ""
    return "## Key countries\n\n" + "\n".join(rows)


def _ai_note(ctx: _Context) -> str:
    note = (
        f"AI-controlled country, described from its own perspective. "
        f"The user plays {ctx.campaign.label(ctx.campaign.player)}."
    )
    if not ctx.country.get("owned_provinces"):
        note += " **This country no longer exists (it owns no provinces).**"
    return note


def _relation_to_player(ctx: _Context) -> str:
    """How the subject country and the player relate, plus a strength comparison."""
    if ctx.is_player:
        return ""
    player_tag = ctx.campaign.player
    player = ctx.other(player_tag)
    if player is None:
        return ""
    c = ctx.country
    links = []
    if player_tag in as_list(c.get("allies")):
        links.append("allied with the player")
    if ctx.tag in as_list(player.get("subjects")):
        links.append("subject of the player")
    if player_tag in as_list(c.get("subjects")):
        links.append("overlord of the player")
    if player_tag in _rivals(c):
        links.append("rivals the player")
    if ctx.tag in _rivals(player):
        links.append("rivalled by the player")
    if ctx.tag in get_all(player, "coalition_against_us"):
        links.append("in a coalition against the player")
    if player_tag in get_all(c, "coalition_against_us"):
        links.append("the player is in a coalition against it")
    if player_tag in as_list(c.get("neighbours")):
        links.append("borders the player")
    for war in ctx.campaign.wars_of(ctx.tag):
        attackers = as_list(war.get("attackers"))
        defenders = as_list(war.get("defenders"))
        same_side = {ctx.tag, player_tag} <= set(attackers) or {ctx.tag, player_tag} <= set(
            defenders
        )
        if player_tag in attackers + defenders:
            relation = "fighting alongside" if same_side else "at war with"
            links.append(f"{relation} the player ({str(war.get('name', '')).strip()})")
    shared_allies = sorted(set(as_list(c.get("allies"))) & set(as_list(player.get("allies"))))

    rows = [
        ("Status", "; ".join(links) or "no direct ties"),
        (f"Its opinion of {player_tag}", _opinion(ctx, c, player_tag)),
        (f"{player_tag}'s opinion of it", _opinion(ctx, player, ctx.tag)),
        ("Allies shared with the player", _tags(ctx, shared_allies) if shared_allies else None),
    ]
    table = [
        f"| | {ctx.name(ctx.tag)} | {ctx.name(player_tag)} (player) |",
        "| --- | --- | --- |",
        f"| Development | {_num(c.get('raw_development'), 0)} "
        f"| {_num(player.get('raw_development'), 0)} |",
        f"| Regiments | {_regiments(c)} | {_regiments(player)} |",
        f"| Manpower | {_thousands(c.get('manpower'), c.get('max_manpower'))} "
        f"| {_thousands(player.get('manpower'), player.get('max_manpower'))} |",
        f"| Mil tech | {_mil_tech(c)} | {_mil_tech(player)} |",
        f"| Treasury | {_ducats(c.get('treasury'))} | {_ducats(player.get('treasury'))} |",
        f"| Allies | {len(as_list(c.get('allies')))} | {len(as_list(player.get('allies')))} |",
    ]
    return _section("Relation to the player", rows) + "\n\n" + "\n".join(table)


def _rivals(country: dict[str, Any]) -> list[str]:
    rivals = get_all(country, "rival")
    return [r["country"] for r in rivals if isinstance(r, dict) and "country" in r]


def _regiments(country: dict[str, Any]) -> int:
    return count_regiments(country)


def _mil_tech(country: dict[str, Any]) -> str:
    return str((country.get("technology") or {}).get("mil_tech", "?"))


def _opinion(ctx: _Context, holder: dict[str, Any], target: str) -> str:
    """``holder``'s opinion of ``target`` with its AI attitude, e.g. ``-46 (Rivalry)``."""
    relation = (holder.get("active_relations") or {}).get(target)
    if not isinstance(relation, dict):
        return "?"
    opinion = relation.get("cached_sum")
    text = _signed(opinion) if opinion is not None else "?"
    attitude = relation.get("attitude")
    if isinstance(attitude, str):
        text += f" ({ctx.text(attitude)})"
    return text


# --- helpers ---------------------------------------------------------------------------


def _find_person(country: dict[str, Any], ref: Any) -> dict[str, Any] | None:
    """Resolve a ``{ id type }`` reference to a ruler or heir in the country history."""
    if not isinstance(ref, dict) or "id" not in ref:
        return None
    wanted = ref["id"]
    found = None
    history = country.get("history") or {}
    for date in history:
        for event in get_all(history, date):
            if not isinstance(event, dict):
                continue
            for key in _MONARCH_KEYS:
                for person in get_all(event, key):
                    if isinstance(person, dict) and (person.get("id") or {}).get("id") == wanted:
                        found = person  # keep the latest record
    return found


def _describe_person(ctx: _Context, person: dict[str, Any] | None) -> str | None:
    if not person:
        return None
    stats = "/".join(str(person.get(k, "?")) for k in ("ADM", "DIP", "MIL"))
    parts = [f"{person.get('name', '?')} {person.get('dynasty', '')}".strip(), f"({stats})"]
    age = _years_between(person.get("birth_date"), ctx.date)
    if age is not None:
        parts.append(f"age {age}")
    traits = person.get("personalities")
    if isinstance(traits, dict) and traits:
        parts.append("traits: " + ", ".join(ctx.text(t) for t in traits))
    return ", ".join([" ".join(parts[:2]), *parts[2:]])


def _years_between(start: Any, end: str) -> int | None:
    try:
        sy, sm, sd = (int(x) for x in str(start).split("."))
        ey, em, ed = (int(x) for x in end.split("."))
    except ValueError:
        return None
    return ey - sy - ((em, ed) < (sm, sd))


def _gov_type(country: dict[str, Any]) -> str:
    gov = country.get("government")
    if isinstance(gov, dict) and isinstance(gov.get("government"), str):
        return gov["government"]
    return str(country.get("government_name", "?"))


def _composition(country: dict[str, Any]) -> str | None:
    units = country.get("num_subunits_type_and_cat")
    if not isinstance(units, dict):
        return None
    parts = []
    for kind in ("infantry", "cavalry", "artillery"):
        value = units.get(kind)
        total = sum(value.values()) if isinstance(value, dict) else 0
        parts.append(f"{total} {kind}")
    return ", ".join(parts)


def _tags(ctx: _Context, tags: Any) -> str:
    items = as_list(tags)
    return ", ".join(f"{ctx.name(t)} ({t})" for t in items) if items else "none"


def _section(title: str, rows: list[tuple[str, str | None]]) -> str:
    body = _bullets(rows)
    return f"## {title}\n\n{body}" if body else ""


def _bullets(rows: list[tuple[str, str | None]]) -> str:
    return "\n".join(f"- {label}: {value}" for label, value in rows if value not in (None, ""))


def _num(value: Any, digits: int = 1) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return f"{value:.{digits}f}"


def _signed(value: Any) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return f"{value:+g}"


def _pct(value: Any) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return f"{value * 100:.0f}%"


def _ducats(value: Any, signed: bool = False) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return f"{value:+.1f} ducats" if signed else f"{value:.1f} ducats"


def _thousands(value: Any, maximum: Any) -> str | None:
    if not isinstance(value, int | float) or not isinstance(maximum, int | float):
        return None
    return f"{value * 1000:,.0f} / {maximum * 1000:,.0f}"


def _pair(value: Any, maximum: Any) -> str | None:
    if not isinstance(value, int | float) or not isinstance(maximum, int | float):
        return None
    return f"{value:,.0f} / {maximum:,.0f}"


def _count(value: Any) -> str | None:
    return str(len(value)) if isinstance(value, list) else None
