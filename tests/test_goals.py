"""Goal progress: recorded goals tied to measures read from each save (D-061)."""

from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox, ToolInputError
from chancellor.game.localisation import Localisation
from chancellor.player.context import PlayerContextError, PlayerContextStore, SaveKey
from chancellor.player.goals import (
    GoalError,
    Measure,
    from_dict,
    progress,
    render,
    to_dict,
    validate,
)
from chancellor.save.parser import parse

WORLD = """
countries={
    HAB={ owned_provinces={ 1 2 } subjects={ HOL } raw_development=900.0 }
    HOL={ owned_provinces={ 3 } overlord=HAB }
    GEL={ owned_provinces={ 4 } }
    NAP={ owned_provinces={ 5 } overlord=HAB }
}
diplomacy={
    dependency={ first="HAB" second="HOL" subject_type="vassal" }
    dependency={ first="HAB" second="NAP" subject_type="vassal" }
}
provinces={
    -1={ owner="HAB" } -2={ owner="HAB" } -3={ owner="HOL" } -4={ owner="GEL" }
    -5={ owner="NAP" } -6={ }
}
"""
NAMES = {
    "HAB": "Austria",
    "GEL": "Gelre",
    "NAP": "Nápoles",
    "low_countries_region": "Low Countries",
}
GEOGRAPHY = {"low_countries_region": frozenset({1, 3, 4, 6})}


def _campaign() -> Campaign:
    return Campaign({"player": "HAB", "date": "1535.8.2"}, parse(WORLD), Localisation(NAMES))


def test_measures_are_validated_and_round_trip():
    assert validate({"kind": "provinces", "key": "low_countries_region", "count": 3}) == Measure(
        "provinces", "low_countries_region", count=3
    )
    metric = validate(
        {"kind": "metric", "condition": {"metric": "development", "op": ">=", "value": 1000}}
    )
    assert metric.condition["metric"] == "development" and metric.condition["value"] == 1000.0
    for measure in (metric, Measure("country", "GEL", state="gone"), Measure("mission", "hab_x")):
        assert from_dict(to_dict(measure)) == measure
    for bad, message in (
        ({"kind": "war"}, "Unknown kind"),
        ({"kind": "mission"}, "needs a key"),
        ({"kind": "provinces", "key": "x", "count": -1}, "whole number"),
        ({"kind": "country", "key": "GEL", "state": "ally"}, "state is one of"),
        (
            {"kind": "metric", "condition": {"metric": "nope", "op": ">=", "value": 1}},
            "Unknown metric",
        ),
    ):
        with pytest.raises(GoalError, match=message):
            validate(bad)
    assert from_dict({"kind": "war"}) is None  # a stored measure that no longer validates


def test_progress_per_kind():
    campaign = _campaign()
    held = progress(
        campaign, Measure("provinces", "low_countries_region", count=3), geography=GEOGRAPHY
    )
    assert (held.text, held.done) == ("Low Countries: 2 of 3 provinces with subjects", False)
    alone = progress(
        campaign,
        Measure("provinces", "low_countries_region", subjects=False),
        geography=GEOGRAPHY,
    )
    assert alone.text == "Low Countries: 1 of 3 provinces"  # province 6 is owned by nobody
    unknown = progress(campaign, Measure("provinces", "nowhere"), geography=GEOGRAPHY)
    assert unknown.done is None
    gelre = progress(campaign, Measure("country", "GEL", state="gone"))
    assert (gelre.text, gelre.done) == ("Gelre still exists", False)
    naples = progress(campaign, Measure("country", "NAP", state="subject"))
    assert (naples.text, naples.done) == ("Nápoles is your subject", True)
    metric = progress(
        campaign,
        validate(
            {"kind": "metric", "condition": {"metric": "development", "op": ">=", "value": 1000}}
        ),
    )
    assert metric.done is False and "now 900" in metric.text
    missing = progress(campaign, Measure("mission", "hab_x"), missions={})
    assert missing.done is None
    assert (
        render([naples, gelre]) == "1 of 2 reached: ✓ Nápoles is your subject; Gelre still exists"
    )


def test_the_store_ties_measures_to_a_goal(tmp_path: Path):
    store = PlayerContextStore(tmp_path / "context.json")
    key = SaveKey("c1", "HAB", "1535.8.2")
    goal = store.add(key, "goal", "Take the Low Countries")
    note = store.add(key, "note", "x")
    store.track_goal(key, goal.id, [{"kind": "mission", "key": "hab_x"}])
    (entry,) = [e for e in store.view(key).campaign.entries if e.id == goal.id]
    assert entry.track == [{"kind": "mission", "key": "hab_x"}]
    with pytest.raises(PlayerContextError, match="No goal"):
        store.track_goal(key, note.id, [])


def test_the_tool_and_the_context(tmp_path: Path):
    campaign = _campaign()
    toolbox = Toolbox(campaign, None, tmp_path / "context.json")
    toolbox.run("update_player_context", {"action": "add", "kind": "goal", "text": "Take Gelre"})
    context = toolbox.run("get_player_context", {})
    assert "Not measured yet: track_goal can tie it to the save." in context
    goal_id = int(context.split("- #")[1].split(" ")[0])
    reply = toolbox.run(
        "track_goal",
        {"goal": goal_id, "measures": [{"kind": "country", "key": "Gelre", "state": "gone"}]},
    )
    assert reply == f"Goal #{goal_id} measured: 0 of 1 reached: Gelre still exists"
    assert "  - Progress: 0 of 1 reached: Gelre still exists" in toolbox.run(
        "get_player_context", {}
    )
    assert toolbox.player_plan()["entries"][0]["progress"].startswith("0 of 1 reached")
    with pytest.raises(ToolInputError):
        toolbox.run("track_goal", {"goal": goal_id, "measures": []})
    with pytest.raises(ToolInputError, match="No goal"):
        toolbox.run("track_goal", {"goal": 999, "measures": [{"kind": "mission", "key": "x"}]})
