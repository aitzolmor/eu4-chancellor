"""Casus belli from the probe mod's log, in the war check and the targets (D-051)."""

from pathlib import Path

from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.context.war_check import check_war, render_war_check
from chancellor.game.localisation import Localisation
from chancellor.live.casus_belli import (
    CasusBelliLookup,
    cb_name,
    describe_against,
    load_casus_belli,
    short_against,
)
from chancellor.save.parser import parse

WORLD = """
countries={
    HAB={ owned_provinces={ 134 } capital=134 subjects={ HUN } army={ regiment={ } } }
    HUN={ owned_provinces={ 153 } overlord=HAB }
    POL={ owned_provinces={ 262 } capital=262 army={ regiment={ } } }
    LIE={ owned_provinces={ 93 } capital=93 }
    TEU={ owned_provinces={ 41 } capital=41 }
}
diplomacy={ dependency={ first="HAB" second="HUN" subject_type="vassal" } }
provinces={ -134={ } -153={ } -262={ } -93={ } -41={ } }
"""

NAMES = {
    "HAB": "Austria",
    "HUN": "Hungría",
    "POL": "Polonia",
    "LIE": "Lieja",
    "TEU": "Orden Teutónica",
    "cb_conquest": "Conquista",
    "cb_humiliate_rotw": "Humillar a su rival",
    "cb_privateers": "Protección del comercio.",
}

# The month before is overwritten by the latest one: TEU had a casus belli in April only.
LOG = """EVENT [1535.04.26]:CHANCELLOR|heartbeat|1535|abril|Austria
EVENT [1535.04.26]:CHANCELLOR|cbtarget|TEU|Orden Teut\xf3nica
EVENT [1535.04.26]:CHANCELLOR|cb|TEU|cb_conquest
EVENT [1535.05.26]:CHANCELLOR|heartbeat|1535|mayo|Austria
EVENT [1535.05.26]:CHANCELLOR|cbtarget|POL|Polonia
EVENT [1535.05.26]:CHANCELLOR|cb|POL|cb_humiliate_rotw
EVENT [1535.05.26]:CHANCELLOR|cbtarget|LIE|Lieja
EVENT [1535.05.26]:CHANCELLOR|cb|LIE|cb_conquest
EVENT [1535.05.26]:CHANCELLOR|cbtarget|TEU|Orden Teut\xf3nica
EVENT [1535.05.26]:CHANCELLOR|subject|HUN|Hungr\xeda
EVENT [1535.05.26]:CHANCELLOR|subcb|POL|Polonia|cb_conquest
"""


def _campaign(date: str = "1535.6.1", player: str = "HAB") -> Campaign:
    return Campaign({"player": player, "date": date}, parse(WORLD), Localisation(NAMES))


def _log(tmp_path: Path, text: str = LOG) -> Path:
    path = tmp_path / "logs" / "game.log"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(text.encode("cp1252"))
    return path


def test_the_latest_check_is_read(tmp_path: Path):
    lookup = load_casus_belli(_campaign(), _log(tmp_path))
    data = lookup.data
    assert data is not None and lookup.reason == ""
    assert data.date == "1535.05.26"
    assert data.against("POL") == [(None, "cb_humiliate_rotw"), ("HUN", "cb_conquest")]
    assert data.against("TEU") == []  # checked in May, nothing found
    assert data.covers("TEU") and not data.covers("FRA")


def test_the_words(tmp_path: Path):
    campaign = _campaign()
    data = load_casus_belli(campaign, _log(tmp_path)).data
    assert data is not None
    assert describe_against(campaign, data, "POL") == (
        "Humillar a su rival (yours); Conquista (Hungría)"
    )
    assert describe_against(campaign, data, "TEU") == "none"
    assert describe_against(campaign, data, "FRA").startswith("not checked")
    assert short_against(campaign, data, "POL") == "Humillar a su rival, Conquista (Hungría)"
    assert (short_against(campaign, data, "TEU"), short_against(campaign, data, "FRA")) == (
        "none",
        "?",
    )
    assert cb_name(campaign, "cb_privateers") == "Protección del comercio"
    assert cb_name(campaign, "cb_border_war") == "border war"  # no localisation


def test_when_the_check_cannot_speak_for_the_save(tmp_path: Path):
    campaign = _campaign()
    assert "no game log" in load_casus_belli(campaign, None).reason
    assert "no game log" in load_casus_belli(campaign, tmp_path / "missing.log").reason
    old_mod = _log(tmp_path, "EVENT [1535.05.26]:CHANCELLOR|heartbeat|1535|mayo|Austria\n")
    assert "no casus belli check" in load_casus_belli(campaign, old_mod).reason
    log = _log(tmp_path)
    other = load_casus_belli(_campaign(player="POL"), log)
    assert other.data is None and "Austria's, not Polonia's" in other.reason
    stale = load_casus_belli(_campaign(date="1540.1.1"), log)
    assert stale.data is None and "too far from the save's date" in stale.reason


def test_the_war_check_shows_them_for_the_player(tmp_path: Path):
    campaign = _campaign()
    lookup = load_casus_belli(campaign, _log(tmp_path))
    text = render_war_check(campaign, check_war(campaign, "POL"), lookup)
    assert (
        "**Casus belli:** Humillar a su rival (yours); Conquista (Hungría) (the probe mod's "
        "check on 1535.05.26;" in text
    )
    assert "War score is not checked; truce" in text
    unknown = render_war_check(
        campaign, check_war(campaign, "POL"), CasusBelliLookup(None, "No log.")
    )
    assert "**Casus belli:** unknown. No log." in unknown
    other = render_war_check(campaign, check_war(campaign, "LIE", "POL"), lookup)
    assert "**Casus belli:**" not in other  # another attacker: the log is the player's
    assert "War score is not checked, nor the casus belli" in other
    assert "**Casus belli:**" not in render_war_check(campaign, check_war(campaign, "POL"))


def test_the_tools_read_the_log(tmp_path: Path):
    toolbox = Toolbox(_campaign(), None, tmp_path / "context.json", _log(tmp_path))
    assert "**Casus belli:** Conquista (yours)" in toolbox.run("check_war", {"target": "LIE"})
    assert toolbox.with_campaign(_campaign()).game_log == toolbox.game_log
    without = Toolbox(_campaign(), None, tmp_path / "context.json")
    assert "**Casus belli:** unknown." in without.run("check_war", {"target": "LIE"})
