"""The live war score from the probe mod, in get_wars and the recommendations (D-063)."""

from pathlib import Path

from chancellor.context.advice import recommend
from chancellor.context.campaign import Campaign
from chancellor.context.guide import steps
from chancellor.context.tools import Toolbox
from chancellor.context.wars import live_score, render_wars, war_reports
from chancellor.game.localisation import Localisation
from chancellor.live.war_score import LiveWarScore, load_war_score
from chancellor.save.parser import parse

# Austria against Poland (with Lithuania), the save of 1537.12.17; the game showed +87.
WORLD = """
countries={ HAB={ } POL={ } LIT={ } }
provinces={ -262={ owner="POL" controller="HAB" base_tax=10 } }
active_war={
    name="Conquista de Barlad"
    history={ 1535.10.12={ add_attacker="HAB" add_defender="POL" } }
    attackers={ "HAB" } defenders={ "POL" "LIT" }
    persistent_attackers={ "HAB" } persistent_defenders={ "POL" "LIT" }
    last_warscore_quarter=87
}
"""
NAMES = {"HAB": "Austria", "POL": "Polonia", "LIT": "Lituania", "PEACETITLE": "Pedir la paz"}
LOG = """EVENT [1537.10.22]:CHANCELLOR|heartbeat|1537|octubre|Austria
EVENT [1537.10.22]:CHANCELLOR|direct|77.999
EVENT [1537.10.22]:CHANCELLOR|ladder|Polonia|75
EVENT [1537.11.22]:CHANCELLOR|heartbeat|1537|noviembre|Austria
EVENT [1537.11.22]:CHANCELLOR|direct|87.999
EVENT [1537.11.22]:CHANCELLOR|ladder|Lituania|-100
EVENT [1537.11.22]:CHANCELLOR|ladder|Polonia|85
"""


def _campaign(date: str = "1537.12.17") -> Campaign:
    return Campaign({"player": "HAB", "date": date}, parse(WORLD), Localisation(NAMES))


def _log(tmp_path: Path, text: str = LOG) -> Path:
    path = tmp_path / "game.log"
    path.write_bytes(text.encode("cp1252"))
    return path


def test_the_latest_months_reading_against_the_war_leader(tmp_path: Path):
    campaign = _campaign()
    lookup = load_war_score(campaign, _log(tmp_path))
    live = lookup.data
    assert live is not None and live.date == "1537.11.22"
    assert (live.direct, live.ladder) == (87.999, {"Lituania": -100.0, "Polonia": 85.0})
    assert live.against(campaign, "POL", wars=1) == (87.999, "exact")
    assert live.against(campaign, "POL", wars=2) == (85.0, "to the nearest 5 below")
    assert live.against(campaign, "LIT", wars=2) is None  # not a war leader: -100


def test_when_the_log_cannot_speak_for_the_save(tmp_path: Path):
    assert "no game log" in load_war_score(_campaign(), None).reason
    fresh = _log(tmp_path, "EVENT [1537.12.1]:CHANCELLOR|treasury|1\n")
    assert "no war score yet" in load_war_score(_campaign(), fresh).reason  # a new game start
    assert "too far" in load_war_score(_campaign("1545.1.1"), _log(tmp_path)).reason


def test_get_wars_shows_the_live_score_beside_the_quarterly_one(tmp_path: Path):
    campaign = _campaign()
    live = load_war_score(campaign, _log(tmp_path)).data
    (war,) = war_reports(campaign)
    assert live_score(war, live, 1, campaign) == (
        "+88 against Polonia (exact, the probe mod on 1537.11.22)"
    )
    text = render_wars(campaign, [war], live=live)
    assert "- War score: +88 against Polonia (exact, the probe mod on 1537.11.22)." in text
    assert "- War score recorded by the game at its last quarterly check: 87." in text
    assert "- We occupy 1 province (" in text  # singular
    without = render_wars(campaign, [war])
    assert "or monthly from the probe mod" in without
    toolbox = Toolbox(campaign, None, tmp_path / "context.json", _log(tmp_path))
    assert "- War score: +88 against Polonia" in toolbox.run("get_wars", {})


def test_peace_is_recommended_from_the_score(tmp_path: Path):
    campaign = _campaign()
    wars = war_reports(campaign)
    live = load_war_score(campaign, _log(tmp_path)).data
    (peace,) = [r for r in recommend(campaign, wars=wars, live=live) if r.kind == "make_peace"]
    assert (peace.priority, peace.target) == ("soon", "POL")  # 88: below 90
    assert peace.reasons[0] == (
        "war score +88 against Polonia (exact, the probe mod on 1537.11.22)"
    )
    (quarterly,) = [r for r in recommend(campaign, wars=wars) if r.kind == "make_peace"]
    assert quarterly.reasons[0] == "war score +87 at the game's last quarterly check"
    losing = LiveWarScore("1537.11.22", -60.0, {})
    (seek,) = [r for r in recommend(campaign, wars=wars, live=losing) if r.kind == "make_peace"]
    assert seek.priority == "now" and seek.action.startswith("Seek a peace with Polonia")
    calm = LiveWarScore("1537.11.22", 20.0, {})
    assert not [r for r in recommend(campaign, wars=wars, live=calm) if r.kind == "make_peace"]
    assert steps(campaign, "make_peace", "POL")[1].startswith("click «Pedir la paz»")


def test_the_recommendations_tool_uses_both(tmp_path: Path):
    toolbox = Toolbox(_campaign(), None, tmp_path / "context.json", _log(tmp_path))
    text = toolbox.run("get_recommendations", {})
    assert "`[make_peace POL]`" in text and "war score +88" in text
    assert "Casus belli need the Chancellor probe mod" in text  # this log has no check
