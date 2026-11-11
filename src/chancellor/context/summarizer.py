"""Build a compact, LLM-friendly briefing of the player's situation (Phase 1).

The briefing is Markdown: short sections of key facts plus a table of the countries that
matter most to the player (allies, rivals, subjects, enemies at war, neighbours). It is
designed to fit comfortably in a prompt (a few thousand tokens), never raw save data.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from chancellor.game.localisation import Localisation
from chancellor.save.loader import RawSave
from chancellor.save.parser import LazyBlock, get_all, parse, parse_lazy

_MONARCH_KEYS = ("monarch", "heir", "monarch_heir", "queen", "monarch_consort")
_DYNAMIC_TAG = re.compile(r"^[A-Z]\d\d$")


@dataclass
class _Context:
    """Everything the section builders need."""

    tag: str
    date: str
    country: dict[str, Any]
    countries: dict[str, Any]
    gamestate: dict[str, Any]
    loc: Localisation
    _cache: dict[str, dict[str, Any] | None] = field(default_factory=dict)

    def other(self, tag: str) -> dict[str, Any] | None:
        """Fully parse another country, with caching."""
        if tag not in self._cache:
            block = self.countries.get(tag)
            if isinstance(block, LazyBlock):
                block = block.parse()
            self._cache[tag] = block if isinstance(block, dict) else None
        return self._cache[tag]

    def name(self, tag: str) -> str:
        """Display name of a country, including custom names of dynamic tags."""
        if _DYNAMIC_TAG.match(tag):  # colonial nations etc. store their name in the save
            self.other(tag)
        data = self._cache.get(tag)
        if data and isinstance(data.get("name"), str):
            return data["name"]
        return self.loc.country(tag)

    def text(self, key: str) -> str:
        """Localised text for a game key, humanised if no translation exists."""
        return self.loc.get(key, key.replace("_", " "))


def summarize_save(raw: RawSave, loc: Localisation | None = None) -> str:
    """Produce a briefing from a loaded save.

    Args:
        raw: Save sections returned by :func:`chancellor.save.loader.load_save`.
        loc: Localisation for readable names. Without it, game keys are shown.

    Returns:
        Markdown briefing.
    """
    meta = parse(raw.meta)
    return summarize(meta, parse_lazy(raw.gamestate), loc or Localisation())


def summarize(meta: dict[str, Any], gamestate: dict[str, Any], loc: Localisation) -> str:
    """Produce a briefing of the player's country and its surroundings.

    Args:
        meta: Parsed ``meta`` section (provides ``player`` and ``date``).
        gamestate: Gamestate parsed with :func:`chancellor.save.parser.parse_lazy`.
        loc: Localisation for readable names.

    Returns:
        Markdown briefing.

    Raises:
        KeyError: If the save has no player country.
    """
    tag = meta["player"]
    countries_block = gamestate["countries"]
    countries = (
        countries_block.lazy() if isinstance(countries_block, LazyBlock) else countries_block
    )
    player_block = countries[tag]
    country = player_block.parse() if isinstance(player_block, LazyBlock) else player_block
    ctx = _Context(
        tag=tag,
        date=str(meta.get("date", "?")),
        country=country,
        countries=countries,
        gamestate=gamestate,
        loc=loc,
    )
    ctx._cache[tag] = country

    sections = [
        _header(ctx),
        _government(ctx),
        _economy(ctx),
        _military(ctx),
        _territory(ctx),
        _progress(ctx),
        _estates(ctx),
        _diplomacy(ctx),
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
        f"# Campaign briefing: {ctx.name(ctx.tag)} ({ctx.tag}), {ctx.date}",
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
    armies = [a for a in get_all(c, "army") if isinstance(a, dict)]
    navies = [n for n in get_all(c, "navy") if isinstance(n, dict)]
    regiments = sum(len(get_all(a, "regiment")) for a in armies)
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
            ("Overextension", _pct(c.get("overextension_percentage"))),
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
        ],
    )


def _estates(ctx: _Context) -> str:
    rows = []
    for estate in get_all(ctx.country, "estate"):
        if not isinstance(estate, dict) or "type" not in estate:
            continue
        rows.append(
            (
                ctx.text(estate["type"]),
                f"loyalty {_num(estate.get('loyalty'))}, "
                f"land share {_num(estate.get('territory'))}%",
            )
        )
    return _section("Estates", rows) if rows else ""


def _diplomacy(ctx: _Context) -> str:
    c = ctx.country
    rivals = [r["country"] for r in get_all(c, "rival") if isinstance(r, dict) and "country" in r]
    return _section(
        "Diplomacy",
        [
            ("Allies", _tags(ctx, c.get("allies"))),
            ("Subjects", _tags(ctx, c.get("subjects"))),
            ("Our rivals", _tags(ctx, rivals)),
            ("Countries rivalling us", _tags(ctx, get_all(c, "enemy"))),
            ("Coalition against us", _tags(ctx, get_all(c, "coalition_against_us"))),
            ("Trade embargoes against us", _tags(ctx, c.get("trade_embargoed_by"))),
        ],
    )


def _wars(ctx: _Context) -> str:
    lines = []
    for war_block in get_all(ctx.gamestate, "active_war"):
        war = war_block.parse() if isinstance(war_block, LazyBlock) else war_block
        if not isinstance(war, dict):
            continue
        attackers = _as_list(war.get("attackers"))
        defenders = _as_list(war.get("defenders"))
        if ctx.tag not in attackers and ctx.tag not in defenders:
            continue
        side = "attacker" if ctx.tag in attackers else "defender"
        goal = war.get("take_province") or {}
        goal_text = ""
        if isinstance(goal, dict) and goal:
            cb = ctx.text(goal.get("casus_belli", goal.get("type", "")))
            target = ctx.loc.province(goal["province"]) if "province" in goal else ""
            goal_text = f"; war goal: {cb} {target}".rstrip()
        lines.append(
            f"- **{str(war.get('name', '?')).strip()}** (we are {side}; started "
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

    rivals = [r["country"] for r in get_all(c, "rival") if isinstance(r, dict) and "country" in r]
    add(_as_list(c.get("allies")), "ally")
    add(_as_list(c.get("subjects")), "subject")
    add(rivals, "our rival")
    add(get_all(c, "enemy"), "rivals us")
    for war_block in get_all(ctx.gamestate, "active_war"):
        war = war_block.parse() if isinstance(war_block, LazyBlock) else war_block
        attackers = _as_list(war.get("attackers"))
        defenders = _as_list(war.get("defenders"))
        if ctx.tag in attackers:
            add(defenders, "at war")
        elif ctx.tag in defenders:
            add(attackers, "at war")
    add(_as_list(c.get("neighbours")), "neighbour")

    rows = [
        "| Country | Relation | Development | Regiments | Mil tech | Their opinion of us |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for t, labels in relations.items():
        other = ctx.other(t)
        if other is None:
            continue
        armies = [a for a in get_all(other, "army") if isinstance(a, dict)]
        regiments = sum(len(get_all(a, "regiment")) for a in armies)
        relation = (other.get("active_relations") or {}).get(ctx.tag) or {}
        opinion = relation.get("cached_sum") if isinstance(relation, dict) else None
        attitude = relation.get("attitude") if isinstance(relation, dict) else None
        opinion_text = _signed(opinion) if opinion is not None else "?"
        if attitude:
            opinion_text += f" ({ctx.text(attitude)})"
        rows.append(
            f"| {ctx.name(t)} ({t}) | {', '.join(dict.fromkeys(labels))} "
            f"| {_num(other.get('raw_development'), 0)} | {regiments} "
            f"| {(other.get('technology') or {}).get('mil_tech', '?')} | {opinion_text} |"
        )
    if len(rows) == 2:
        return ""
    return "## Key countries\n\n" + "\n".join(rows)


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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _tags(ctx: _Context, tags: Any) -> str:
    items = _as_list(tags)
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
