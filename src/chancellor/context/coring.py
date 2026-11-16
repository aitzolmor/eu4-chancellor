"""What coring each province costs (D-033, D-035).

``cost = floor(10 x min(development, 30) x max(1 + parts, 0.2) x
(1 - administrative efficiency) x 0.5 for a territory)``

The parts add up: war exhaustion, corruption and innovativeness (each cut to a thousandth,
as the tooltip shows them), ideas, policies, government reforms, estate privileges, the
golden bull, imperial reforms, country and province modifiers and a claim.
Administrative efficiency and a territory's half price multiply after the sum, and the
cost is rounded down (the wiki's Core page, checked for 1.37). Coring takes
``36 x (1 + parts)`` months (between 6 and 240). Rules in :class:`CoringRules`.

Checked against the game's tooltips for Austria in 1492 at war: Friaul (12 development, a
territory) 61 and Treviso (20) 102, with war exhaustion +3.1% and innovativeness -0.7%;
coring Friaul takes 37 months.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.context.development import _areas, _entries, _golden_bull
from chancellor.game.coring_rules import (
    DEVELOPMENT_CAP,
    MODIFIER_FLOOR,
    TERRITORY_FACTOR,
    CoringRules,
)
from chancellor.game.rules import GameRules
from chancellor.save.parser import LazyBlock, get_all


@dataclass
class CoringCost:
    """The cost of coring one province.

    Attributes:
        province: Province id.
        name: Province name.
        development: Its development.
        cost: Administrative power to core it.
        months: How long coring takes.
        territory: Whether it is a territory (outside a state), which halves the cost.
        claim: Whether the country has a claim on it.
        parts: The changes that add up, as ``(description, share)``.
        admin_efficiency: The administrative efficiency that multiplies the cost.
    """

    province: int
    name: str
    development: float
    cost: int
    months: int
    territory: bool
    claim: bool
    parts: list[tuple[str, float]] = field(default_factory=list)
    admin_efficiency: float = 0.0


def coring_costs(
    campaign: Campaign, rules: CoringRules, game_rules: GameRules, tag: str | None = None
) -> list[CoringCost]:
    """What coring each of a country's provinces without its core costs, cheapest first."""
    tag = tag or campaign.player
    country = campaign.country(tag) or {}
    shared = country_parts(campaign, rules, tag, country)
    level = int((country.get("technology") or {}).get("adm_tech", 0) or 0)
    efficiency = rules.admin_efficiency.get(level, 0.0)
    areas = _areas(game_rules)
    costs = []
    for province in as_list(country.get("owned_provinces")):
        if not isinstance(province, int):
            continue
        data = campaign.province(province) or {}
        if tag in as_list(data.get("cores")):
            continue
        territory = not _in_state(campaign, areas.get(province), tag)
        costs.append(coring_cost(campaign, rules, province, tag, shared, territory, efficiency))
    return sorted(costs, key=lambda c: (c.cost, c.name))


def coring_cost(
    campaign: Campaign,
    rules: CoringRules,
    province: int,
    tag: str,
    shared: list[tuple[str, float]],
    territory: bool,
    efficiency: float = 0.0,
) -> CoringCost:
    """What coring one province costs.

    ``shared`` are the country-wide parts; ``efficiency`` is the country's administrative
    efficiency, which multiplies the cost after the parts are summed.
    """
    data = campaign.province(province) or {}
    development = sum(
        float(data.get(k) or 0) for k in ("base_tax", "base_production", "base_manpower")
    )
    parts = list(shared)
    for entry in _entries(data.get("modifier")):
        name = entry.get("modifier")
        change = rules.modifiers.get(str(name)) if name else None
        if change:
            parts.append((campaign.text(str(name)), change))
    claim = tag in as_list(data.get("claims"))
    if claim:
        parts.append(("claim", -rules.define("CORE_HAD_CLAIM")))
    factor = max(1 + sum(share for _, share in parts), 1 + MODIFIER_FLOOR)
    cost = rules.define("PS_MAKE_PROVINCE_CORE") * min(development, DEVELOPMENT_CAP) * factor
    cost *= 1 - efficiency
    if territory:
        cost *= TERRITORY_FACTOR
    months = min(
        max(
            _round(rules.define("MONTHS_TO_CORE") * factor),
            int(rules.define("MONTHS_TO_CORE_MINIMUM")),
        ),
        int(rules.define("MONTHS_TO_CORE_MAXIMUM")),
    )
    name = str(data.get("name") or campaign.loc.province(province))
    cost_points = math.floor(cost + 1e-9)
    return CoringCost(
        province, name, development, cost_points, months, territory, claim, parts, efficiency
    )


