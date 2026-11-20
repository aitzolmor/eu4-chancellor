"""A country's trade from the save's trade nodes and the game's node map (D-046)."""

from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.context.trade import render_trade, trade_line, trade_report
from chancellor.game.localisation import Localisation
from chancellor.game.trade_nodes import TradeGraph
from chancellor.save.parser import parse

# Pest -> Wien -> Venice (end); Ragusa -> Venice; Wien also -> Saxony (end, elsewhere).
NODES = """
pest = { location = 153 outgoing = { name = "wien" path = { } } }
wien = {
    location = 134
    outgoing = { name = "venice" path = { } }
    outgoing = { name = "saxony" path = { } }
}
ragusa = { location = 137 outgoing = { name = "venice" path = { } } }
venice = { location = 112 end = yes }
saxony = { location = 61 }
"""

# Austria: home in Venice (collecting), a merchant steering in Wien, power in Saxony.
SAVE = """
countries={ HAB={ owned_provinces={ 134 } trade_embargoed_by={ "FRA" } } FRA={ } }
trade={
    node={ definitions="pest" current=2.0 outgoing=8.0 total=100.0 }
    node={ definitions="wien" current=6.8 outgoing=13.2 total=1000.0
           HAB={ val=200.0 province_power=74.0 has_trader=yes type=1 } }
    node={ definitions="ragusa" current=3.0 outgoing=5.0 total=50.0 }
    node={ definitions="venice" current=13.9 total=240.0
           HAB={ val=108.0 province_power=59.0 ship_power=16.0 light_ship=6 money=8.6
                 has_trader=yes has_capital=yes } }
    node={ definitions="saxony" current=15.0 outgoing=0.2 total=400.0
           HAB={ val=40.0 province_power=29.0 } }
}
"""

NAMES = {
    "HAB": "Austria",
    "FRA": "Francia",
    "venice": "Venecia",
    "wien": "Viena",
    "pest": "Pest",
    "ragusa": "Ragusa",
    "saxony": "Sajonia",
}


@pytest.fixture
def graph() -> TradeGraph:
    graph = TradeGraph()
    graph.add_document(NODES)
    return graph


@pytest.fixture
def campaign() -> Campaign:
    return Campaign({"player": "HAB", "date": "1525.9.6"}, parse(SAVE), Localisation(NAMES))


def test_the_node_map(graph):
    assert graph.outgoing["wien"] == ["venice", "saxony"]
    assert graph.ends == {"venice", "saxony"}
    assert graph.upstream("venice") == {"wien": 1, "ragusa": 1, "pest": 2}
    assert sorted(graph.incoming("venice")) == ["ragusa", "wien"]


def test_the_report_orders_home_then_its_feeders(campaign, graph):
    report = trade_report(campaign, graph)
    assert [s.node for s in report.nodes] == ["venice", "wien", "saxony"]
    home, wien, saxony = report.nodes
    assert (home.home, home.merchant, home.light_ships, home.money) == (True, "collecting", 6, 8.6)
    assert home.share == pytest.approx(108 / 240) and home.value == pytest.approx(13.9)
    assert (wien.merchant, wien.steps_to_home, wien.value) == ("steering", 1, 20.0)
    assert saxony.steps_to_home is None
    assert report.home_is_end is True
    assert report.upstream_without_power == [("pest", 10.0, 2), ("ragusa", 8.0, 1)]
    assert report.embargoed_by == ["FRA"]


def test_render(campaign, graph):
    text = render_trade(campaign, trade_report(campaign, graph))
    assert "- Home node: **Venecia** (an end node: its trade goes nowhere else): 45%" in text
    assert "- Merchants placed: 2: Venecia (collecting), Viena (steering)." in text
    assert "- Light ships protecting trade: 6 in Venecia." in text
    assert "- Embargoed by: Francia" in text
    assert "| Viena | 20.0 | 200 | 20% | 74 / 0 | steering | yes, 1 step |" in text
    assert "| Sajonia | 15.2 | 40 | 10% | 29 / 0 | - | no |" in text
    assert "Pest (value 10.0, 2 steps), Ragusa (value 8.0, 1 step)" in text
    line = trade_line(trade_report(campaign, graph))
    assert line.startswith("Trade: home node Venecia, 45% of its power, collecting 8.60")


def test_a_country_without_trade(graph):
    campaign = Campaign({"player": "HAB"}, parse("countries={ HAB={ } }"), Localisation())
    report = trade_report(campaign, graph)
    assert report.home is None and trade_line(report) is None
    assert "No home trade node found" in render_trade(campaign, report)
    with pytest.raises(KeyError):
        trade_report(campaign, graph, "XXX")


def test_the_tool_and_the_briefing_pointer(campaign, tmp_path: Path):
    folder = tmp_path / "game" / "common" / "tradenodes"
    folder.mkdir(parents=True)
    (folder / "00_tradenodes.txt").write_text(NODES, encoding="utf-8")
    toolbox = Toolbox(campaign, tmp_path / "game", tmp_path / "context.json")
    assert toolbox.run("get_trade", {}).startswith("# Trade: Austria (HAB)")
    briefing = toolbox.run("get_country_briefing", {})
    assert "_Trade: home node Venecia, 45% of its power" in briefing
