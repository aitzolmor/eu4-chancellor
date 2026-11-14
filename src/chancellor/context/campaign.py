"""Shared, cached view of one loaded save (D-009).

Every query (briefings, war checks, world overview, and later agent tools) works on a
:class:`Campaign`. It parses the gamestate lazily and caches whatever it has parsed, so
running several queries against the same save stays fast.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from chancellor.game.localisation import Localisation
from chancellor.save.loader import RawSave
from chancellor.save.parser import LazyBlock, get_all, parse, parse_lazy

DYNAMIC_TAG = re.compile(r"^[A-Z]\d\d$")
_MAX_CANDIDATES = 25
_OWNS_LAND = re.compile(r"\bowned_provinces=\{\s*\d")
_RAW_DEVELOPMENT = re.compile(r"\braw_development=(-?[\d.]+)")
_REGIMENT = re.compile(r"\bregiment=\{")
_OWNER = re.compile(r'\bowner="?([A-Z0-9]{3})"?')
_AE_MODIFIER = '"aggressive_expansion"'


@dataclass(frozen=True)
class Grievance:
    """Aggressive expansion one country holds against another.

    Attributes:
        tag: The country holding the grievance.
        value: Aggressive expansion, as a positive number (the opinion penalty negated).
        attitude: The holder's AI attitude key towards the other country, if any.
    """

    tag: str
    value: float
    attitude: str | None


@dataclass(frozen=True)
class Truce:
    """A truce between two countries after a war.

    Attributes:
        other: The country the truce is with.
        last_war: Date the last war between them ended, ``YYYY.M.D``, if known.
        warscore: War score of that peace, if known.
        estimated_end: When the truce should end, ``YYYY.M.D``, if it can be estimated.
            The save does not store it; see :func:`estimate_truce_end`.
    """

    other: str
    last_war: str | None
    warscore: int | None
    estimated_end: str | None


# From common/defines.lua: TRUCE_YEARS = 5 and SCALED_TRUCE_YEARS = 10 (extra years at
# 100% war score). Checked against every truce in a 1475 save: none outlived its estimate.
TRUCE_YEARS = 5
SCALED_TRUCE_YEARS = 10
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)  # EU4 has no leap years


def estimate_truce_end(last_war: str, warscore: int) -> str | None:
    """Estimated end of a truce: base years plus years scaled by the war score.

    Modifiers to truce length (ideas, policies) are not counted, so the result is an
    estimate.

    Args:
        last_war: Date the war ended, ``YYYY.M.D``.
        warscore: War score of the peace, 0-100.

    Returns:
        The estimated end date, or ``None`` if ``last_war`` is not a date.
    """
    try:
        year, month, day = (int(part) for part in last_war.split("."))
    except ValueError:
        return None
    years = TRUCE_YEARS + SCALED_TRUCE_YEARS * min(max(warscore, 0), 100) / 100
    days = round(years * 365)
    ordinal = year * 365 + sum(_MONTH_DAYS[: month - 1]) + day - 1 + days
    year, rest = divmod(ordinal, 365)
    month = 1
    while rest >= _MONTH_DAYS[month - 1]:
        rest -= _MONTH_DAYS[month - 1]
        month += 1
    return f"{year}.{month}.{rest + 1}"


class CountryLookupError(LookupError):
    """Raised when a country query matches no country or several equally well.

    Attributes:
        query: The text that was searched for.
        candidates: ``(tag, name)`` pairs that partially matched, best first.
    """

    def __init__(self, query: str, candidates: list[tuple[str, str]], ambiguous: bool) -> None:
        self.query = query
        self.candidates = candidates
        self.ambiguous = ambiguous
        if ambiguous:
            options = ", ".join(f"{name} ({tag})" for tag, name in candidates[:8])
            message = f"'{query}' matches several countries: {options}. Use the tag instead."
        elif candidates:
            options = ", ".join(f"{name} ({tag})" for tag, name in candidates[:8])
            message = f"No country named '{query}'. Did you mean: {options}?"
        else:
            message = f"No country named '{query}'."
        super().__init__(message)


class Campaign:
    """A loaded save plus localisation, with cached lazy access to its data."""

    def __init__(
        self, meta: dict[str, Any], gamestate: dict[str, Any], loc: Localisation | None = None
    ) -> None:
        """Wrap already parsed save sections.

        Args:
            meta: Parsed ``meta`` section.
            gamestate: Gamestate from :func:`chancellor.save.parser.parse_lazy` (or a fully
                parsed dict, which is also accepted).
            loc: Localisation for readable names. Without it, game keys are shown.
        """
        self.meta = meta
        self.gamestate = gamestate
        self.loc = loc or Localisation()
        self._countries: dict[str, dict[str, Any] | None] = {}
        self._province_cache: dict[str, dict[str, Any] | None] = {}
        self._grievances: dict[str, list[Grievance]] = {}

    @classmethod
    def from_raw(cls, raw: RawSave, loc: Localisation | None = None) -> Campaign:
        """Build a campaign from the text sections returned by the loader."""
        return cls(parse(raw.meta), parse_lazy(raw.gamestate), loc)

    # --- basic facts --------------------------------------------------------------------

    @property
    def player(self) -> str:
        """The player's country tag."""
        return str(self.meta["player"])

    @property
    def date(self) -> str:
        """In-game date of the save, ``YYYY.M.D``."""
        return str(self.meta.get("date", "?"))

    @cached_property
    def country_blocks(self) -> dict[str, Any]:
        """Every country in the save, keyed by tag, as lazy (unparsed) blocks."""
        block = self.gamestate.get("countries", {})
        result = block.lazy() if isinstance(block, LazyBlock) else block
        return result if isinstance(result, dict) else {}

    def country(self, tag: str) -> dict[str, Any] | None:
        """Fully parsed country block, or ``None`` if the tag is not in the save."""
        if tag not in self._countries:
            block = self.country_blocks.get(tag)
            if isinstance(block, LazyBlock):
                block = block.parse()
            self._countries[tag] = block if isinstance(block, dict) else None
        return self._countries[tag]

    def exists(self, tag: str) -> bool:
        """Whether the country currently owns land (dead tags stay in the save).

        Checked with a regular expression on the raw block, so asking about many
        countries does not parse them all.
        """
        if tag in self._countries:
            data = self._countries[tag]
            return bool(data and data.get("owned_provinces"))
        block = self.country_blocks.get(tag)
        if isinstance(block, LazyBlock):
            return bool(_OWNS_LAND.search(block.text, block.start, block.end))
        return bool(isinstance(block, dict) and block.get("owned_provinces"))

    @cached_property
    def wars(self) -> list[dict[str, Any]]:
        """Every ongoing war in the world, fully parsed."""
        wars = []
        for block in get_all(self.gamestate, "active_war"):
            war = block.parse() if isinstance(block, LazyBlock) else block
            if isinstance(war, dict):
                wars.append(war)
        return wars

    def wars_of(self, tag: str) -> list[dict[str, Any]]:
        """Ongoing wars in which ``tag`` is an attacker or defender."""
        return [
            w
            for w in self.wars
            if tag in as_list(w.get("attackers")) or tag in as_list(w.get("defenders"))
        ]

    @cached_property
    def quick_stats(self) -> dict[str, tuple[float, int]]:
        """``(development, regiments)`` of every living country, without full parsing.

        Fully parsing ~1,400 country blocks takes tens of seconds, so world-wide rankings
        use regular expressions over the raw blocks instead (about 1-2 s). The values
        match a full parse: ``raw_development`` only appears at the top of a country
        block, and every ``regiment={`` belongs to one of its armies (armies at sea sit
        inside a ``navy`` block, see :func:`land_armies`).
        """
        stats: dict[str, tuple[float, int]] = {}
        for tag, block in self.country_blocks.items():
            if isinstance(block, LazyBlock):
                text, start, end = block.text, block.start, block.end
                if not _OWNS_LAND.search(text, start, end):
                    continue
                match = _RAW_DEVELOPMENT.search(text, start, end)
                development = float(match.group(1)) if match else 0.0
                regiments = len(_REGIMENT.findall(text, start, end))
                stats[tag] = (development, regiments)
            elif isinstance(block, dict) and block.get("owned_provinces"):
                regiments = count_regiments(block)
                stats[tag] = (float(block.get("raw_development") or 0.0), regiments)
        return stats

    @cached_property
    def global_flags(self) -> dict[str, Any]:
        """World-wide flags set by events and decisions."""
        block = self.gamestate.get("flags", {})
        result = block.parse() if isinstance(block, LazyBlock) else block
        return result if isinstance(result, dict) else {}

    @cached_property
    def diplomacy(self) -> dict[str, Any]:
        """The world's diplomatic links (alliances, guarantees, dependencies, ...)."""
        block = self.gamestate.get("diplomacy", {})
        result = block.parse() if isinstance(block, LazyBlock) else block
        return result if isinstance(result, dict) else {}

    def truce(self, tag: str, other: str) -> Truce | None:
        """The truce between two countries, if they have one.

        Truces are ``truce=yes`` in ``active_relations``, next to ``last_war`` and
        ``last_warscore``; both countries carry the same values.
        """
        country = self.country(tag) or {}
        relation = (country.get("active_relations") or {}).get(other)
        if not isinstance(relation, dict) or relation.get("truce") is not True:
            return None
        last_war = relation.get("last_war")
        warscore = relation.get("last_warscore")
        last_war = str(last_war) if last_war else None
        warscore = int(warscore) if isinstance(warscore, int | float) else None
        estimated_end = (
            estimate_truce_end(last_war, warscore)
            if last_war is not None and warscore is not None
            else None
        )
        return Truce(other=other, last_war=last_war, warscore=warscore, estimated_end=estimated_end)

    def truces(self, tag: str) -> list[Truce]:
        """Every truce ``tag`` is under, soonest estimated end first (unknown ends last)."""
        relations = (self.country(tag) or {}).get("active_relations") or {}
        found = [
            truce
            for other in relations
            if (truce := self.truce(tag, str(other))) is not None and self.exists(str(other))
        ]
        return sorted(found, key=lambda t: _date_key(t.estimated_end or "9999.1.1"))

    def opinion(self, holder: str, of: str) -> float | None:
        """``holder``'s total opinion of ``of`` (the save's ``cached_sum``), if known."""
        relation = ((self.country(holder) or {}).get("active_relations") or {}).get(of)
        value = relation.get("cached_sum") if isinstance(relation, dict) else None
        return float(value) if isinstance(value, int | float) else None

    def trust(self, holder: str, of: str) -> float | None:
        """``holder``'s trust in ``of`` (``trust_value``); absent at the default of 50."""
        relation = ((self.country(holder) or {}).get("active_relations") or {}).get(of)
        if not isinstance(relation, dict):
            return None
        value = relation.get("trust_value")
        return float(value) if isinstance(value, int | float) else None

    def aggressive_expansion_towards(self, tag: str) -> list[Grievance]:
        """Every living country's aggressive expansion against ``tag``, highest first.

        AE is an ``aggressive_expansion`` opinion modifier in the holder's
        ``active_relations``. Only blocks that mention both AE and the tag are opened, and
        only down to that one relation, so scanning the whole world takes about a second.
        """
        if tag in self._grievances:
            return self._grievances[tag]
        needle = re.compile(rf"\b{re.escape(tag)}=\{{")
        found = []
        for holder, block in self.country_blocks.items():
            if holder == tag or holder not in self.quick_stats:
                continue
            if isinstance(block, LazyBlock):
                text, start, end = block.text, block.start, block.end
                if text.find(_AE_MODIFIER, start, end) < 0 or not needle.search(text, start, end):
                    continue
                block = block.lazy()
            relations = block.get("active_relations") if isinstance(block, dict) else None
            if isinstance(relations, LazyBlock):
                relations = relations.lazy()
            relation = relations.get(tag) if isinstance(relations, dict) else None
            if isinstance(relation, LazyBlock):
                relation = relation.parse()
            if not isinstance(relation, dict):
                continue
            attitude = relation.get("attitude")
            for opinion in get_all(relation, "opinion"):
                if isinstance(opinion, dict) and opinion.get("modifier") == "aggressive_expansion":
                    found.append(
                        Grievance(
                            tag=holder,
                            value=-float(opinion.get("current_opinion") or 0.0),
                            attitude=str(attitude) if attitude else None,
                        )
                    )
        found.sort(key=lambda g: -g.value)
        self._grievances[tag] = found
        return found

    def active_links(self, kind: str) -> list[dict[str, Any]]:
        """Diplomatic links of one kind (``guarantee``, ``dependency``, ...) still in force.

        Links whose ``end_date`` lies before the save date are skipped.
        """
        today = _date_key(self.date)
        links = []
        for link in get_all(self.diplomacy, kind):
            if not isinstance(link, dict):
                continue
            end = link.get("end_date")
            if end is not None and _date_key(str(end)) <= today:
                continue
            links.append(link)
        return links

    def subject_type(self, overlord: str, subject: str) -> str | None:
        """Kind of subject relation (``vassal``, ``personal_union``, ...), if any."""
        for link in self.active_links("dependency"):
            if link.get("first") == overlord and link.get("second") == subject:
                return str(link.get("subject_type", "subject"))
        return None

    def guarantors_of(self, tag: str) -> list[str]:
        """Countries guaranteeing the independence of ``tag``."""
        return [
            str(link["first"])
            for link in self.active_links("guarantee")
            if link.get("second") == tag and "first" in link
        ]

    @cached_property
    def _provinces(self) -> dict[str, Any]:
        block = self.gamestate.get("provinces", {})
        result = block.lazy() if isinstance(block, LazyBlock) else block
        return result if isinstance(result, dict) else {}

    @cached_property
    def province_owners(self) -> dict[int, str]:
        """Owner of every owned province, without fully parsing the provinces.

        Read with a regular expression on each raw block: a province's own ``owner``
        comes before its history, where older owners are recorded.
        """
        owners: dict[int, str] = {}
        for key, block in self._provinces.items():
            number = str(key).lstrip("-")
            if not number.isdigit():
                continue
            if isinstance(block, LazyBlock):
                match = _OWNER.search(block.text, block.start, block.end)
                owner = match.group(1) if match else None
            else:
                owner = block.get("owner") if isinstance(block, dict) else None
            if isinstance(owner, str):
                owners[int(number)] = owner
        return owners

    def province(self, province_id: int | str) -> dict[str, Any] | None:
        """Fully parsed province (ids are stored negated, e.g. ``-219``), cached."""
        number = str(province_id).lstrip("-")
        if number not in self._province_cache:
            block = self._provinces.get(f"-{number}")
            if isinstance(block, LazyBlock):
                block = block.parse()
            self._province_cache[number] = block if isinstance(block, dict) else None
        return self._province_cache[number]

    @cached_property
    def empire(self) -> dict[str, Any]:
        """The Holy Roman Empire block: emperor, electors, imperial authority, reforms."""
        block = self.gamestate.get("empire", {})
        result = block.parse() if isinstance(block, LazyBlock) else block
        return result if isinstance(result, dict) else {}

    @property
    def emperor(self) -> str | None:
        """Tag of the Holy Roman Emperor, if there is one."""
        emperor = self.empire.get("emperor")
        return str(emperor) if emperor and emperor != "---" else None

    @property
    def electors(self) -> list[str]:
        """Tags of the Holy Roman Empire's electors."""
        return [str(t) for t in as_list(self.empire.get("electors"))]

    def in_hre(self, tag: str) -> bool:
        """Whether the country's capital lies inside the Holy Roman Empire."""
        country = self.country(tag)
        capital = country.get("capital") if country else None
        province = self.province(capital) if capital is not None else None
        return bool(province and province.get("hre"))

    # --- names --------------------------------------------------------------------------

    def name(self, tag: str) -> str:
        """Display name of a country, including custom names of dynamic tags."""
        if DYNAMIC_TAG.match(tag):  # colonial nations etc. store their name in the save
            data = self.country(tag)
            if data and isinstance(data.get("name"), str):
                return data["name"]
        return self.loc.country(tag)

    def label(self, tag: str) -> str:
        """``"Name (TAG)"``, the standard way to mention a country in output."""
        return f"{self.name(tag)} ({tag})"

    def text(self, key: str) -> str:
        """Localised text for a game key, humanised if no translation exists."""
        return self.loc.get(key, key.replace("_", " "))

    def subject_type_name(self, kind: str) -> str:
        """Localised name of a subject type (``vassal`` → ``Vasallo``).

        The game names most types under ``<type>_title``; a few only under the bare key.
        """
        return self.loc.get(f"{kind}_title", "") or self.text(kind)

    # --- lookup -------------------------------------------------------------------------

    def resolve_country(self, query: str) -> str:
        """Find a country tag from a tag or a (partial) display name.

        Matching is case- and accent-insensitive. Exact matches beat prefix matches,
        which beat substring matches. Within a tier, countries that still exist are
        preferred over dead tags.

        Args:
            query: A tag such as ``"BUR"`` or a name such as ``"borgona"``.

        Returns:
            The matching tag.

        Raises:
            CountryLookupError: If nothing matches or several countries match equally.
        """
        text = query.strip()
        if text.upper() in self.country_blocks:
            return text.upper()

        wanted = normalize(text)
        if not wanted:
            raise CountryLookupError(query, [], ambiguous=False)

        names = self._names_index(include_dynamic=False)
        tiers = _match_tiers(wanted, names)
        if not any(tiers):
            tiers = _match_tiers(wanted, self._names_index(include_dynamic=True))

        for tier in tiers:
            if not tier:
                continue
            if len(tier) > _MAX_CANDIDATES:  # too vague to inspect every candidate
                ranked = sorted(tier, key=lambda t: len(self.name(t)))
                pairs = [(t, self.name(t)) for t in ranked]
                raise CountryLookupError(query, pairs, ambiguous=True)
            alive = [t for t in tier if self.exists(t)]
            pool = alive or tier
            if len(pool) == 1:
                return pool[0]
            ranked = sorted(pool, key=lambda t: len(self.name(t)))
            raise CountryLookupError(query, [(t, self.name(t)) for t in ranked], ambiguous=True)

        raise CountryLookupError(query, self._suggestions(wanted), ambiguous=False)

    def _names_index(self, include_dynamic: bool) -> dict[str, str]:
        """Map tags to normalized display names."""
        index = {}
        for tag in self.country_blocks:
            if DYNAMIC_TAG.match(tag) and not include_dynamic:
                continue
            index[tag] = normalize(self.name(tag))
        return index

    def _suggestions(self, wanted: str) -> list[tuple[str, str]]:
        """Existing countries whose names share the query's first letters."""
        prefix = wanted[:3]
        found = [
            tag
            for tag, name in self._names_index(include_dynamic=False).items()
            if any(word.startswith(prefix) for word in name.split())
        ]
        alive = [t for t in found[:_MAX_CANDIDATES] if self.exists(t)]
        return [(t, self.name(t)) for t in alive[:8]]


