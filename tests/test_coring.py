"""The cost of coring a province (D-033), on a small world."""

from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.coring import coring_costs, render_coring
from chancellor.game.coring_rules import CoringRules, IdeaGroup, parse_idea_group
from chancellor.game.localisation import Localisation
from chancellor.game.rules import GameRules
from chancellor.save.parser import parse

# Austria in 1492, at war: Friaul (12 development) and Treviso (20) are territories in the
# Veneto area; Celje (9, claimed) sits in a state. Vienna is a core.
WORLD = """
countries={
    HAB={ owned_provinces={ 134 111 1774 4751 } capital=134 war_exhaustion=1.049
          innovativeness=7.78 technology={ adm_tech=6 } core_provinces={ 134 } }
}
provinces={
    -134={ owner="HAB" name="Wien" cores={ "HAB" } base_tax=8 base_production=8 base_manpower=8 }
    -111={ owner="HAB" name="Friaul" cores={ "VEN" }
           base_tax=5.000 base_production=5.000 base_manpower=2.000 }
    -1774={ owner="HAB" name="Treviso" cores={ "VEN" } claims={ "TNT" }
            base_tax=7.000 base_production=9.000 base_manpower=4.000 }
    -4751={ owner="HAB" name="Celje" cores={ "CLI" } claims={ "HAB" }
            base_tax=3.000 base_production=4.000 base_manpower=2.000 }
}
map_area_data={
    veneto_area={ state={ country_state={ country="VEN" } } }
    carniola_area={ state={ country_state={ country="HAB" } } }
}
"""


@pytest.fixture
def campaign() -> Campaign:
    return Campaign({"player": "HAB", "date": "1492.2.2"}, parse(WORLD), Localisation())


@pytest.fixture
def game_rules() -> GameRules:
    return GameRules(geography={"veneto_area": [111, 1774], "carniola_area": [4751]})


@pytest.fixture
def rules() -> CoringRules:
    return CoringRules(admin_efficiency={6: 0.0})


def test_costs_match_the_games_tooltips(campaign, rules, game_rules):
    costs = {c.name: c for c in coring_costs(campaign, rules, game_rules)}
    assert set(costs) == {"Friaul", "Treviso", "Celje"}  # Wien is a core already
    friaul, treviso = costs["Friaul"], costs["Treviso"]
    # War exhaustion 1.049 x 3% → +3.1%, innovativeness 7.78 → -0.7% (cut to a thousandth).
    assert friaul.parts == [("war exhaustion", 0.031), ("innovativeness", -0.007)]
    assert (friaul.cost, friaul.months, friaul.territory) == (61, 37, True)
    assert (treviso.cost, treviso.territory, treviso.claim) == (102, True, False)


def test_a_claim_and_a_state(campaign, rules, game_rules):
    celje = next(c for c in coring_costs(campaign, rules, game_rules) if c.name == "Celje")
    assert (celje.territory, celje.claim) == (False, True)
    # 9 development x 10 x (1 + 0.031 - 0.007 - 0.1), full price in a state.
    assert celje.cost == round(90 * 0.924)
    assert celje.months == round(36 * 0.924)


def test_render(campaign, rules, game_rules):
    line = render_coring(coring_costs(campaign, rules, game_rules))
    assert line.startswith("- Coring: Friaul 61 adm, 37 months (territory, half price)")
    assert "war exhaustion +3.1%" in line
    assert render_coring([]) == ""


