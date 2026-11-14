"""The aggressive expansion (AE) a conquest would add, country by country (D-030).

The coalition risk (D-024) reads the AE countries already hold; this says what taking
particular provinces would add to it, so the advice can say how much land is safe to
take. For each province:

``base = min(development, 30) x 0.6 x casus belli x (1 + prestige effect) x
(1 - administrative efficiency)``

The casus belli factor is 0.25 for a core of the attacker and 1 otherwise (a claim, or
no casus belli). Every country within reach then receives

``base x (1 + religion + infidel conquest + culture + Empire + same overlord) x
distance falloff``, times 2/3 for the attacker's allies and 0.1 for its subjects.

Rules come from the game files (:class:`AeRules`). The distance falloff and the reach
follow the game wiki (written for 1.24): distance to the receiver's nearest province,
rounded down to hundreds and capped at 400, ``1 / (1 + 0.75 x distance / 100)``;
countries farther than that are left out. Both are estimates until checked against a
peace deal in game.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.game.ae_rules import AeRules
from chancellor.game.rules import GameRules

MAX_DISTANCE = 400.0
COALITION_AE = 50.0


@dataclass
class TakenProvince:
    """One province of the conquest and the AE it causes before it is shared out."""

    province: int
    name: str
    owner: str
    development: float
    core: bool
    base: float


@dataclass
class Receiver:
    """AE one country would receive.

    Attributes:
        tag: The country.
        added: AE the conquest would add.
        current: AE it already holds against the attacker.
        parts: The modifiers of the largest share, ``(description, share)``.
    """

    tag: str
    added: float
    current: float
    parts: list[tuple[str, float]] = field(default_factory=list)

    @property
    def after(self) -> float:
        """AE it would hold after the conquest."""
        return self.current + self.added


@dataclass
class ConquestAe:
    """The AE of taking some provinces.

    Attributes:
        attacker: Who takes them.
        provinces: The provinces, with their base AE.
        reduction: The attacker's reduction of AE (prestige, administrative efficiency).
        receivers: Countries that would receive AE, most AE after the conquest first.
    """

    attacker: str
    provinces: list[TakenProvince]
    reduction: list[tuple[str, float]]
    receivers: list[Receiver]

    @property
    def base(self) -> float:
        """The AE of the conquest before it is shared out."""
        return sum(p.base for p in self.provinces)

    def crossing(self, threshold: float = COALITION_AE) -> list[Receiver]:
        """Countries that would go from below ``threshold`` to at or above it."""
        return [r for r in self.receivers if r.current < threshold <= r.after]

    def at_threshold(self, threshold: float = COALITION_AE) -> list[Receiver]:
        """Countries at or above ``threshold`` after the conquest."""
        return [r for r in self.receivers if r.after >= threshold]


def conquest_ae(
    campaign: Campaign,
    ae_rules: AeRules,
    game_rules: GameRules,
    provinces: list[int],
    attacker: str | None = None,
) -> ConquestAe:
    """Estimate the AE of taking ``provinces``.

    Args:
        campaign: The loaded save.
        ae_rules: AE rules from the game files.
        game_rules: Culture and religion groups.
        provinces: Province ids to take.
        attacker: Who takes them; the player by default.

    Raises:
        KeyError: If the attacker is not in the save.
    """
    attacker = attacker or campaign.player
    att = campaign.country(attacker)
    if att is None:
        raise KeyError(f"Country {attacker} is not in the save")

    reduction = _reduction(att, ae_rules)
    factor = 1 + sum(share for _, share in reduction)
    taken = []
    for province_id in provinces:
        data = campaign.province(province_id) or {}
        owner = data.get("owner")
        if not isinstance(owner, str) or owner == attacker:
            continue
        development = sum(
            float(data.get(k) or 0) for k in ("base_tax", "base_production", "base_manpower")
        )
        core = attacker in as_list(data.get("cores"))
        cb = ae_rules.core_factor if core else ae_rules.claim_factor
        base = (
            min(development, ae_rules.define("AE_PROVINCE_CAP"))
            * ae_rules.define("PO_DEMAND_PROVINCES_AE")
            * cb
            * max(factor, 0.0)
        )
        name = str(data.get("name") or campaign.loc.province(province_id))
        taken.append(TakenProvince(province_id, name, owner, development, core, base))

    current = {g.tag: g.value for g in campaign.aggressive_expansion_towards(attacker)}
    totals: dict[str, Receiver] = {}
    largest: dict[str, float] = {}  # the largest single share, whose reasons are shown
    for province in taken:
        for tag, share, parts in _shares(campaign, ae_rules, game_rules, attacker, att, province):
            receiver = totals.setdefault(tag, Receiver(tag, 0.0, current.get(tag, 0.0)))
            receiver.added += share
            if share > largest.get(tag, 0.0):
                largest[tag] = share
                receiver.parts = parts
    receivers = sorted(totals.values(), key=lambda r: -r.after)
    return ConquestAe(attacker, taken, reduction, receivers)


def claimed_provinces(campaign: Campaign, target: str, attacker: str | None = None) -> list[int]:
    """The target's provinces the attacker has a claim or a core on: what a war takes."""
    attacker = attacker or campaign.player
    country = campaign.country(attacker) or {}
    wanted = {
        p
        for key in ("claim_provinces", "core_provinces")
        for p in as_list(country.get(key))
        if isinstance(p, int)
    }
    owners = campaign.province_owners
    return sorted(p for p, owner in owners.items() if owner == target and p in wanted)


