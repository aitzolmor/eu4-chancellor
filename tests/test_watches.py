"""Watches: conditions on the save checked on each new save (D-041)."""

from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox, ToolInputError
from chancellor.game.localisation import Localisation
from chancellor.player.context import PlayerContextStore, SaveKey, refresh_watches
from chancellor.player.watches import (
    METRICS,
    Condition,
    Watch,
    WatchError,
    check,
    describe,
    from_dict,
    to_dict,
    validate_condition,
)
from chancellor.save.parser import parse

# Austria (player) next to France. France holds 60 AE against Austria and is at war with
# Burgundy; Austria and Castile are allied; Austria has a truce with Venice.
WORLD = """
countries={
    HAB={ owned_provinces={ 1 } treasury=150.5 manpower=20.0 max_manpower=40.0
          powers={ 300 120 999 } stability=1.000 war_exhaustion=2.5
          overextension_percentage=0.25 prestige=40.0 raw_development=300.0
          technology={ adm_tech=9 dip_tech=8 mil_tech=10 }
          army={ regiment={ type=x } regiment={ type=x } regiment={ type=x } }
          active_relations={ VEN={ truce=yes last_war="1518.1.1" last_warscore=20 } } }
    FRA={ owned_provinces={ 2 } treasury=900.0 war_exhaustion=6.0
          coalition_against_us="ENG" coalition_against_us="BUR"
          army={ regiment={ type=x } }
          active_relations={ HAB={
              opinion={ modifier="aggressive_expansion" current_opinion=-60.0 } } } }
    CAS={ owned_provinces={ 3 } }
    VEN={ owned_provinces={ 4 } active_relations={ HAB={ truce=yes last_war="1518.1.1" } } }
    BUR={ owned_provinces={ 5 } }
}
diplomacy={
    alliance={ first="HAB" second="CAS" start_date=1500.1.1 }
}
active_war={ name="French war" attackers={ "FRA" } defenders={ "BUR" } }
"""


@pytest.fixture
def campaign() -> Campaign:
    names = {"FRA": "Francia", "HAB": "Austria", "VEN": "Venecia", "CAS": "Castilla"}
    meta = {"player": "HAB", "date": "1520.7.1", "campaign_id": "c1"}
    return Campaign(meta, parse(WORLD), Localisation(names))


def _value(campaign: Campaign, metric: str, country: str = "", other: str = ""):
    op = "is" if METRICS[metric].kind == "bool" else ">="
    watch = Watch(1, "x", [Condition(metric, op, True if op == "is" else 0, country, other)])
    return check(campaign, watch)[0].value


def test_metrics_read_the_save(campaign):
    assert _value(campaign, "treasury") == 150.5
    assert _value(campaign, "manpower_percent") == 50.0
    assert (_value(campaign, "adm_power"), _value(campaign, "mil_power")) == (300, 999)
    assert _value(campaign, "overextension") == 25.0
    assert (_value(campaign, "adm_tech"), _value(campaign, "mil_tech")) == (9, 10)
    assert _value(campaign, "regiments") == 3
    assert _value(campaign, "war_exhaustion", "FRA") == 6.0
    assert _value(campaign, "ae", "FRA") == 60.0
    assert _value(campaign, "countries_at_coalition_ae") == 1
    assert _value(campaign, "coalition_members", "FRA") == 2
    assert _value(campaign, "at_war", "FRA") is True
    assert _value(campaign, "at_war") is False
    assert _value(campaign, "truce", "VEN") is True
    assert _value(campaign, "truce", "FRA") is False
    assert _value(campaign, "allied", "CAS") is True
    assert _value(campaign, "exists", "CAS") is True
    assert _value(campaign, "exists", "XXX") is False
    assert _value(campaign, "year") == pytest.approx(1520.5)
    assert _value(campaign, "treasury", "XXX") is None  # an unknown country


def test_war_odds_come_from_the_war_check(campaign):
    odds = _value(campaign, "war_odds", "FRA")
    assert odds == pytest.approx(3 / 1)  # Austria's 3 regiments against France's 1
    assert _value(campaign, "war_odds") is None  # the player against itself


