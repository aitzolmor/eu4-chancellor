"""Where a country's money comes from and goes, from the ledger in the save (D-052).

Each country's ``ledger`` block holds per-category arrays: income has 19 slots, expenses
38. The save does not name them; the order below is the one the open-source
``eu4save`` crate (rakaly/jomini, MIT, used by PDX Tools) reads, and it was checked
against the user's 1535 save: the categories sum to ``lastmonthincome`` and
``lastmonthexpense`` (81.98 and 63.69 ducats), and the large ones are where the game
puts them (army maintenance, forts, advisors; a war reparation after a won war).

The arrays read:

* ``lastmonthincometable`` / ``lastmonthexpensetable``: last month;
* ``income`` / ``expense``: this year so far;
* ``lastyearincome`` / ``lastyearexpense``: the previous calendar year;
* ``totalexpensetable``: everything spent since the campaign began.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list

# Index → category. Slots not listed here are summed as "other".
INCOME: dict[int, str] = {
    0: "Taxation",
    1: "Production",
    2: "Trade",
    3: "Gold",
    4: "Tariffs",
    5: "Vassals",
    6: "Harbor fees",
    7: "Subsidies",
    8: "War reparations",
    9: "Interest",
    10: "Gifts",
    11: "Events",
    12: "Spoils of war",
    13: "Treasure fleet",
    14: "Siphoning income",
    15: "Condottieri",
    16: "Knowledge sharing",
    17: "Blockading foreign ports",
    18: "Looting foreign cities",
}
EXPENSES: dict[int, str] = {
    0: "Advisor maintenance",
    1: "Interest",
    2: "State maintenance",
    4: "Subsidies",
    5: "War reparations",
    6: "Army maintenance",
    7: "Fleet maintenance",
    8: "Fort maintenance",
    9: "Colonists",
    10: "Missionaries",
    11: "Raising armies",
    12: "Building fleets",
    13: "Building fortresses",
    14: "Buildings",
    16: "Repaid loans",
    17: "Gifts",
    18: "Hiring advisors",
    19: "Events",
    20: "Peace",
    21: "Vassal fee",
    22: "Tariffs",
    23: "Support loyalists",
    26: "Condottieri",
    27: "Root out corruption",
    28: "Embrace institution",
    30: "Knowledge sharing",
    31: "Trade company investments",
    33: "Ports blockaded",
    34: "Cities looted",
    35: "Monuments",
    36: "Centre of trade upgrades",
    37: "Colony changes",
}
# Costs paid every month while nothing changes; the rest are one-off spending.
RECURRING_EXPENSES = frozenset(
    {
        "Advisor maintenance",
        "Interest",
        "State maintenance",
        "Subsidies",
        "War reparations",
        "Army maintenance",
        "Fleet maintenance",
        "Fort maintenance",
        "Colonists",
        "Missionaries",
        "Vassal fee",
        "Tariffs",
        "Support loyalists",
        "Condottieri",
        "Root out corruption",
        "Knowledge sharing",
    }
)
OTHER = "Other"


@dataclass
class Ledger:
    """A country's income and expenses by category, in ducats.

    Attributes:
        tag: The country.
        last_month_income: Category → income last month.
        last_month_expenses: Category → expenses last month.
        year_income: Category → income this year so far.
        year_expenses: Category → expenses this year so far.
        last_year_income: Category → income in the previous calendar year.
        last_year_expenses: Category → expenses in the previous calendar year.
        total_expenses: Category → everything spent since the campaign began.
        recurring_income: The game's ``last_months_recurring_income``.
        recurring_expenses: The game's ``last_months_recurring_expenses``.
    """

    tag: str
    last_month_income: dict[str, float] = field(default_factory=dict)
    last_month_expenses: dict[str, float] = field(default_factory=dict)
    year_income: dict[str, float] = field(default_factory=dict)
    year_expenses: dict[str, float] = field(default_factory=dict)
    last_year_income: dict[str, float] = field(default_factory=dict)
    last_year_expenses: dict[str, float] = field(default_factory=dict)
    total_expenses: dict[str, float] = field(default_factory=dict)
    recurring_income: float | None = None
    recurring_expenses: float | None = None


def categorise(values: Any, names: dict[int, str]) -> dict[str, float]:
    """Name a ledger array's slots, dropping zeros; unnamed slots go to "Other"."""
    result: dict[str, float] = {}
    for index, value in enumerate(as_list(values)):
        if not isinstance(value, int | float) or value <= 0:
            continue
        name = names.get(index, OTHER)
        result[name] = result.get(name, 0.0) + float(value)
    return result