def normalize(text: str) -> str:
    """Lowercase and strip accents, so that ``"Borgoña"`` matches ``"borgona"``."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def as_list(value: Any) -> list[Any]:
    """Treat a missing value as empty and a single value as a one-item list."""
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def land_armies(country: dict[str, Any]) -> list[dict[str, Any]]:
    """Every land army of a parsed country block, including armies at sea.

    An army carried by a fleet is stored inside that fleet's ``navy`` block rather than
    at the top of the country, so reading only ``army`` misses it.
    """
    armies = [a for a in get_all(country, "army") if isinstance(a, dict)]
    for navy in get_all(country, "navy"):
        if isinstance(navy, dict):
            armies.extend(a for a in get_all(navy, "army") if isinstance(a, dict))
    return armies


def count_regiments(country: dict[str, Any]) -> int:
    """Land regiments of a parsed country block, including those aboard ships."""
    return sum(len(get_all(a, "regiment")) for a in land_armies(country))


def _date_key(date: str) -> tuple[int, ...]:
    """Sortable form of a ``YYYY.M.D`` date; unparsable dates sort first."""
    try:
        return tuple(int(part) for part in date.split("."))
    except ValueError:
        return (0,)


def _match_tiers(wanted: str, names: dict[str, str]) -> list[list[str]]:
    exact = [t for t, n in names.items() if n == wanted]
    prefix = [t for t, n in names.items() if n.startswith(wanted) and t not in exact]
    words = [
        t
        for t, n in names.items()
        if t not in exact and t not in prefix and any(w.startswith(wanted) for w in n.split())
    ]
    inner = [t for t, n in names.items() if wanted in n and t not in exact + prefix + words]
    return [exact, prefix, words, inner]
