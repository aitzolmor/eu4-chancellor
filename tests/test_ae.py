"""The aggressive expansion of a conquest (D-030), on a small world."""

from pathlib import Path

import pytest

from chancellor.context.ae import claimed_provinces, conquest_ae, render_ae_section
from chancellor.context.campaign import Campaign
from chancellor.game.ae_rules import AeRules, admin_efficiency_by_level, parse_positions
from chancellor.game.localisation import Localisation
from chancellor.game.rules import GameRules
from chancellor.save.parser import parse

# HAB (catholic, austrian) takes VEN's Verona (10 dev, a claim) and Friuli (40 dev, a core).
# MLO (catholic, lombard: same culture group as Verona's venetian) is next door; ITA (in
# the Empire? no) is 250 away; FAR is beyond reach. SAV is HAB's ally, LAN its subject.
WORLD = """
countries={
    HAB={ owned_provinces={ 134 } capital=134 religion=catholic primary_culture=austrian
          prestige=50.000 technology={ adm_tech=2 } claim_provinces={ 1 } core_provinces={ 134 2 }
          allies={ SAV } subjects={ LAN }
          active_relations={ } }
    VEN={ owned_provinces={ 1 2 } capital=1 religion=catholic primary_culture=venetian
          active_relations={ HAB={
              opinion={ modifier="aggressive_expansion" current_opinion=-40.0 } } } }
    MLO={ owned_provinces={ 3 } capital=3 religion=catholic primary_culture=lombard }
    ITA={ owned_provinces={ 4 } capital=4 religion=orthodox primary_culture=greek }
    FAR={ owned_provinces={ 5 } capital=5 religion=catholic primary_culture=venetian }
    SAV={ owned_provinces={ 6 } capital=6 religion=catholic primary_culture=lombard allies={ HAB } }
    LAN={ owned_provinces={ 7 } capital=7 religion=catholic primary_culture=venetian overlord=HAB }
}
provinces={
    -134={ owner="HAB" cores={ "HAB" } }
    -1={ owner="VEN" name="Verona" culture=venetian
         base_tax=4.000 base_production=3.000 base_manpower=3.000 }
    -2={ owner="VEN" name="Friuli" culture=venetian cores={ "VEN" "HAB" }
         base_tax=15.000 base_production=15.000 base_manpower=10.000 }
    -3={ owner="MLO" }
    -4={ owner="ITA" }
    -5={ owner="FAR" }
    -6={ owner="SAV" }
    -7={ owner="LAN" }
}
"""

POSITIONS = {
    134: (0, 0),
    1: (100, 0),
    2: (110, 0),
    3: (150, 0),
    4: (350, 0),
    5: (900, 0),
    6: (160, 0),
    7: (120, 0),
}


@pytest.fixture
def campaign() -> Campaign:
    names = {"VEN": "Venice", "HAB": "Austria", "MLO": "Milan"}
    return Campaign({"player": "HAB", "date": "1483.3.2"}, parse(WORLD), Localisation(names))


@pytest.fixture
def ae_rules() -> AeRules:
    return AeRules(admin_efficiency={0: 0.0, 1: 0.0, 2: 0.1}, positions=POSITIONS)


@pytest.fixture
def game_rules() -> GameRules:
    return GameRules(
        culture_groups={
            "venetian": "latin",
            "lombard": "latin",
            "austrian": "germanic",
            "greek": "byzantine",
        },
        religion_groups={"catholic": "christian", "orthodox": "christian"},
    )


def test_base_ae_per_province(campaign, ae_rules, game_rules):
    estimate = conquest_ae(campaign, ae_rules, game_rules, [1, 2])
    # Prestige 50 → -5%; administrative efficiency at adm 2 → -10%.
    assert dict(estimate.reduction) == {"prestige": -0.05, "administrative efficiency": -0.1}
    verona, friuli = estimate.provinces
    assert (verona.core, friuli.core) == (False, True)
    assert verona.base == pytest.approx(10 * 0.6 * 1.0 * 0.85)  # a claim counts fully
    assert friuli.base == pytest.approx(30 * 0.6 * 0.25 * 0.85)  # capped at 30, a core is 1/4


