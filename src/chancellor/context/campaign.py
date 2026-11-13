"""Shared, cached view of one loaded save (D-009).

Every query (briefings, war checks, world overview, and later agent tools) works on a
:class:`Campaign`. It parses the gamestate lazily and caches whatever it has parsed, so
running several queries against the same save stays fast.
"""

from __future__ import annotations

import re
import unicodedata
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
