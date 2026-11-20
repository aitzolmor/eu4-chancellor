"""The briefing's sections for the Empire of China and the shogunate (D-060)."""

from chancellor.context.campaign import Campaign
from chancellor.context.summarizer import _celestial, _Context, _japan
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse

WORLD = """
countries={
    MNG={ subjects={ KHA KOR } government={ reform_stack={ reforms={ celestial_empire } } } }
    KHA={ overlord=MNG }
    KOR={ overlord=MNG }
    ASK={ subjects={ UES } isolationism=1
          government={ reform_stack={ reforms={ monarchy_mechanic shogunate } } } }
    UES={ overlord=ASK isolationism=4 }
    HAB={ }
}
diplomacy={
    dependency={ first="MNG" second="KHA" subject_type="tributary_state" }
    dependency={ first="MNG" second="KOR" subject_type="vassal" }
    dependency={ first="ASK" second="UES" subject_type="daimyo_vassal" }
}
celestial_empire={
    emperor="MNG" imperial_influence=84.200
    passed_reform="seaban_decision"
    decree={ decree_name="proclaim_dynastic_name_decree" decree_date=1532.7.3 }
}
"""
NAMES = {
    "MNG": "Ming",
    "ASK": "Ashikaga",
    "UES": "Uesugi",
    "seaban_decision_title": "Sea Ban",
    "proclaim_dynastic_name_decree": "Proclaimed Dynastic Name",
}


def _section(function, tag: str) -> str:
    campaign = Campaign({"player": tag, "date": "1535.8.2"}, parse(WORLD), Localisation(NAMES))
    return function(_Context(campaign, tag, campaign.country(tag) or {}))


def test_the_emperor_of_china():
    text = _section(_celestial, "MNG")
    assert "- Role: Emperor of China" in text
    assert "- Mandate: 84.2 of 100" in text
    assert "- Celestial reforms passed: 1: Sea Ban" in text
    assert "- Decree in force: Proclaimed Dynastic Name (issued 1532.7.3)" in text
    assert "- Tributaries: 1" in text  # Korea is a vassal here, not a tributary


def test_a_tributary_and_an_outsider():
    text = _section(_celestial, "KHA")
    assert "- Role: tributary of the Emperor" in text and "- Emperor: Ming (MNG)" in text
    assert _section(_celestial, "KOR") == ""  # a vassal of Ming, not a tributary
    assert _section(_celestial, "HAB") == ""


def test_the_shogun_and_its_daimyos():
    shogun = _section(_japan, "ASK")
    assert "- Role: Shogun" in shogun and "- Daimyos: 1: Uesugi (UES)" in shogun
    assert "- Isolationism: 1.0" in shogun
    daimyo = _section(_japan, "UES")
    assert "- Role: daimyo of the Shogun, Ashikaga (ASK)" in daimyo
    assert _section(_japan, "HAB") == "" and _section(_japan, "MNG") == ""
