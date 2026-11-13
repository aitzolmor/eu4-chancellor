from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.decisions import check_decisions, render_decisions
from chancellor.game.decisions import DecisionLibrary, parse_decision_file
from chancellor.game.localisation import Localisation
from chancellor.game.rules import GameRules
from chancellor.save.parser import parse

DECISIONS = """
country_decisions = {
    form_germany = {
        major = yes
        potential = { culture_group = germanic NOT = { exists = GER } }
        allow = {
            adm_tech = 5
            owns_core_province = 50
            estate_thing = yes
        }
        effect = { change_tag = GER add_prestige = 25 }
    }
    form_poland = {
        potential = { primary_culture = polish }
        allow = { adm_tech = 1 }
        effect = { if = { limit = { always = yes } change_tag = POL } }
    }
    small_decision = {
        potential = { tag = HAB }
        allow = { treasury = 10 }
        effect = { add_stability = 1 }
    }
    estate_action = {
        potential = { has_unsupported_thing = yes }
        allow = { treasury = 1 }
        effect = { add_stability = 1 }
    }
}
"""

WORLD = """
countries={
    HAB={ owned_provinces={ 134 } capital=134 primary_culture=austrian
          technology={ adm_tech=6 } treasury=36.0 }
    BRA={ owned_provinces={ 50 } primary_culture=austrian }
}
provinces={
    -134={ owner="HAB" cores={ "HAB" } }
    -50={ owner="BRA" cores={ "BRA" } }
}
"""

NAMES = {
    "HAB": "Austria",
    "GER": "Germany",
    "PROV50": "Berlin",
    "form_germany_title": "Form §YGermany§!",
}


@pytest.fixture
def library() -> DecisionLibrary:
    return DecisionLibrary(parse_decision_file(DECISIONS))


@pytest.fixture
def rules() -> GameRules:
    return GameRules(culture_groups={"austrian": "germanic", "polish": "west_slavic"})


@pytest.fixture
def campaign() -> Campaign:
    return Campaign({"player": "HAB", "date": "1475.1.1"}, parse(WORLD), Localisation(NAMES))


def test_parse_decisions(library: DecisionLibrary):
    assert len(library) == 4
    germany = library.get("form_germany")
    assert germany.major
    assert germany.forms == "GER"
    assert library.get("form_poland").forms == "POL"  # found inside an if
    assert library.get("small_decision").forms is None


def test_load_from_game_dir(tmp_path: Path):
    folder = tmp_path / "decisions"
    folder.mkdir()
    (folder / "a.txt").write_text(DECISIONS, encoding="utf-8")
    assert len(DecisionLibrary.load(tmp_path)) == 4
    assert len(DecisionLibrary.load(tmp_path / "missing")) == 0


def test_visible_decisions(campaign, rules, library):
    checks = check_decisions(campaign, rules, library, "HAB")
    names = [c.decision.name for c in checks]
    assert names == ["form_germany", "small_decision"]  # formables first
    assert "form_poland" not in names  # potential is false
    assert "estate_action" not in names  # unknown visibility, not major/formable


def test_requirement_checklist(campaign, rules, library):
    germany = check_decisions(campaign, rules, library, "HAB")[0]
    assert [r.met for r in germany.requirements] == [True, False, None]
    assert (germany.count(True), germany.count(False), germany.count(None)) == (1, 1, 1)
    assert germany.can_take is False
    small = check_decisions(campaign, rules, library, "HAB")[1]
    assert small.can_take is True


def test_formables_only(campaign, rules, library):
    checks = check_decisions(campaign, rules, library, "HAB", formables_only=True)
    assert [c.decision.name for c in checks] == ["form_germany"]


def test_render(campaign, rules, library):
    text = render_decisions(campaign, "HAB", check_decisions(campaign, rules, library, "HAB"))
    assert text.startswith("# Decisions: Austria (HAB), 1475.1.1")
    assert "## Formable nations" in text
    assert "### Form Germany, forms Germany (GER)" in text
    assert "`form_germany`: not yet; 1 met, 1 not met, 1 unchecked." in text
    assert "- [x] Administrative technology 5 or more" in text
    assert "- [ ] Owns Berlin (#50) as a core" in text
    assert "- [?] estate_thing: yes" in text
    assert "  - change_tag: Germany (GER)" in text
    assert "`small_decision`: can be taken now" in text


def test_render_empty(campaign):
    text = render_decisions(campaign, "HAB", [])
    assert "No decisions are available" in text


def test_rules_load(tmp_path: Path):
    (tmp_path / "common" / "cultures").mkdir(parents=True)
    (tmp_path / "common" / "cultures" / "c.txt").write_text(
        "germanic = { graphical_culture = x austrian = { primary = HAB } country = { a = 1 } }",
        encoding="utf-8",
    )
    (tmp_path / "common" / "religions").mkdir(parents=True)
    (tmp_path / "common" / "religions" / "r.txt").write_text(
        "christian = { catholic = { color = { 1 1 1 } } }", encoding="utf-8"
    )
    (tmp_path / "common" / "scripted_triggers").mkdir(parents=True)
    (tmp_path / "common" / "scripted_triggers" / "s.txt").write_text(
        "my_trigger = { tag = HAB }", encoding="utf-8"
    )
    (tmp_path / "common" / "colonial_regions").mkdir(parents=True)
    (tmp_path / "common" / "colonial_regions" / "c.txt").write_text(
        "colonial_x = { color = { 1 1 1 } provinces = { 900 901 } }", encoding="utf-8"
    )
    (tmp_path / "map").mkdir()
    (tmp_path / "map" / "area.txt").write_text("a_area = { 1 2 }\nb_area = { 3 }", "utf-8")
    (tmp_path / "map" / "region.txt").write_text(
        "x_region = { areas = { a_area b_area } }", encoding="utf-8"
    )
    (tmp_path / "map" / "superregion.txt").write_text("x_superregion = { x_region }", "utf-8")
    (tmp_path / "map" / "continent.txt").write_text("europe = { 1 2 3 }", "utf-8")

    rules = GameRules.load(tmp_path)
    assert rules.culture_groups == {"austrian": "germanic"}
    assert rules.religion_groups == {"catholic": "christian"}
    assert rules.scripted_triggers == {"my_trigger": {"tag": "HAB"}}
    assert rules.geography["x_region"] == frozenset({1, 2, 3})
    assert rules.geography["x_superregion"] == frozenset({1, 2, 3})
    assert rules.geography["europe"] == frozenset({1, 2, 3})
    assert rules.geography["colonial_x"] == frozenset({900, 901})