def read_ledger(campaign: Campaign, tag: str | None = None) -> Ledger:
    """A country's ledger (the player's by default)."""
    tag = tag or campaign.player
    ledger = (campaign.country(tag) or {}).get("ledger") or {}

    def number(key: str) -> float | None:
        value = ledger.get(key)
        return float(value) if isinstance(value, int | float) else None

    return Ledger(
        tag=tag,
        last_month_income=categorise(ledger.get("lastmonthincometable"), INCOME),
        last_month_expenses=categorise(ledger.get("lastmonthexpensetable"), EXPENSES),
        year_income=categorise(ledger.get("income"), INCOME),
        year_expenses=categorise(ledger.get("expense"), EXPENSES),
        last_year_income=categorise(ledger.get("lastyearincome"), INCOME),
        last_year_expenses=categorise(ledger.get("lastyearexpense"), EXPENSES),
        total_expenses=categorise(ledger.get("totalexpensetable"), EXPENSES),
        recurring_income=number("last_months_recurring_income"),
        recurring_expenses=number("last_months_recurring_expenses"),
    )


def budget_line(ledger: Ledger, items: int = 4) -> str | None:
    """One briefing line: last month's largest sources and costs."""
    if not ledger.last_month_income and not ledger.last_month_expenses:
        return None
    parts = []
    if ledger.last_month_income:
        parts.append("income from " + _top(ledger.last_month_income, items))
    if ledger.last_month_expenses:
        parts.append("spent on " + _top(ledger.last_month_expenses, items))
    return "; ".join(parts) + " (details: get_budget)"


def render_budget(campaign: Campaign, ledger: Ledger) -> str:
    """The full breakdown as Markdown, for ``get_budget``."""
    year = campaign.date.split(".")[0]
    lines = [f"# Budget of {campaign.label(ledger.tag)}, {campaign.date}", ""]
    if not any((ledger.last_month_income, ledger.last_month_expenses, ledger.last_year_income)):
        return "\n".join([*lines, "The save has no ledger for this country."]) + "\n"

    income, spent = sum(ledger.last_month_income.values()), sum(ledger.last_month_expenses.values())
    lines.append(
        f"Last month: income {income:.2f}, expenses {spent:.2f}, balance {income - spent:+.2f} "
        "ducats."
    )
    if ledger.recurring_income is not None and ledger.recurring_expenses is not None:
        recurring = ledger.recurring_income - ledger.recurring_expenses
        lines.append(
            f"Recurring (what repeats each month): income {ledger.recurring_income:.2f}, "
            f"expenses {ledger.recurring_expenses:.2f}, balance {recurring:+.2f}."
        )
    lines += [
        "",
        "## Income",
        "",
        *_table(
            [ledger.last_month_income, ledger.year_income, ledger.last_year_income],
            ["Last month", f"{year} so far", f"{int(year) - 1}" if year.isdigit() else "Last year"],
        ),
        "",
        "## Expenses",
        "",
        *_table(
            [ledger.last_month_expenses, ledger.year_expenses, ledger.last_year_expenses],
            ["Last month", f"{year} so far", f"{int(year) - 1}" if year.isdigit() else "Last year"],
            recurring=True,
        ),
    ]
    if ledger.total_expenses:
        total = sum(ledger.total_expenses.values())
        lines += [
            "",
            "## Spent since the campaign began",
            "",
            f"{total:,.0f} ducats; the largest: "
            + ", ".join(
                f"{name} {value:,.0f} ({value / total:.0%})"
                for name, value in _sorted(ledger.total_expenses)[:8]
            )
            + ".",
        ]
    if ledger.last_month_income.get("War reparations"):
        lines += [
            "",
            "War reparations are paid for a limited time after a peace (10 years), so that "
            "income will stop.",
        ]
    lines += [
        "",
        "_From the ledger in the save. One-off spending (buildings, raising armies, hiring "
        "advisors, repaid loans and the like) is marked; the recurring balance is what the "
        "treasury gains each month while nothing changes. Last month's totals match the "
        "game's ledger; the category names follow the game's English ones._",
    ]
    return "\n".join(lines) + "\n"


# --- helpers ---------------------------------------------------------------------------


def _sorted(values: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(values.items(), key=lambda item: -item[1])


def _top(values: dict[str, float], items: int) -> str:
    total = sum(values.values())
    shown = [
        f"{name} {value:.1f}" + (f" ({value / total:.0%})" if total else "")
        for name, value in _sorted(values)[:items]
    ]
    return ", ".join(shown)


def _table(
    columns: list[dict[str, float]], headers: list[str], recurring: bool = False
) -> list[str]:
    names: list[str] = []
    for column in columns:
        names += [name for name, _ in _sorted(column) if name not in names]
    rows = [
        "| Category | " + " | ".join(headers) + " |",
        "| --- |" + " ---: |" * len(headers),
    ]
    for name in names:
        label = name
        if recurring and name not in RECURRING_EXPENSES and name != OTHER:
            label += " (one-off)"
        cells = " | ".join(f"{column.get(name, 0.0):.2f}" for column in columns)
        rows.append(f"| {label} | {cells} |")
    totals = " | ".join(f"**{sum(column.values()):.2f}**" for column in columns)
    rows.append(f"| **Total** | {totals} |")
    return rows
