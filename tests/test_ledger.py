# ruff: noqa: E501  (the fixture keeps the save's ledger arrays on one line each)
"""Income and expenses by category from the ledger in the save (D-052)."""

from pathlib import Path

from chancellor.context.campaign import Campaign
from chancellor.context.ledger import (
    EXPENSES,
    INCOME,
    OTHER,
    budget_line,
    categorise,
    read_ledger,
    render_budget,
)
from chancellor.context.summarizer import summarize
from chancellor.context.tools import Toolbox
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse

# Austria's ledger on the user's 1535.8.2 save, trimmed to the arrays used.
WORLD = """
countries={
    HAB={
        treasury=128.974
        ledger={
            income={ 174.679 114.184 96.022 90.441 0.000 24.030 0.000 0.000 74.830 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 }
            expense={ 73.797 0.000 32.115 0.000 0.000 0.000 247.363 12.258 79.968 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 2.572 475.973 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 }
            lastmonthincome=81.979
            lastmonthincometable={ 24.970 16.354 13.843 12.929 0.000 3.467 0.000 0.000 10.416 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 }
            lastmonthexpense=63.688
            lastmonthexpensetable={ 10.535 0.000 4.585 0.000 0.000 0.000 35.100 1.724 11.376 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.368 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 }
            totalexpensetable={ 3396.929 76.998 2373.019 0.000 171.941 0.000 19393.229 672.449 8184.232 0.000 115.855 1005.180 406.140 190.800 3305.700 0.000 565.784 219.043 360.719 658.073 0.000 0.000 0.000 1723.507 0.000 0.000 0.000 456.442 760.692 0.000 386.329 0.000 0.000 19.764 14.565 0.000 860.400 0.000 }
            lastyearincome={ 292.696 191.907 155.551 154.710 0.000 40.276 0.000 0.000 136.634 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 }
            lastyearexpense={ 129.492 0.000 54.300 0.000 0.000 0.000 485.160 22.869 139.800 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 23.233 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 0.000 }
            last_months_recurring_income=81.979
            last_months_recurring_expenses=63.688
        }
    }
    RAG={ }
}
"""


def _campaign() -> Campaign:
    return Campaign(
        {"player": "HAB", "date": "1535.8.2"}, parse(WORLD), Localisation({"HAB": "Austria"})
    )


def test_the_categories_add_up_to_the_game_totals():
    ledger = read_ledger(_campaign())
    assert round(sum(ledger.last_month_income.values()), 3) == 81.979
    assert round(sum(ledger.last_month_expenses.values()), 3) == 63.688
    assert ledger.last_month_income["Taxation"] == 24.970
    assert ledger.last_month_income["War reparations"] == 10.416
    assert ledger.last_month_expenses["Army maintenance"] == 35.100
    assert ledger.last_month_expenses["Fort maintenance"] == 11.376
    assert ledger.year_expenses["Embrace institution"] == 475.973
    assert ledger.total_expenses["Centre of trade upgrades"] == 860.400
    assert ledger.recurring_income == 81.979


def test_unnamed_slots_are_other_and_the_maps_have_no_gaps_in_use():
    assert categorise([1.0, 0.0, -2.0, 0.5], {0: "A"}) == {"A": 1.0, OTHER: 0.5}
    assert categorise(None, INCOME) == {}
    assert len(INCOME) == 19 and max(EXPENSES) == 37


def test_the_briefing_line_and_the_report():
    campaign = _campaign()
    ledger = read_ledger(campaign)
    line = budget_line(ledger)
    assert line is not None
    assert line.startswith("income from Taxation 25.0 (30%), Production 16.4 (20%)")
    assert "spent on Army maintenance 35.1 (55%)" in line
    text = render_budget(campaign, ledger)
    assert "Last month: income 81.98, expenses 63.69, balance +18.29 ducats." in text
    assert "| Category | Last month | 1535 so far | 1534 |" in text
    assert "| Army maintenance | 35.10 | 247.36 | 485.16 |" in text
    assert "| Embrace institution (one-off) | 0.00 | 475.97 | 0.00 |" in text
    assert "| **Total** | **81.98** | **574.19** | **971.77** |" in text
    assert "45,318 ducats; the largest: Army maintenance 19,393 (43%)" in text
    assert "War reparations are paid for a limited time" in text
    assert "By category: income from Taxation" in summarize(campaign)


def test_no_ledger(tmp_path: Path):
    campaign = _campaign()
    assert budget_line(read_ledger(campaign, "RAG")) is None
    assert "no ledger" in render_budget(campaign, read_ledger(campaign, "RAG"))
    toolbox = Toolbox(campaign, None, tmp_path / "context.json")
    assert toolbox.run("get_budget", {}).startswith("# Budget of Austria (HAB), 1535.8.2")