def test_shares_follow_religion_culture_distance_and_relations(campaign, ae_rules, game_rules):
    estimate = conquest_ae(campaign, ae_rules, game_rules, [1])
    added = {r.tag: r.added for r in estimate.receivers}
    base = 10 * 0.6 * 0.85
    # Owner: same religion +50%, same culture +50%, no distance.
    assert added["VEN"] == pytest.approx(base * 2.0)
    # Milan, 50 away: same religion, same culture group, distance rounds down to 0.
    assert added["MLO"] == pytest.approx(base * 1.75)
    # The orthodox country 250 away: other religion group? no, same group (0); greek culture
    # is another group; distance 200 → 1 / (1 + 1.5).
    assert added["ITA"] == pytest.approx(base * 1.0 / 2.5)
    assert "FAR" not in added  # beyond reach
    assert added["SAV"] == pytest.approx(base * 1.75 * 2 / 3)  # an ally takes 2/3
    assert added["LAN"] == pytest.approx(base * 2.0 * 0.1)  # a subject takes a tenth
    assert "HAB" not in added


def test_current_ae_and_crossing_the_threshold(campaign, ae_rules, game_rules):
    estimate = conquest_ae(campaign, ae_rules, game_rules, [1])
    venice = next(r for r in estimate.receivers if r.tag == "VEN")
    assert venice.current == 40
    assert venice.after == pytest.approx(40 + 10 * 0.6 * 0.85 * 2)
    assert [r.tag for r in estimate.crossing()] == ["VEN"]


def test_claimed_provinces_and_the_war_check_section(campaign, ae_rules, game_rules):
    assert claimed_provinces(campaign, "VEN") == [1, 2]
    assert claimed_provinces(campaign, "MLO") == []
    text = render_ae_section(campaign, ae_rules, game_rules, "VEN")
    assert text.startswith("## Aggressive expansion of taking your claims and cores")
    assert "Taking 2 provinces (50 development, 1 of them your cores)" in text
    assert "| Venice (VEN) | 40 |" in text
    assert "would cross it now: Venice" in text
    assert "not yet checked for 1.37" in text
    empty = render_ae_section(campaign, ae_rules, game_rules, "MLO")
    assert "has no claims or cores on Milan's provinces" in empty


def test_province_owners_are_read_without_parsing(campaign):
    owners = campaign.province_owners
    assert owners[1] == "VEN" and owners[134] == "HAB" and len(owners) == 8


def test_rules_are_read_from_the_game_files(tmp_path: Path):
    common = tmp_path / "common"
    (common / "wargoal_types").mkdir(parents=True)
    (common / "wargoal_types" / "w.txt").write_text(
        "take_claim = { attacker = { badboy_factor = 1.0 } }\n"
        "take_core = { attacker = { badboy_factor = 0.3 } }\n",
        encoding="utf-8",
    )
    (common / "static_modifiers").mkdir()
    (common / "static_modifiers" / "s.txt").write_text(
        "prestige = { ae_impact = -0.2 }\n", encoding="utf-8"
    )
    (common / "technologies").mkdir()
    (common / "technologies" / "adm.txt").write_text(
        "monarch_power = ADM\ntechnology = { year = 1350 }\n"
        "technology = { year = 1390 administrative_efficiency = 0.1 }\n",
        encoding="utf-8",
    )
    (common / "defines.lua").write_text("NDefines = {\n\tAE_SAME_CULTURE = 0.6,\n}\n", "utf-8")
    (tmp_path / "map").mkdir()
    (tmp_path / "map" / "positions.txt").write_text(
        "#Stockholm\n1={\n\tposition={\n\t\t3085.000 1723.000 3086.000 1730.000\n\t}\n}\n",
        encoding="utf-8",
    )
    rules = AeRules.load(tmp_path)
    assert (rules.claim_factor, rules.core_factor) == (1.0, 0.3)
    assert rules.prestige_ae_impact == -0.2
    assert rules.define("AE_SAME_CULTURE") == 0.6
    assert rules.define("PO_DEMAND_PROVINCES_AE") == 0.6  # the 1.37 value
    assert rules.admin_efficiency == {0: 0.0, 1: 0.0, 2: 0.1}
    assert rules.positions == {1: (3085.0, 1723.0)}


def test_parsers():
    assert parse_positions("2={ position={ 1.5 -2.0 } }") == {2: (1.5, -2.0)}
    assert admin_efficiency_by_level("technology = { administrative_efficiency = 0.1 }") == {
        0: 0.0,
        1: 0.1,
    }
