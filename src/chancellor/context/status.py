"""The campaign at a glance: the numbers the desktop panel shows (Phase 4, UI_DESIGN).

Briefings render straight to Markdown for the LLM; the panel needs the same facts as
plain values it can lay out itself. :func:`campaign_status` reads them from the save
without any game files, so the panel can show them as soon as a save is loaded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from chancellor.context.campaign import Campaign, as_list, count_regiments
from chancellor.save.parser import LazyBlock, get_all


@dataclass(frozen=True)
class CampaignStatus:
    """Key facts about one country in the current save.

    Attributes:
        tag: Country tag.
        name: Display name.
        date: In-game date, ``YYYY.M.D``.
        save_name: File name of the save, if known.
        treasury: Ducats in the treasury.
        income: Last month's income.
        expenses: Last month's expenses.
        loans: Number of loans.
        manpower: Available manpower, in men.
        max_manpower: Maximum manpower, in men.
        regiments: Land regiments, including armies at sea.
        stability: Stability, -3 to +3.
        prestige: Prestige, -100 to 100.
        legitimacy: Legitimacy (monarchies), if present.
        monarch_power: Administrative, diplomatic and military points.
        development: Total development.
        wars: Names of the wars the country is fighting.
        great_power_rank: Rank among great powers (1-8), if it is one.
    """

    tag: str
    name: str
    date: str
    save_name: str | None
    treasury: float | None
    income: float | None
    expenses: float | None
    loans: int
    manpower: float | None
    max_manpower: float | None
    regiments: int
    stability: float | None
    prestige: float | None
    legitimacy: float | None
    monarch_power: tuple[int, int, int] | None
    development: float | None
    wars: list[str]
    great_power_rank: int | None

    def to_dict(self) -> dict[str, Any]:
        """Plain values for JSON (the panel's page reads this)."""
        return asdict(self)


def campaign_status(
    campaign: Campaign, save_path: Path | None = None, tag: str | None = None
) -> CampaignStatus:
    """Collect the key facts about a country (default: the player).

    Args:
        campaign: The loaded save.
        save_path: Where the save was read from, for display.
        tag: Country to describe; defaults to the player.

    Raises:
        KeyError: If the country is not in the save.
    """
    tag = tag or campaign.player
    country = campaign.country(tag)
    if country is None:
        raise KeyError(f"Country {tag} is not in the save")
    ledger = country.get("ledger") or {}
    manpower = _number(country.get("manpower"))
    max_manpower = _number(country.get("max_manpower"))
    return CampaignStatus(
        tag=tag,
        name=campaign.name(tag),
        date=campaign.date,
        save_name=save_path.name if save_path else None,
        treasury=_number(country.get("treasury")),
        income=_number(ledger.get("lastmonthincome")),
        expenses=_number(ledger.get("lastmonthexpense")),
        loans=sum(1 for loan in get_all(country, "loan") if isinstance(loan, dict)),
        manpower=manpower * 1000 if manpower is not None else None,  # stored in thousands
        max_manpower=max_manpower * 1000 if max_manpower is not None else None,
        regiments=count_regiments(country),
        stability=_number(country.get("stability")),
        prestige=_number(country.get("prestige")),
        legitimacy=_number(country.get("legitimacy")),
        monarch_power=_powers(country.get("powers")),
        development=_number(country.get("raw_development")),
        wars=[str(w.get("name", "?")).strip() for w in campaign.wars_of(tag)],
        great_power_rank=_great_power_rank(campaign, tag),
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _powers(value: Any) -> tuple[int, int, int] | None:
    points = [int(v) for v in as_list(value) if isinstance(v, int | float)]
    return (points[0], points[1], points[2]) if len(points) == 3 else None


def _great_power_rank(campaign: Campaign, tag: str) -> int | None:
    block = campaign.gamestate.get("great_powers")
    if isinstance(block, LazyBlock):
        block = block.parse()
    if not isinstance(block, dict):
        return None
    for entry in get_all(block, "original"):
        if isinstance(entry, dict) and entry.get("country") == tag:
            rank = entry.get("rank")
            return int(rank) if isinstance(rank, int) else None
    return None