def render_coring(costs: list[CoringCost], shown: int = 6) -> str:
    """A briefing line: what coring the country's uncored provinces costs."""
    if not costs:
        return ""
    items = [
        f"{c.name} {c.cost} adm, {c.months} months"
        + (" (territory, half price)" if c.territory else "")
        for c in costs[:shown]
    ]
    more = f" and {len(costs) - shown} more" if len(costs) > shown else ""
    parts = costs[0].parts
    changes = [f"{text} {share:+.1%}" for text, share in parts]
    if costs[0].admin_efficiency:
        changes.append(f"then administrative efficiency {-costs[0].admin_efficiency:+.0%}")
    reasons = "; cost changed by " + ", ".join(changes) if changes else ""
    return f"- Coring: {', '.join(items)}{more}{reasons}."


def country_parts(
    campaign: Campaign, rules: CoringRules, tag: str, country: dict[str, Any]
) -> list[tuple[str, float]]:
    """Country-wide changes to the cost of coring."""
    parts: list[tuple[str, float]] = []
    exhaustion = float(country.get("war_exhaustion") or 0.0)
    share = _cut(exhaustion * rules.war_exhaustion)
    if share:
        parts.append(("war exhaustion", share))
    for key, per_hundred in (
        ("corruption", rules.corruption_power_cost),
        ("innovativeness", rules.innovativeness_power_cost),
    ):
        share = _cut(float(country.get(key) or 0.0) * per_hundred / 100)
        if share:
            parts.append((key, share))
    groups = country.get("active_idea_groups")
    for name, taken in groups.items() if isinstance(groups, dict) else []:
        group = rules.idea_groups.get(str(name))
        if group is None or not isinstance(taken, int):
            continue
        change = group.start + sum(group.ideas[:taken])
        if group.ideas and taken >= len(group.ideas):
            change += group.bonus
        if change:
            parts.append((campaign.text(str(name)), change))
    for entry in get_all(country, "active_policy"):
        policy = entry.get("policy") if isinstance(entry, dict) else None
        if policy and rules.policies.get(str(policy)):
            parts.append((campaign.text(str(policy)), rules.policies[str(policy)]))
    government = country.get("government")
    stack = government.get("reform_stack") if isinstance(government, dict) else None
    for reform in as_list(stack.get("reforms") if isinstance(stack, dict) else None):
        if rules.government_reforms.get(str(reform)):
            parts.append((campaign.text(str(reform)), rules.government_reforms[str(reform)]))
    for privilege in _privileges(country):
        if rules.privileges.get(privilege):
            parts.append((campaign.text(privilege), rules.privileges[privilege]))
    religion, bull = _golden_bull(campaign)
    if bull and religion == country.get("religion") and rules.golden_bulls.get(bull):
        parts.append((campaign.text(bull), rules.golden_bulls[bull]))
    emperor = campaign.emperor == tag
    member = campaign.in_hre(tag)
    for reform in as_list(campaign.empire.get("passed_reform")):
        scopes = rules.imperial_reforms.get(str(reform), {})
        for scope, applies in (("all", True), ("member", member), ("emperor", emperor)):
            if applies and scopes.get(scope):
                parts.append((campaign.text(str(reform)), scopes[scope]))
    for entry in _entries(country.get("modifier")):
        name = entry.get("modifier")
        change = rules.modifiers.get(str(name)) if name else None
        if change:
            parts.append((campaign.text(str(name)), change))
    return parts


def _privileges(country: dict[str, Any]) -> list[str]:
    """Every estate privilege the country has granted."""
    found = []
    for estate in get_all(country, "estate"):
        if not isinstance(estate, dict):
            continue
        # granted_privileges={ { estate_church_religious_diplomats 1479.8.12 } ... }
        for granted in as_list(estate.get("granted_privileges")):
            first = granted[0] if isinstance(granted, list) and granted else granted
            if isinstance(first, str) and not first[:1].isdigit():
                found.append(first)
    return found


def _in_state(campaign: Campaign, area: str | None, tag: str) -> bool:
    """Whether the country has made a state of the area."""
    if area is None:
        return True  # without the map, assume a state (the dearer price)
    block = campaign.gamestate.get("map_area_data")
    areas = block.lazy() if isinstance(block, LazyBlock) else block
    data = areas.get(area) if isinstance(areas, dict) else None
    data = data.parse() if isinstance(data, LazyBlock) else data
    state = data.get("state") if isinstance(data, dict) else None
    for entry in get_all(state, "country_state") if isinstance(state, dict) else []:
        for item in as_list(entry):
            if isinstance(item, dict) and item.get("country") == tag:
                return True
    return False


def _cut(value: float) -> float:
    """Cut to a thousandth, toward zero, as the game's tooltip does (D-029)."""
    return math.trunc(value * 1000) / 1000


def _round(value: float) -> int:
    """Months round to the nearest (36 x 1.024 is 37 in the game's tooltip)."""
    return math.floor(value + 0.5 + 1e-9)
