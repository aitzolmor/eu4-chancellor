"""What developing each province costs (D-031).

``cost = floor(50 x (1 + parts))``, where the parts are the capital's discount, embraced
institutions, the golden bull, imperial reforms, country and province modifiers, the
centre of trade, terrain, climate, prosperity, the development already there,
corruption and innovativeness (rules in :class:`DevelopmentRules`). Checked against
the game's tooltips for Austria in 1483: Vienna 59, Ostmark 53, Tirol 56.

The growth per point of development was seen up to 27 (+3% a point from 10, +6% from
20); beyond 30 it is assumed to keep rising by 3% every ten points.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.game.development_rules import (
    BASE_COST,
    CAPITAL_DISCOUNT_PER_DEVELOPMENT,
    DevelopmentRules,
)
from chancellor.game.rules import GameRules
from chancellor.save.parser import LazyBlock, get_all

PROSPEROUS = 100.0


@dataclass
class DevelopmentCost:
    """The cost of developing one province by one point.

    Attributes:
        province: Province id.
        name: Province name.
        development: Its development now.
        cost: Monarch points for one more point of development.
        parts: The changes to the base of 50, as ``(description, share)``.
    """

    province: int
    name: str
    development: float
    cost: int
    parts: list[tuple[str, float]] = field(default_factory=list)


def development_costs(
    campaign: Campaign,
    rules: DevelopmentRules,
    game_rules: GameRules,
    tag: str | None = None,
) -> list[DevelopmentCost]:
    """What developing each of a country's provinces costs, cheapest first."""
    tag = tag or campaign.player
    country = campaign.country(tag) or {}
    shared = _country_parts(campaign, rules, tag, country)
    areas = _areas(game_rules)
    costs = [
        development_cost(campaign, rules, province, tag, country, shared, areas)
        for province in as_list(country.get("owned_provinces"))
        if isinstance(province, int)
    ]
    return sorted(costs, key=lambda c: (c.cost, -c.development))


def development_cost(
    campaign: Campaign,
    rules: DevelopmentRules,
    province: int,
    tag: str,
    country: dict[str, Any],
    shared: list[tuple[str, float]],
    areas: dict[int, str],
) -> DevelopmentCost:
    """What developing one province costs; ``shared`` are the country-wide parts."""
    data = campaign.province(province) or {}
    development = sum(
        float(data.get(k) or 0) for k in ("base_tax", "base_production", "base_manpower")
    )
    parts: list[tuple[str, float]] = []
    if country.get("capital") == province:
        total = float(country.get("raw_development") or 0.0)
        share = math.trunc(total * CAPITAL_DISCOUNT_PER_DEVELOPMENT * 1000) / 1000
        parts.append((f"capital ({total:.0f} total development)", share))
    parts += shared
    for entry in _entries(data.get("modifier")):
        name = entry.get("modifier")
        change = rules.modifiers.get(str(name)) if name else None
        if change:
            parts.append((campaign.text(str(name)), change))
    level = data.get("center_of_trade")
    if isinstance(level, int) and rules.centers_of_trade.get(level):
        parts.append((f"centre of trade level {level}", rules.centers_of_trade[level]))
    state_level = _state_centre(campaign, rules, province, tag, areas)
    if state_level:
        parts.append(
            (
                f"level {state_level} centre of trade in the state",
                rules.state_centers_of_trade[state_level],
            )
        )
    if data.get("hre"):
        for reform in as_list(campaign.empire.get("passed_reform")):
            change = rules.imperial_reforms.get(str(reform), {}).get("province")
            if change:
                parts.append((campaign.text(str(reform)), change))
    terrain = rules.terrain.provinces.get(province)
    terrain_change = rules.terrain.development_cost(province)
    if terrain and terrain_change:
        parts.append((campaign.text(terrain), terrain_change))
    climate = rules.climate.get(province)
    if climate and rules.static.get(climate):
        parts.append((climate, rules.static[climate]))
    if _prosperous(campaign, areas.get(province), tag) and rules.static.get("prosperity"):
        parts.append(("prosperity", rules.static["prosperity"]))
    growth = _growth(development, rules.static.get("development_scaled", 0.03))
    if growth:
        parts.append(("development already there", growth))
    parts += _power_cost_parts(country, rules)
    factor = max(1 + sum(share for _, share in parts), 0.0)
    name = str(data.get("name") or campaign.loc.province(province))
    return DevelopmentCost(
        province, name, development, math.floor(BASE_COST * factor + 1e-9), parts
    )