def render_ae_section(
    campaign: Campaign,
    ae_rules: AeRules,
    game_rules: GameRules,
    target: str,
    attacker: str | None = None,
) -> str:
    """A Markdown section on the AE of taking the target's claimed and core provinces."""
    attacker = attacker or campaign.player
    provinces = claimed_provinces(campaign, target, attacker)
    lines = ["## Aggressive expansion of taking your claims and cores", ""]
    if not provinces:
        lines.append(
            f"{campaign.name(attacker)} has no claims or cores on {campaign.name(target)}'s "
            "provinces, so there is no AE estimate (fabricate claims first, or name provinces)."
        )
        return "\n".join(lines) + "\n"
    estimate = conquest_ae(campaign, ae_rules, game_rules, provinces, attacker)
    return "\n".join(lines + render_conquest_ae(campaign, estimate)) + "\n"


def render_conquest_ae(campaign: Campaign, estimate: ConquestAe, shown: int = 8) -> list[str]:
    """Markdown lines on the AE of a conquest (for the war check)."""
    if not estimate.provinces:
        return []
    development = sum(p.development for p in estimate.provinces)
    cores = sum(1 for p in estimate.provinces if p.core)
    lines = [
        f"Taking {len(estimate.provinces)} province{'s' if len(estimate.provinces) != 1 else ''} "
        f"({development:.0f} development"
        + (f", {cores} of them your cores" if cores else "")
        + f") causes about {estimate.base:.0f} AE before it is shared out"
        + (
            " (" + ", ".join(f"{text} {share:+.0%}" for text, share in estimate.reduction) + ")"
            if estimate.reduction
            else ""
        )
        + ".",
        "",
        "| Country | AE now | Added | After | Main reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    for receiver in estimate.receivers[:shown]:
        reasons = ", ".join(text for text, _ in receiver.parts) or "-"
        lines.append(
            f"| {campaign.label(receiver.tag)} | {receiver.current:.0f} | +{receiver.added:.0f} "
            f"| {receiver.after:.0f} | {reasons} |"
        )
    crossing = estimate.crossing()
    total = len(estimate.at_threshold())
    lines += [
        "",
        f"{total} countries would be at {COALITION_AE:.0f}+ AE afterwards"
        + (
            f"; {len(crossing)} would cross it now: "
            + ", ".join(campaign.name(r.tag) for r in crossing[:8])
            if crossing
            else ""
        )
        + ".",
        "",
        "_AE estimate: the per-development rate, casus belli, prestige, culture, religion and "
        "Empire factors come from the game files; the distance falloff and which distant "
        "countries are left out follow the game wiki and are not yet checked for 1.37. A "
        "claim and no casus belli count the same here._",
    ]
    return lines


# --- shares -------------------------------------------------------------------------------


def _reduction(country: dict[str, Any], rules: AeRules) -> list[tuple[str, float]]:
    """The attacker's own changes to AE: prestige and administrative efficiency."""
    parts = []
    prestige = float(country.get("prestige") or 0.0)
    if prestige:
        parts.append(("prestige", prestige / 100 * rules.prestige_ae_impact))
    level = int((country.get("technology") or {}).get("adm_tech", 0) or 0)
    efficiency = rules.admin_efficiency.get(level, 0.0)
    if efficiency:
        parts.append(("administrative efficiency", -efficiency))
    return parts


def _shares(
    campaign: Campaign,
    rules: AeRules,
    game_rules: GameRules,
    attacker: str,
    att: dict[str, Any],
    province: TakenProvince,
) -> list[tuple[str, float, list[tuple[str, float]]]]:
    """What each country within reach receives from one province."""
    origin = rules.positions.get(province.province)
    if origin is None:
        return []
    nearest: dict[str, float] = {}
    for other, owner in campaign.province_owners.items():
        if owner == attacker:
            continue
        place = rules.positions.get(other)
        if place is None:
            continue
        distance = math.dist(origin, place)
        if distance <= MAX_DISTANCE and distance < nearest.get(owner, math.inf):
            nearest[owner] = distance
    nearest[province.owner] = 0.0

    data = campaign.province(province.province) or {}
    culture = str(data.get("culture") or "")
    in_hre = bool(data.get("hre"))
    loser = campaign.country(province.owner) or {}
    loser_religion = str(loser.get("religion") or "")
    attacker_group = game_rules.religion_groups.get(str(att.get("religion") or ""))
    loser_group = game_rules.religion_groups.get(loser_religion)
    allies = set(as_list(att.get("allies")))
    subjects = set(as_list(att.get("subjects")))

    shares = []
    for tag, distance in nearest.items():
        country = campaign.country(tag) or {}
        parts: list[tuple[str, float]] = []
        religion = str(country.get("religion") or "")
        if religion and religion == loser_religion:
            parts.append(("same religion", rules.define("AE_SAME_RELIGION")))
            if attacker_group and loser_group and attacker_group != loser_group:
                parts.append(("infidel conquest", rules.define("AE_INFIDEL_CONQUEST")))
        elif religion and game_rules.religion_groups.get(religion) == loser_group:
            if rules.define("AE_SAME_RELIGION_GROUP"):
                parts.append(("same religion group", rules.define("AE_SAME_RELIGION_GROUP")))
        elif religion:
            parts.append(("other religion", rules.define("AE_DIFFERENT_RELIGION")))
        primary = str(country.get("primary_culture") or "")
        if primary and primary == culture:
            parts.append(("same culture", rules.define("AE_SAME_CULTURE")))
        elif primary and game_rules.culture_groups.get(primary) == game_rules.culture_groups.get(
            culture
        ):
            parts.append(("same culture group", rules.define("AE_SAME_CULTURE_GROUP")))
        if in_hre and campaign.in_hre(tag):
            parts.append(("both in the Empire", rules.define("AE_HRE_INTERNAL")))
        overlord = country.get("overlord")
        if isinstance(overlord, str) and overlord == loser.get("overlord"):
            parts.append(("same overlord", rules.define("AE_SAME_OVERLORD")))
        factor = max(1 + sum(share for _, share in parts), 0.0)
        steps = min(math.floor(distance / 100) * 100, MAX_DISTANCE)
        falloff = 1 / (1 + rules.define("AE_DISTANCE_BASE") * steps / 100)
        if falloff < 1:
            parts.append((f"distance {steps:.0f}", falloff - 1))
        share = province.base * factor * falloff
        if tag in allies:
            share *= 2 / 3
            parts.append(("your ally", -1 / 3))
        if tag in subjects:
            share *= 0.1
            parts.append(("your subject", -0.9))
        if tag == province.owner:
            parts.insert(0, ("owner", 0.0))
        if share > 0:
            shares.append((tag, share, parts))
    return shares
