"""Evaluate game conditions (triggers) against a save, with three-valued logic.

EU4 conditions decide who can see a decision (``potential``), what is needed to take it
(``allow``), when a mission is complete, and so on. Re-implementing the whole trigger
language is out of scope. Instead this module evaluates the conditions that actually
matter for planning and answers ``None`` ("unknown") for everything else:

* ``True`` / ``False`` when the save and game files settle the question;
* ``None`` when the condition is not supported or the data is not in the save.

Unknowns propagate the way logic says they should (``AND`` with a ``False`` is still
``False``), so a missing province or the wrong religion is reported with certainty even
when other parts of the condition cannot be checked.

Approximations (documented so the assistant can hedge):

* ``was_tag = X`` is true only if the country *is* X now (tag history is not tracked).
* ``is_former_colonial_nation`` is false unless the tag looks like a colonial nation.
* ``had_country_flag`` counts years as 365 days.
* Game rules are assumed at their defaults (``normal_or_historical_nations = yes``,
  no random new world, no custom nations).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from chancellor.context.campaign import DYNAMIC_TAG, Campaign, as_list
from chancellor.game.missions import MissionLibrary
from chancellor.game.rules import GameRules
from chancellor.save.parser import Repeated, get_all

Truth = bool | None

_TAG = re.compile(r"^[A-Z][A-Z0-9]{2}$")
_ROOT_WORDS = {"ROOT", "root"}
_THIS_WORDS = {"THIS", "this"}
_COUNTRY_NUMBERS = {
    "adm_tech": ("technology", "adm_tech"),
    "dip_tech": ("technology", "dip_tech"),
    "mil_tech": ("technology", "mil_tech"),
    "num_of_cities": ("num_of_cities",),
    "stability": ("stability",),
    "prestige": ("prestige",),
    "legitimacy": ("legitimacy",),
    "army_tradition": ("army_tradition",),
    "navy_tradition": ("navy_tradition",),
    "treasury": ("treasury",),
    "manpower": ("manpower",),
    "total_development": ("raw_development",),
    "government_rank": ("government_rank",),
    "army_professionalism": ("army_professionalism",),
    "mercantilism": ("mercantilism",),
    "religious_unity": ("religious_unity",),
    "num_of_ports": ("num_of_ports",),
    "monthly_income": ("ledger", "lastmonthincome"),
}
# Game rules and setup assumed at their defaults.
_DEFAULT_RULES = {
    "normal_or_historical_nations": True,
    "is_random_new_world": False,
    "is_playing_custom_nation": False,
    "end_game_tags_blocked": False,
}
_NON_SOVEREIGN = {
    "tributary_state",
    "nahuatl_tributary",
    "trade_protectorate",
    "cultural_sphere_of_influence_subject",
}


def all_of(values: Iterable[Truth]) -> Truth:
    """Three-valued AND: false wins, then unknown, else true."""
    unknown = False
    for value in values:
        if value is False:
            return False
        if value is None:
            unknown = True
    return None if unknown else True


def any_of(values: Iterable[Truth]) -> Truth:
    """Three-valued OR: true wins, then unknown, else false."""
    unknown = False
    for value in values:
        if value is True:
            return True
        if value is None:
            unknown = True
    return None if unknown else False


def negate(value: Truth) -> Truth:
    """Three-valued NOT."""
    return None if value is None else not value


class Evaluator:
    """Evaluates conditions for one ``ROOT`` country."""

    def __init__(
        self,
        campaign: Campaign,
        rules: GameRules,
        root: str,
        missions: MissionLibrary | None = None,
    ) -> None:
        """Bind the evaluator to a save, the game rules and the ``ROOT`` country.

        Args:
            campaign: The loaded save.
            rules: Game data (cultures, religions, geography, scripted triggers).
            root: The country conditions are evaluated for.
            missions: Mission definitions, needed for ``has_mission``.
        """
        self.campaign = campaign
        self.rules = rules
        self.root = root
        self.missions = missions
        self._depth = 0

    # --- public API ---------------------------------------------------------------------

    def country(self, script: Any, tag: str | None = None) -> Truth:
        """Evaluate a country-scope block (all entries must hold)."""
        return self._block(script, lambda k, v: self._country_entry(k, v, tag or self.root))

    def province(self, script: Any, province_id: int) -> Truth:
        """Evaluate a province-scope block for one province."""
        return self._block(script, lambda k, v: self._province_entry(k, v, province_id))

    def explain(self, script: Any, tag: str | None = None) -> list[tuple[Truth, str, Any]]:
        """Evaluate each top-level entry of a country-scope block separately.

        Returns:
            ``(result, key, value)`` triples, in order, for showing a checklist.
        """
        if not isinstance(script, dict):
            return []
        entry = self._country_fn(tag or self.root)
        results: list[tuple[Truth, str, Any]] = []
        ifs = _items(script["if"]) if "if" in script else []
        # The parser groups repeated keys, so `else_if`/`else` belong to the last `if`.
        tail = {k: script[k] for k in ("else_if", "else") if k in script}
        for key, value in script.items():
            if key in ("else_if", "else"):
                continue
            if key == "if":
                for index, item in enumerate(ifs):
                    chain = {"if": item, **tail} if index == len(ifs) - 1 else {"if": item}
                    results.append((self._block(chain, entry), "if", chain))
                continue
            for item in _items(value):
                results.append((self._logic(key, item, entry), key, item))
        return results

    # --- blocks and logic ---------------------------------------------------------------

    def _country_fn(self, this: str) -> Callable[[str, Any], Truth]:
        return lambda k, v: self._country_entry(k, v, this)

    def _block(self, script: Any, entry: Callable[[str, Any], Truth]) -> Truth:
        if not isinstance(script, dict):
            return None if script is not None else True
        results: list[Truth] = []
        previous_if: Truth = True  # True means "an earlier branch already applied"
        for key, value in script.items():
            for item in _items(value):
                if key == "if":
                    previous_if, result = self._branch(item, entry)
                    results.append(result)
                elif key == "else_if":
                    if previous_if is False:
                        previous_if, result = self._branch(item, entry)
                        results.append(result)
                    elif previous_if is None:
                        results.append(None)
                elif key == "else":
                    if previous_if is False:
                        results.append(self._block(item, entry))
                    elif previous_if is None:
                        results.append(None)
                else:
                    results.append(self._logic(key, item, entry))
        return all_of(results)

    def _branch(self, block: Any, entry: Callable[[str, Any], Truth]) -> tuple[Truth, Truth]:
        """Evaluate an ``if``: returns (did the limit hold, result of the branch)."""
        if not isinstance(block, dict):
            return None, None
        condition = self._block(block.get("limit"), entry)
        body = {k: v for k, v in block.items() if k != "limit"}
        if condition is True:
            return True, self._block(body, entry)
        if condition is False:
            return False, True
        return None, None

    def _logic(self, key: str, value: Any, entry: Callable[[str, Any], Truth]) -> Truth:
        if key == "AND":
            return self._block(value, entry)
        if key == "OR":
            return any_of(self._entries(value, entry))
        if key == "NOT":
            return negate(any_of(self._entries(value, entry)))
        if key == "custom_trigger_tooltip" and isinstance(value, dict):
            return self._block({k: v for k, v in value.items() if k != "tooltip"}, entry)
        if key == "calc_true_if" and isinstance(value, dict):
            amount = value.get("amount", 1)
            parts = [
                r
                for k, v in value.items()
                if k not in ("amount", "desc")
                for r in (self._logic(k, i, entry) for i in _items(v))
            ]
            hits = sum(1 for r in parts if r is True)
            unknown = sum(1 for r in parts if r is None)
            if hits >= amount:
                return True
            return None if hits + unknown >= amount else False
        if key in ("tooltip", "desc", "type"):
            return True
        return entry(key, value)

    def _entries(self, block: Any, entry: Callable[[str, Any], Truth]) -> list[Truth]:
        if not isinstance(block, dict):
            return [None]
        results: list[Truth] = []
        for key, value in block.items():
            for item in _items(value):
                if key in ("if", "else_if", "else"):
                    results.append(self._block({key: item}, entry))
                else:
                    results.append(self._logic(key, item, entry))
        return results

    # --- country scope ------------------------------------------------------------------

    def _country_entry(self, key: str, value: Any, this: str) -> Truth:  # noqa: C901
        c = self.campaign.country(this)
        if c is None:
            return False
        if key in _DEFAULT_RULES:
            return _is(_DEFAULT_RULES[key], value)
        if key == "current_age":
            return self.campaign.gamestate.get("current_age") == value
        if key == "has_estate":
            return value in {e.get("type") for e in get_all(c, "estate") if isinstance(e, dict)}
        if key == "has_estate_privilege":
            granted = {
                str(p[0]) if isinstance(p, list) and p else str(p)
                for e in get_all(c, "estate")
                if isinstance(e, dict)
                for p in as_list(e.get("granted_privileges"))
            }
            return value in granted
        if key == "tag":
            return this == self._tag(value, this)
        if key == "was_tag":
            return this == self._tag(value, this)
        if key == "exists":
            if isinstance(value, bool):
                return _is(self.campaign.exists(this), value)
            target = self._tag(value, this)
            return self.campaign.exists(target) if target else None
        if key == "ai":
            return _is(this != self.campaign.player, value)
        if key == "has_dlc":
            return str(value) in as_list(self.campaign.meta.get("dlc_enabled"))
        if key == "map_setup":
            return False if value == "map_setup_random" else None
        if key == "is_at_war":
            return _is(bool(self.campaign.wars_of(this)), value)
        if key == "primary_culture":
            return c.get("primary_culture") == self._same(value, "primary_culture")
        if key == "accepted_culture":
            culture = self._same(value, "primary_culture")
            return culture == c.get("primary_culture") or culture in get_all(c, "accepted_culture")
        if key == "culture_group":
            group = self.rules.culture_groups.get(str(c.get("primary_culture")))
            if value in _ROOT_WORDS or _TAG.match(str(value)):
                other = self.campaign.country(self._tag(value, this) or "")
                value = self.rules.culture_groups.get(str((other or {}).get("primary_culture")))
            return None if group is None else group == value
        if key == "religion":
            return c.get("religion") == self._same(value, "religion")
        if key == "religion_group":
            group = self.rules.religion_groups.get(str(c.get("religion")))
            if value in _ROOT_WORDS or _TAG.match(str(value)):
                other = self.campaign.country(self._tag(value, this) or "")
                value = self.rules.religion_groups.get(str((other or {}).get("religion")))
            return None if group is None else group == value
        if key == "technology_group":
            return c.get("technology_group") == value
        if key == "government":
            return (c.get("government") or {}).get("government") == value
        if key == "has_reform":
            reforms = ((c.get("government") or {}).get("reform_stack") or {}).get("reforms", [])
            return value in as_list(reforms)
        if key in _COUNTRY_NUMBERS:
            return _at_least(_dig(c, _COUNTRY_NUMBERS[key]), value)
        if key == "is_subject":
            return _is(isinstance(c.get("overlord"), str), value)
        if key == "is_subject_of":
            return c.get("overlord") == self._tag(value, this)
        if key == "is_subject_of_type":
            overlord = c.get("overlord")
            if not isinstance(overlord, str):
                return False
            return self.campaign.subject_type(overlord, this) == value
        if key == "overlord_of":
            target = self.campaign.country(self._tag(value, this) or "")
            return bool(target) and target.get("overlord") == this
        if key == "alliance_with":
            return self._tag(value, this) in as_list(c.get("allies"))
        if key == "is_emperor":
            return _is(self.campaign.emperor == this, value)
        if key == "is_part_of_hre":
            return _is(self.campaign.in_hre(this), value)
        if key == "is_colonial_nation":
            return _is("colonial_parent" in c, value)
        if key == "is_former_colonial_nation":
            former = bool(DYNAMIC_TAG.match(this)) and "colonial_parent" not in c
            return _is(former, value)
        if key == "is_nomad":
            reforms = ((c.get("government") or {}).get("reform_stack") or {}).get("reforms", [])
            return _is(any("steppe" in str(r) for r in as_list(reforms)), value)
        if key == "is_lesser_in_union":
            overlord = c.get("overlord")
            kind = self.campaign.subject_type(overlord, this) if isinstance(overlord, str) else None
            return _is(kind is not None and "personal_union" in kind, value)
        if key == "has_country_flag":
            return value in (c.get("flags") or {})
        if key == "had_country_flag" and isinstance(value, dict):
            since = (c.get("flags") or {}).get(value.get("flag"))
            if since is None:
                return False
            return _days_between(str(since), self.campaign.date) >= int(value.get("days", 0))
        if key == "has_global_flag":
            return value in self.campaign.global_flags
        if key == "has_country_modifier":
            names = {m.get("modifier") for m in get_all(c, "modifier") if isinstance(m, dict)}
            return value in names
        if key == "capital":
            return c.get("capital") == value
        if key == "has_mission":
            return self._has_mission(c, str(value))
        if key == "mission_completed":
            return value in as_list(c.get("completed_missions"))
        if key == "junior_union_with":
            senior = self._tag(value, this)
            kind = self.campaign.subject_type(senior, this) if senior else None
            return kind is not None and "personal_union" in kind
        if key == "senior_union_with":
            junior = self._tag(value, this)
            kind = self.campaign.subject_type(this, junior) if junior else None
            return kind is not None and "personal_union" in kind
        if key in ("owns", "owns_core_province", "controls", "owns_or_non_sovereign_subject_of"):
            return self._owns(key, value, this)
        if key in (
            "num_of_owned_provinces_with",
            "num_of_provinces_owned_or_owned_by_non_sovereign_subjects_with",
        ):
            include_subjects = key != "num_of_owned_provinces_with"
            return self._count_provinces(value, this, include_subjects)
        if key in ("any_owned_province", "all_owned_province"):
            provinces = [p for p in as_list(c.get("owned_provinces")) if isinstance(p, int)]
            results = [self.province(value, p) for p in provinces]
            return any_of(results) if key.startswith("any") else all_of(results)
        if key == "capital_scope":
            capital = c.get("capital")
            return self.province(value, capital) if isinstance(capital, int) else None
        if key in _ROOT_WORDS:
            return self.country(value, self.root)
        if key == "overlord":
            overlord = c.get("overlord")
            return self.country(value, overlord) if isinstance(overlord, str) else False
        if key == "emperor":
            emperor = self.campaign.emperor
            return self.country(value, emperor) if emperor else False
        if _TAG.match(key) and isinstance(value, dict):
            if self.campaign.country(key) is None:
                return False
            return self.country(value, key)
        if key.lstrip("-").isdigit() and isinstance(value, dict):
            return self.province(value, int(key.lstrip("-")))
        if key in self.rules.geography and isinstance(value, dict):
            return self._geography_scope(key, value)
        if key in self.rules.scripted_triggers and isinstance(value, bool):
            return self._scripted(key, value, self._country_fn(this))
        return None

    def _tag(self, value: Any, this: str) -> str | None:
        text = str(value)
        if text in _ROOT_WORDS:
            return self.root
        if text in _THIS_WORDS:
            return this
        return text if _TAG.match(text) else None

    def _same(self, value: Any, field_name: str) -> Any:
        """``primary_culture = ROOT`` compares with ROOT's value."""
        if value in _ROOT_WORDS:
            return (self.campaign.country(self.root) or {}).get(field_name)
        return value

    def _owns(self, key: str, value: Any, this: str) -> Truth:
        if not isinstance(value, int):
            return None
        province = self.campaign.province(value)
        if province is None:
            return False
        owner = province.get("owner")
        if key == "owns":
            return owner == this
        if key == "controls":
            return province.get("controller") == this
        if key == "owns_core_province":
            return owner == this and this in as_list(province.get("cores"))
        return owner == this or self._non_sovereign_subject_of(owner, this)

    def _count_provinces(self, block: Any, this: str, include_subjects: bool) -> Truth:
        if not isinstance(block, dict):
            return None
        wanted = block.get("value", 1)
        filters = {k: v for k, v in block.items() if k != "value"}
        owners = [this]
        if include_subjects:
            subjects = as_list((self.campaign.country(this) or {}).get("subjects"))
            owners += [s for s in subjects if self._non_sovereign_subject_of(s, this)]
        provinces = []
        for owner in owners:
            data = self.campaign.country(owner) or {}
            provinces += [p for p in as_list(data.get("owned_provinces")) if isinstance(p, int)]
        results = [self.province(filters, p) for p in provinces]
        hits = sum(1 for r in results if r is True)
        unknown = sum(1 for r in results if r is None)
        if hits >= wanted:
            return True
        return None if hits + unknown >= wanted else False

    def _geography_scope(self, name: str, block: dict[str, Any]) -> Truth:
        provinces = self.rules.geography.get(name, frozenset())
        conditions = {k: v for k, v in block.items() if k != "type"}
        results = [self.province(conditions, p) for p in sorted(provinces)]
        return any_of(results) if block.get("type") == "any" else all_of(results)

    def _scripted(self, name: str, expected: bool, entry: Callable[[str, Any], Truth]) -> Truth:
        definition = self.rules.scripted_triggers[name]
        if "$" in repr(definition) or self._depth > 10:  # parameterised or too deep
            return None
        self._depth += 1
        try:
            result = self._block(definition, entry)
        finally:
            self._depth -= 1
        return result if expected else negate(result)

    def _has_mission(self, country: dict[str, Any], mission: str) -> Truth:
        """Whether the mission is part of the country's current mission tree."""
        if self.missions is None:
            return None
        slots = (country.get("country_missions") or {}).get("mission_slot", [])
        for slot in as_list(slots):
            for name in as_list(slot):
                series = self.missions.series(str(name))
                if series and any(m.name == mission for m in series.missions):
                    return True
        return False

    def _non_sovereign_subject_of(self, subject: Any, overlord: str) -> bool:
        if not isinstance(subject, str):
            return False
        data = self.campaign.country(subject) or {}
        if data.get("overlord") != overlord:
            return False
        return self.campaign.subject_type(overlord, subject) not in _NON_SOVEREIGN

    # --- province scope -----------------------------------------------------------------

    def _province_entry(self, key: str, value: Any, province_id: int) -> Truth:
        if key == "province_id":
            return province_id == value
        if key in ("area", "region", "superregion", "continent", "colonial_region"):
            members = self.rules.geography.get(str(value))
            return None if members is None else province_id in members
        p = self.campaign.province(province_id)
        if p is None:
            return None
        owner = p.get("owner")
        if key == "owned_by":
            return owner == self._tag(value, self.root)
        if key == "is_core":
            return self._tag(value, self.root) in as_list(p.get("cores"))
        if key == "controlled_by":
            return p.get("controller") == self._tag(value, self.root)
        if key == "country_or_non_sovereign_subject_holds":
            target = self._tag(value, self.root)
            return owner == target or self._non_sovereign_subject_of(owner, target or "")
        if key == "culture":
            return p.get("culture") == value
        if key == "religion":
            return p.get("religion") == value
        if key == "religion_group":
            group = self.rules.religion_groups.get(str(p.get("religion")))
            return None if group is None else group == value
        if key == "trade_goods":
            return p.get("trade_goods") == value
        if key == "has_discovered":
            return self._tag(value, self.root) in as_list(p.get("discovered_by"))
        if key == "has_province_modifier":
            names = {m.get("modifier") for m in get_all(p, "modifier") if isinstance(m, dict)}
            return value in names
        if key == "is_capital_of":
            target = self.campaign.country(self._tag(value, self.root) or "")
            return bool(target) and target.get("capital") == province_id
        if key == "is_capital":
            owner_data = self.campaign.country(owner) if isinstance(owner, str) else None
            return _is(bool(owner_data) and owner_data.get("capital") == province_id, value)
        if key in ("is_part_of_hre", "hre"):
            return _is(bool(p.get("hre")), value)
        if key == "is_city":
            return _is(isinstance(owner, str), value)
        if key in ("base_tax", "base_production", "base_manpower"):
            return _at_least(p.get(key), value)
        if key == "development":
            total = sum(
                float(p.get(k) or 0) for k in ("base_tax", "base_production", "base_manpower")
            )
            return _at_least(total, value)
        if key == "owner" and isinstance(value, dict):
            return self.country(value, owner) if isinstance(owner, str) else False
        if key in _ROOT_WORDS and isinstance(value, dict):
            return self.country(value, self.root)
        if key in self.rules.scripted_triggers and isinstance(value, bool):
            entry = lambda k, v: self._province_entry(k, v, province_id)  # noqa: E731
            return self._scripted(key, value, entry)
        return None


# --- helpers ---------------------------------------------------------------------------


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, Repeated) else [value]


def _is(actual: Truth, expected: Any) -> Truth:
    if actual is None or not isinstance(expected, bool):
        return None
    return actual == expected


def _at_least(actual: Any, wanted: Any) -> Truth:
    if not isinstance(actual, int | float) or not isinstance(wanted, int | float):
        return None
    return actual >= wanted


def _dig(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = data
    for part in path:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _days_between(start: str, end: str) -> int:
    def days(date: str) -> int:
        try:
            year, month, day = (int(x) for x in date.split("."))
        except ValueError:
            return 0
        return year * 365 + (month - 1) * 30 + day

    return days(end) - days(start)
