import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.conditions import Evaluator, all_of, any_of, negate
from chancellor.game.missions import MissionLibrary, parse_mission_file
from chancellor.game.rules import GameRules
from chancellor.save.parser import parse

# HAB (player, emperor, catholic, austrian, germanic) owns Wien (134, core) and Linz (133,
# not a core). Its vassal BOH owns Prague (266). HUN is its tributary. POL is independent.
WORLD = """
countries={
    HAB={
        owned_provinces={ 134 133 } capital=134 primary_culture=austrian religion=catholic
        technology_group=western government={ government=monarchy
            reform_stack={ reforms={ "monarchy_mechanic" "austrian_archduchy_reform" } } }
        technology={ adm_tech=6 dip_tech=5 mil_tech=6 } num_of_cities=2 stability=1.000
        prestige=50.000 treasury=36.0 raw_development=185.000
        subjects={ BOH HUN } allies={ CAS }
        flags={ hab_flag=1450.1.1 } modifier={ modifier="hab_mod" date=1460.1.1 }
        completed_missions={ hab_first }
        country_missions={ mission_slot={ hab_series } }
        estate={ type="estate_nobles" granted_privileges={ { "estate_nobles_x" 1450.1.1 } } }
        ledger={ lastmonthincome=26.2 }
    }
    BOH={ owned_provinces={ 266 } overlord=HAB primary_culture=czech religion=catholic }
    HUN={ owned_provinces={ 153 } overlord=HAB primary_culture=hungarian religion=catholic }
    POL={ owned_provinces={ 262 } primary_culture=polish religion=catholic }
    CAS={ owned_provinces={ 219 } allies={ HAB } }
    DED={ }
}
provinces={
    -134={ owner="HAB" controller="HAB" cores={ "HAB" } culture=austrian religion=catholic
           hre=yes base_tax=5.000 base_production=6.000 base_manpower=4.000 trade_goods=wine
           discovered_by={ HAB BOH } modifier={ modifier="capital_mod" } }
    -133={ owner="HAB" controller="HAB" cores={ "BOH" } culture=austrian hre=yes }
    -266={ owner="BOH" controller="BOH" cores={ "BOH" } culture=czech hre=yes }
    -153={ owner="HUN" cores={ "HUN" } culture=hungarian }
    -262={ owner="POL" cores={ "POL" } }
    -219={ owner="CAS" cores={ "CAS" } }
}
diplomacy={
    dependency={ first="HAB" second="BOH" subject_type="personal_union" }
    dependency={ first="HAB" second="HUN" subject_type="tributary_state" }
}
empire={ emperor=HAB }
flags={ global_flag=1444.1.1 }
current_age=age_of_discovery
active_war={ name="War" attackers={ "POL" } defenders={ "CAS" } }
"""


@pytest.fixture
def rules() -> GameRules:
    return GameRules(
        culture_groups={"austrian": "germanic", "czech": "west_slavic", "polish": "west_slavic"},
        religion_groups={"catholic": "christian"},
        geography={
            "austria_area": frozenset({134, 133}),
            "bohemia_area": frozenset({266}),
            "german_region": frozenset({134, 133, 266}),
        },
        scripted_triggers={
            "is_free_trigger": {"is_subject": False},
            "parameterised_trigger": {"tag": "$who$"},
        },
    )


@pytest.fixture
def evaluator(rules) -> Evaluator:
    campaign = Campaign(
        {"player": "HAB", "date": "1475.1.1", "dlc_enabled": ["Emperor"]}, parse(WORLD)
    )
    missions = MissionLibrary(
        parse_mission_file("hab_series = { slot = 1 hab_m = { position = 1 } }")
    )
    return Evaluator(campaign, rules, "HAB", missions)


def check(evaluator: Evaluator, script: str, tag: str | None = None):
    return evaluator.country(parse(script), tag)


def test_three_valued_logic():
    assert all_of([True, None]) is None
    assert all_of([False, None]) is False
    assert any_of([False, None]) is None
    assert any_of([True, None]) is True
    assert negate(None) is None


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("tag = HAB", True),
        ("tag = BOH", False),
        ("was_tag = HAB", True),
        ("exists = POL", True),
        ("exists = DED", False),
        ("ai = no", True),
        ('has_dlc = "Emperor"', True),
        ('has_dlc = "Leviathan"', False),
        ("is_at_war = no", True),
        ("primary_culture = austrian", True),
        ("culture_group = germanic", True),
        ("culture_group = west_slavic", False),
        ("religion = catholic", True),
        ("religion_group = christian", True),
        ("technology_group = western", True),
        ("government = monarchy", True),
        ("has_reform = austrian_archduchy_reform", True),
        ("adm_tech = 6", True),
        ("adm_tech = 7", False),
        ("num_of_cities = 2", True),
        ("treasury = 40", False),
        ("total_development = 180", True),
        ("monthly_income = 20", True),
        ("is_subject = no", True),
        ("is_emperor = yes", True),
        ("is_part_of_hre = yes", True),
        ("alliance_with = CAS", True),
        ("overlord_of = BOH", True),
        ("senior_union_with = BOH", True),
        ("has_country_flag = hab_flag", True),
        ("had_country_flag = { flag = hab_flag days = 3650 }", True),
        ("had_country_flag = { flag = hab_flag days = 36500 }", False),
        ("has_global_flag = global_flag", True),
        ("has_country_modifier = hab_mod", True),
        ("current_age = age_of_discovery", True),
        ("has_estate = estate_nobles", True),
        ("has_estate_privilege = estate_nobles_x", True),
        ("mission_completed = hab_first", True),
        ("has_mission = hab_m", True),
        ("has_mission = other_m", False),
        ("capital = 134", True),
        ("normal_or_historical_nations = yes", True),
        ("end_game_tags_blocked = no", True),
        ("map_setup = map_setup_random", False),
        ("some_unsupported_condition = yes", None),
    ],
)
def test_country_conditions(evaluator: Evaluator, script: str, expected):
    assert check(evaluator, script) is expected