def render_development(costs: list[DevelopmentCost], capital: int | None, shown: int = 5) -> str:
    """A briefing line: the cheapest provinces to develop, and the capital."""
    if not costs:
        return ""
    cheapest = costs[:shown]
    items = [f"{c.name} {c.cost}" for c in cheapest]
    capital_cost = next((c for c in costs if c.province == capital), None)
    if capital_cost and capital_cost not in cheapest:
        items.append(f"capital {capital_cost.name} {capital_cost.cost}")
    dearest = costs[-1]
    return (
        "- Developing a province (+1, same price in any category): cheapest "
        + ", ".join(items)
        + f"; dearest {dearest.name} {dearest.cost}. Cost rises with the development already "
        "there and with rough terrain."
    )


# --- parts ---------------------------------------------------------------------------------


def _country_parts(
    campaign: Campaign, rules: DevelopmentRules, tag: str, country: dict[str, Any]
) -> list[tuple[str, float]]:
    """Country-wide changes: institutions, golden bull, reforms, country modifiers."""
    parts: list[tuple[str, float]] = []
    flags = as_list(country.get("institutions"))
    for name, flag in zip(rules.institution_order, flags, strict=False):
        if flag == 1 and rules.institutions.get(name):
            parts.append((campaign.text(name), rules.institutions[name]))
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


def _power_cost_parts(country: dict[str, Any], rules: DevelopmentRules) -> list[tuple[str, float]]:
    """Corruption and innovativeness, cut to a thousandth as the game does (D-029)."""
    parts = []
    for key, per_point in (
        ("corruption", rules.corruption_power_cost),
        ("innovativeness", rules.innovativeness_power_cost),
    ):
        share = math.trunc(float(country.get(key) or 0.0) * per_point / 100 * 1000) / 1000
        if share:
            parts.append((key, share))
    return parts


def _growth(development: float, per_point: float) -> float:
    """+3% a point from 10, +6% from 20, assumed +9% from 30 and so on."""
    total = 0.0
    for point in range(10, int(development) + 1):
        total += per_point * (1 + (point - 10) // 10)
    return round(total, 3)


def _golden_bull(campaign: Campaign) -> tuple[str | None, str | None]:
    """The religion with a papacy and the golden bull in force for it."""
    block = campaign.gamestate.get("religion_instance_data")
    data = block.parse() if isinstance(block, LazyBlock) else block
    if not isinstance(data, dict):
        return None, None
    for religion, instance in data.items():
        papacy = instance.get("papacy") if isinstance(instance, dict) else None
        if isinstance(papacy, dict) and isinstance(papacy.get("golden_bull"), str):
            return str(religion), papacy["golden_bull"]
    return None, None


def _areas(game_rules: GameRules) -> dict[int, str]:
    """Province id → its area."""
    return {
        province: name
        for name, provinces in game_rules.geography.items()
        if name.endswith("_area")
        for province in provinces
    }


def _prosperous(campaign: Campaign, area: str | None, tag: str) -> bool:
    if area is None:
        return False
    block = campaign.gamestate.get("map_area_data")
    areas = block.lazy() if isinstance(block, LazyBlock) else block
    data = areas.get(area) if isinstance(areas, dict) else None
    data = data.parse() if isinstance(data, LazyBlock) else data
    state = data.get("state") if isinstance(data, dict) else None
    for entry in get_all(state, "country_state") if isinstance(state, dict) else []:
        for item in as_list(entry):
            if isinstance(item, dict) and item.get("country") == tag:
                return float(item.get("prosperity") or 0.0) >= PROSPEROUS
    return False


def _state_centre(
    campaign: Campaign, rules: DevelopmentRules, province: int, tag: str, areas: dict[int, str]
) -> int | None:
    """The level of a state-wide centre of trade in the province's state, if any."""
    area = areas.get(province)
    if area is None or not rules.state_centers_of_trade:
        return None
    for other, other_area in areas.items():
        if other_area != area or campaign.province_owners.get(other) != tag:
            continue
        level = (campaign.province(other) or {}).get("center_of_trade")
        if isinstance(level, int) and level in rules.state_centers_of_trade:
            return level
    return None


def _entries(value: Any) -> list[dict[str, Any]]:
    """Modifier entries of a country or province (one block or several)."""
    return [v for v in as_list(value) if isinstance(v, dict)]