def test_conditions_are_validated():
    condition = validate_condition({"metric": "treasury", "op": ">=", "value": 200})
    assert condition == Condition("treasury", ">=", 200.0)
    # Common slips in a tool call are forgiven (D-041).
    assert validate_condition({"metric": "War_Odds", "op": ">", "value": "1.5"}) == Condition(
        "war_odds", ">=", 1.5
    )
    assert validate_condition({"metric": "truce", "op": "==", "value": "false"}) == Condition(
        "truce", "is", False
    )
    assert validate_condition({"metric": "at_war", "op": "is", "value": 1}).value is True
    for raw, message in (
        ({"metric": "gold", "op": ">=", "value": 1}, "Unknown metric 'gold'"),
        ({"metric": "at_war", "op": ">=", "value": 1}, "use op 'is'"),
        ({"metric": "treasury", "op": "is", "value": True}, "use op '>=' or '<='"),
        ({"metric": "treasury", "op": ">=", "value": 1, "other": "FRA"}, "leave `other` out"),
        ("treasury >= 1", "is an object"),
    ):
        with pytest.raises(WatchError, match=message):
            validate_condition(raw)


def test_describe_and_round_trip(campaign):
    condition = Condition("war_odds", ">=", 1.5, "FRA")
    assert describe(condition, campaign) == "war_odds of Francia with you >= 1.5"
    assert describe(Condition("at_war", "is", True, "FRA"), campaign) == (
        "at_war of Francia is true"
    )
    watch = Watch(3, "France weak", [condition], "1520.7.1", "2026-11-16", "")
    assert from_dict(to_dict(watch)) == watch
    assert from_dict({"id": 4, "conditions": [{"metric": "gone"}]}).conditions == []


def test_a_watch_fires_once_and_keeps_its_date(campaign, tmp_path: Path):
    store = PlayerContextStore(tmp_path / "context.json")
    key = SaveKey("c1", "HAB", "1520.7.1")
    rich = store.add_watch(key, "200 ducats", [Condition("treasury", ">=", 200)])
    poor = store.add_watch(key, "100 ducats", [Condition("treasury", ">=", 100)])
    results = dict((w.id, w.fired) for w, _ in refresh_watches(store, key, campaign))
    assert results == {rich.id: "", poor.id: "1520.7.1"}
    later = SaveKey("c1", "HAB", "1521.1.1")
    fired = {w.id: w.fired for w, _ in refresh_watches(store, later, campaign)}
    assert fired[poor.id] == "1520.7.1"  # fired once: the date stays


def test_the_create_watch_tool(campaign, tmp_path: Path):
    toolbox = Toolbox(campaign, None, tmp_path / "context.json")
    reply = toolbox.run(
        "create_watch",
        {
            "description": "Francia débil",
            "conditions": [
                {"metric": "war_odds", "op": ">=", "value": 5, "country": "Francia"},
                {"metric": "at_war", "op": "is", "value": True, "country": "Francia"},
            ],
        },
    )
    assert reply.startswith("Watch #1 set: Francia débil. war_odds of Francia with you >= 5")
    assert "now 3" in reply and "It fires on the first save" in reply
    context = toolbox.run("get_player_context", {})
    assert "## Watches" in context and "- #1 waiting: Francia débil." in context
    hint = toolbox.run("get_country_briefing", {}).rstrip().splitlines()[-1]
    assert "1 watches waiting" in hint
    with pytest.raises(ToolInputError, match="Unknown metric"):
        toolbox.run("create_watch", {"description": "x", "conditions": [{"metric": "gold"}]})
    with pytest.raises(ToolInputError, match="at least one condition"):
        toolbox.run("create_watch", {"description": "x", "conditions": []})
    with pytest.raises(ToolInputError, match="is a watch"):
        toolbox.run("update_player_context", {"action": "replace", "entry": 1, "text": "y"})
    assert "Francia débil" in toolbox.run("get_player_context", {})  # kept after the refusal


def test_a_fired_watch_is_announced_in_the_planning_tools(campaign, tmp_path: Path):
    toolbox = Toolbox(campaign, None, tmp_path / "context.json")
    toolbox.run(
        "create_watch",
        {
            "description": "100 ducats",
            "conditions": [{"metric": "treasury", "op": ">=", "value": 100}],
        },
    )
    hint = toolbox.run("get_country_briefing", {}).rstrip().splitlines()[-1]
    assert "WATCH FIRED #1 at 1520.7.1: 100 ducats (tell the player)." in hint
    assert "**FIRED** at 1520.7.1" in toolbox.run("get_player_context", {})