def test_logic_blocks(evaluator: Evaluator):
    assert check(evaluator, "NOT = { tag = BOH }") is True
    assert check(evaluator, "NOT = { tag = BOH tag = HAB }") is False  # NOT is NOR
    assert check(evaluator, "OR = { tag = BOH unsupported = yes }") is None
    assert check(evaluator, "OR = { tag = HAB unsupported = yes }") is True
    assert check(evaluator, "AND = { tag = BOH unsupported = yes }") is False
    assert check(evaluator, "custom_trigger_tooltip = { tooltip = x tag = HAB }") is True
    assert (
        check(evaluator, "calc_true_if = { amount = 2 tag = HAB adm_tech = 1 tag = BOH }") is True
    )


def test_if_else(evaluator: Evaluator):
    script = "if = { limit = { tag = BOH } adm_tech = 99 } else = { adm_tech = 1 }"
    assert check(evaluator, script) is True
    script = "if = { limit = { tag = HAB } adm_tech = 99 } else = { adm_tech = 1 }"
    assert check(evaluator, script) is False
    script = "if = { limit = { unsupported = yes } adm_tech = 1 }"
    assert check(evaluator, script) is None


def test_scopes(evaluator: Evaluator):
    assert check(evaluator, "BOH = { is_subject_of = ROOT }") is True
    assert check(evaluator, "BOH = { junior_union_with = ROOT }") is True
    assert check(evaluator, "HUN = { is_subject_of_type = tributary_state }") is True
    assert check(evaluator, "XXX = { tag = XXX }") is False  # tag not in save
    assert check(evaluator, "overlord = { tag = HAB }", tag="BOH") is True
    assert check(evaluator, "emperor = { tag = HAB }", tag="POL") is True
    assert check(evaluator, "ROOT = { tag = HAB }", tag="POL") is True
    assert check(evaluator, "capital_scope = { culture = austrian }") is True


def test_province_ownership(evaluator: Evaluator):
    assert check(evaluator, "owns = 133") is True
    assert check(evaluator, "owns_core_province = 134") is True
    assert check(evaluator, "owns_core_province = 133") is False  # not a core
    assert check(evaluator, "owns_or_non_sovereign_subject_of = 266") is True  # vassal
    assert check(evaluator, "owns_or_non_sovereign_subject_of = 153") is False  # tributary
    assert check(evaluator, "controls = 134") is True


def test_province_conditions(evaluator: Evaluator):
    assert check(evaluator, "134 = { owned_by = ROOT is_core = ROOT hre = yes }") is True
    assert check(evaluator, "134 = { trade_goods = wine base_tax = 5 development = 15 }") is True
    assert check(evaluator, "134 = { has_discovered = ROOT is_capital_of = ROOT }") is True
    assert check(evaluator, "134 = { has_province_modifier = capital_mod }") is True
    assert check(evaluator, "134 = { region = german_region area = austria_area }") is True
    assert check(evaluator, "266 = { country_or_non_sovereign_subject_holds = ROOT }") is True
    assert check(evaluator, "266 = { owner = { is_subject_of = ROOT } }") is True


def test_geography_scopes(evaluator: Evaluator):
    assert check(evaluator, "austria_area = { type = all owned_by = ROOT }") is True
    assert check(evaluator, "german_region = { type = all owned_by = ROOT }") is False
    assert check(evaluator, "german_region = { type = any owned_by = BOH }") is True


def test_province_counts(evaluator: Evaluator):
    script = "num_of_owned_provinces_with = { value = 2 region = german_region }"
    assert check(evaluator, script) is True
    script = "num_of_owned_provinces_with = { value = 2 region = german_region is_core = ROOT }"
    assert check(evaluator, script) is False
    script = (
        "num_of_provinces_owned_or_owned_by_non_sovereign_subjects_with = "
        "{ value = 3 region = german_region }"
    )
    assert check(evaluator, script) is True  # includes the vassal's Prague
    script = "num_of_owned_provinces_with = { value = 1 unsupported = yes }"
    assert check(evaluator, script) is None


def test_scripted_triggers(evaluator: Evaluator):
    assert check(evaluator, "is_free_trigger = yes") is True
    assert check(evaluator, "is_free_trigger = no") is False
    assert check(evaluator, "is_free_trigger = yes", tag="BOH") is False
    assert check(evaluator, "parameterised_trigger = yes") is None


def test_explain_groups_if_chains(evaluator: Evaluator):
    script = parse("tag = HAB if = { limit = { tag = BOH } adm_tech = 99 } else = { adm_tech = 1 }")
    results = evaluator.explain(script)
    assert [(r, k) for r, k, _ in results] == [(True, "tag"), (True, "if")]
    assert set(results[1][2]) == {"if", "else"}


def test_government_attributes(rules: GameRules, evaluator: Evaluator):
    assert evaluator.country({"has_government_attribute": "english_parliament"}) is None
    rules.government_attributes = {
        "austrian_archduchy_reform": {"is_elective": True},
        "monarchy_mechanic": {"maybe_attribute": False},
    }
    assert evaluator.country({"has_government_attribute": "is_elective"}) is True
    assert evaluator.country({"has_government_attribute": "maybe_attribute"}) is None
    assert evaluator.country({"has_government_attribute": "english_parliament"}) is False
