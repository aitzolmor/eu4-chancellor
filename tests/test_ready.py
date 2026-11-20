"""Alerts for missions and nations that became claimable (D-055)."""

from pathlib import Path

from chancellor.context.alerts import ReadyNow, campaign_alerts, ready_now
from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.game.decisions import DecisionLibrary, parse_decision_file
from chancellor.game.localisation import Localisation
from chancellor.game.missions import MissionLibrary, parse_mission_file
from chancellor.game.rules import GameRules
from chancellor.player.journal import changes, take_snapshot
from chancellor.save.parser import parse

MISSIONS = """
hab_series = {
    slot = 1
    hab_emperor = { position = 1 trigger = { is_emperor = yes } }
    hab_rich = { position = 2 trigger = { treasury = 1000 } }
    hab_odd = { position = 3 trigger = { unsupported_trigger = yes } }
}
"""
DECISIONS = """
country_decisions = {
    form_big = {
        major = yes
        potential = { NOT = { tag = BIG } }
        allow = { is_emperor = yes }
        effect = { change_tag = BIG }
    }
    form_huge = {
        potential = { NOT = { tag = HUG } }
        allow = { treasury = 1000 }
        effect = { change_tag = HUG }
    }
}
"""
NAMES = {
    "HAB": "Austria",
    "hab_emperor_title": "Holy Roman Emperor",
    "hab_rich_title": "A rich realm",
    "form_big_title": "Form the Big Empire",
}


def _campaign(treasury: float = 100.0) -> Campaign:
    world = parse(
        f"""
        countries={{ HAB={{
            treasury={treasury} country_missions={{ mission_slot={{ hab_series }} }}
        }} }}
        empire={{ emperor=HAB }}
        """
    )
    return Campaign({"player": "HAB", "date": "1500.1.1"}, world, Localisation(NAMES))


def _ready(campaign: Campaign) -> ReadyNow:
    return ready_now(
        campaign,
        GameRules(),
        MissionLibrary(parse_mission_file(MISSIONS)),
        DecisionLibrary(parse_decision_file(DECISIONS)),
    )


def test_only_what_is_certainly_met_is_ready():
    ready = _ready(_campaign())
    assert ready.missions == ["hab_emperor"]  # hab_odd is unknown, hab_rich unmet
    assert ready.formables == ["form_big"]
    assert _ready(_campaign(treasury=2000)).missions == ["hab_emperor", "hab_rich"]


def test_the_panel_alerts():
    campaign = _campaign()
    alerts = campaign_alerts(campaign, ready=_ready(campaign))
    texts = {a.kind: (a.severity, a.text) for a in alerts}
    assert texts["formable_ready"] == ("medium", "Can be taken now: Form the Big Empire")
    assert texts["missions_ready"] == ("info", "1 mission can be completed: Holy Roman Emperor")
    assert "missions_ready" not in {a.kind for a in campaign_alerts(campaign)}


def test_the_journal_says_what_became_ready():
    poor, rich = _campaign(), _campaign(treasury=2000)
    before = take_snapshot(poor, ready=_ready(poor))
    after = take_snapshot(rich, ready=_ready(rich))
    assert after["ready"] == {
        "missions": ["hab_emperor", "hab_rich"],
        "formables": ["form_big", "form_huge"],
    }
    news = changes(before, after, rich)
    assert "Mission ready: A rich realm" in news
    assert "Can now be taken: form huge" in news  # no localisation: the key, readable
    assert not any("ready" in line for line in changes(after, after, rich))
    backfilled = take_snapshot(poor)  # no game data: nothing to compare
    assert "ready" not in backfilled
    assert not any("ready" in line for line in changes(backfilled, after, rich))


def test_the_toolbox_computes_it_once_and_only_with_the_game_files(tmp_path: Path):
    assert Toolbox(_campaign(), None, tmp_path / "context.json").ready() is None
    toolbox = Toolbox(_campaign(), tmp_path, tmp_path / "context.json")
    toolbox.__dict__["_ready_now"] = ReadyNow(missions=["hab_emperor"])  # cached
    assert toolbox.ready() == ReadyNow(missions=["hab_emperor"])