def test_country_parts_from_ideas_reforms_and_privileges(rules, game_rules):
    world = """
    countries={ HAB={ owned_provinces={ 999 } active_idea_groups={ HAB_ideas=0 adm_ideas=7 }
        government={ reform_stack={ reforms={ monarchy_mechanic strong_duchies } } }
        estate={ type=estate_nobles granted_privileges={ { estate_nobles_land 1450.1.1 } } } } }
    provinces={ -999={ owner="HAB" base_tax=10 base_production=0 base_manpower=0 } }
    """
    campaign = Campaign({"player": "HAB"}, parse(world), Localisation())
    rules.idea_groups = {
        "HAB_ideas": IdeaGroup(start=-0.1, ideas=[-0.2] * 7, bonus=-0.5),
        "adm_ideas": IdeaGroup(ideas=[0, -0.25, 0, 0, 0, 0, 0], bonus=-0.05),
    }
    rules.government_reforms = {"strong_duchies": 0.05}
    rules.privileges = {"estate_nobles_land": -0.1}
    (cost,) = coring_costs(campaign, rules, game_rules)
    assert dict(cost.parts) == pytest.approx(
        {"HAB ideas": -0.1, "adm ideas": -0.3, "strong duchies": 0.05, "estate nobles land": -0.1}
    )
    # Not in a known area: priced as a state. Summed parts -45%.
    assert cost.cost == round(100 * 0.55)


def test_modifiers_never_cut_below_the_floor(rules, game_rules):
    world = """
    countries={ HAB={ owned_provinces={ 999 } modifier={ modifier=cheap_cores } } }
    provinces={ -999={ owner="HAB" base_tax=40 base_production=0 base_manpower=0 } }
    """
    campaign = Campaign({"player": "HAB"}, parse(world), Localisation())
    rules.modifiers = {"cheap_cores": -2.0}
    (cost,) = coring_costs(campaign, rules, game_rules)
    # Development is capped at 30; the summed modifiers stop at -80%.
    assert cost.cost == round(10 * 30 * 0.2)
    assert cost.months == 7  # 36 x 0.2, above the minimum of 6


def test_rules_are_read_from_the_game_files(tmp_path: Path):
    common = tmp_path / "common"
    for folder in ("ideas", "static_modifiers", "government_reforms", "estate_privileges"):
        (common / folder).mkdir(parents=True)
    (common / "defines.lua").write_text(
        "NDefines = {\n\tPS_MAKE_PROVINCE_CORE = 12,\n\tMONTHS_TO_CORE = 30,\n}\n", "utf-8"
    )
    (common / "ideas" / "i.txt").write_text(
        "adm_ideas = { category = ADM bonus = { core_creation = -0.05 }\n"
        "  a = { global_tax_modifier = 0.1 } b = { core_creation = -0.25 } }\n"
        "plain_ideas = { category = DIP a = { diplomats = 1 } }\n",
        encoding="utf-8",
    )
    (common / "static_modifiers" / "s.txt").write_text(
        "war_exhaustion = { core_creation = 0.04 }\n"
        "corruption = { all_power_cost = 0.9 }\n"
        "overextension = { core_creation = 0.5 }\n",
        encoding="utf-8",
    )
    (common / "government_reforms" / "g.txt").write_text(
        "strong_duchies = { modifiers = { core_creation = 0.05 } }\n", encoding="utf-8"
    )
    (common / "estate_privileges" / "e.txt").write_text(
        "land = { benefits = { core_creation = -0.1 } penalties = { } }\n", encoding="utf-8"
    )
    rules = CoringRules.load(tmp_path)
    assert rules.define("PS_MAKE_PROVINCE_CORE") == 12
    assert rules.define("MONTHS_TO_CORE") == 30
    assert rules.define("CORE_HAD_CLAIM") == 0.1  # the 1.37 value
    assert rules.idea_groups == {"adm_ideas": IdeaGroup(0.0, [0.0, -0.25], -0.05)}
    assert rules.war_exhaustion == 0.04
    assert rules.corruption_power_cost == 0.9
    assert rules.modifiers == {"overextension": 0.5}
    assert rules.government_reforms == {"strong_duchies": 0.05}
    assert rules.privileges == {"land": -0.1}


def test_parse_idea_group():
    assert parse_idea_group({"start": {"core_creation": -0.1}}) == IdeaGroup(-0.1, [], 0.0)
    assert parse_idea_group({"category": "MIL", "a": {"discipline": 0.05}}) is None
    assert parse_idea_group("not a block") is None
