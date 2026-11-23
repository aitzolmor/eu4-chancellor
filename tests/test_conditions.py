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
        estate={ type="estate_nobles" loyalty=55.5 territory=20.0
                 granted_privileges={ { "estate_nobles_x" 1450.1.1 } } }
        estate={ type="estate_church" loyalty=30.0 territory=15.0 }
        ledger={ lastmonthincome=26.2 last_months_recurring_income=26.2
                 last_months_recurring_expenses=30.0 }
        estimated_monthly_income=3.0 powers={ 120 80 40 } innovativeness=12.5
        active_idea_groups={ HAB_ideas=3 humanist_ideas=7 trade_ideas=2 }
        total_count={ 10 4 2 0 0 0 0 } is_great_power=yes
        rival={ country="POL" date="1450.1.1" } neighbours={ POL BOH }
        active_relations={ POL={ cached_sum=-40 } CAS={ cached_sum=120 } }
        monarch={ id=1 type=48 } heir={ id=2 type=48 } advisor={ id=7 type=51 }
        history={ 1450.1.1={ monarch={ id={ id=1 type=48 } ADM=4 DIP=2 MIL=5 } }
                  1460.1.1={ heir={ id={ id=2 type=48 } ADM=1 DIP=1 MIL=1 female=yes } } }
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
           discovered_by={ HAB BOH } modifier={ modifier="capital_mod" }
           buildings={ temple=yes marketplace=yes }
           history={ 1455.1.1={ advisor={ id={ id=7 type=51 } type=artist skill=2 } } } }
    -133={ owner="HAB" controller="REB" cores={ "BOH" } culture=austrian hre=yes
           religion=protestant }
    -266={ owner="BOH" controller="BOH" cores={ "BOH" } culture=czech hre=yes }
    -153={ owner="HUN" cores={ "HUN" } culture=hungarian }
    -262={ owner="POL" cores={ "POL" } }
    -219={ owner="CAS" cores={ "CAS" } }
}
diplomacy={
    dependency={ first="HAB" second="BOH" subject_type="personal_union" }
    dependency={ first="HAB" second="HUN" subject_type="tributary_state" }
}
empire={ emperor=HAB electors={ BOH } imperial_influence=42.0 passed_reform=reichsreform }
great_powers={ original={ country="HAB" rank=3 } original={ country="CAS" rank=5 } }
map_area_data={ austria_area={ state={ area=austria_area country_state={ country="HAB" } } } }
flags={ global_flag=1444.1.1 }
current_age=age_of_discovery
active_war={ name="War" attackers={ "POL" } defenders={ "CAS" } }
"""


@pytest.fixture
def rules() -> GameRules:
    return GameRules(
        culture_groups={"austrian": "germanic", "czech": "west_slavic", "polish": "west_slavic"},
        religion_groups={"catholic": "christian", "protestant": "christian"},
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
        ("always = yes", True),
        ("always = no", False),
        ("estate_loyalty = { estate = estate_nobles loyalty = 50 }", True),
        ("estate_loyalty = { estate = estate_church loyalty = 50 }", False),
        ("estate_loyalty = { estate = estate_burghers loyalty = 10 }", False),  # no such estate
        ("crown_land_share = 65", True),  # 100 - 20 - 15
        ("crown_land_share = 66", False),
        ("adm = 4", True),
        ("dip = 3", False),
        ("has_female_heir = yes", True),
        ("artist = 2", True),
        ("artist = 3", False),
        ("advisor = artist", True),
        ("advisor = theologian", False),
        ("full_idea_group = humanist_ideas", True),
        ("full_idea_group = trade_ideas", False),
        ("has_idea_group = trade_ideas", True),
        ("great_power_rank = 3", True),
        ("great_power_rank = 2", False),
        ("is_great_power = yes", True),
        ("is_elector = no", True),
        ("imperial_influence = 40", True),
        ("hre_reform_passed = reichsreform", True),
        ("hre_reform_passed = erbkaisertum", False),
        ("has_opinion = { who = CAS value = 100 }", True),
        ("has_opinion = { who = POL value = 0 }", False),
        ("years_of_income = 1", True),  # 36 ducats against 3 a month
        ("years_of_income = 2", False),
        ("is_in_deficit = yes", True),
        ("num_of_cavalry = 4", True),
        ("num_of_cavalry = 5", False),
        ("num_of_rebel_controlled_provinces = 1", True),
        ("adm_power = 100", True),
        ("mil_power = 50", False),
        ("innovativeness = 10", True),
        ("had_global_flag = { flag = global_flag days = 3650 }", True),
        ("hre_size = 1", True),  # only HAB has a capital (Wien, in the Empire)
        ("hre_size = 2", False),
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
    # Without `type` the game checks ANY province (D-054): "the Ottomans own nothing in
    # Europe" is NOT = { europe = { owned_by = TUR } }, not "...own all of it".
    assert check(evaluator, "german_region = { owned_by = BOH }") is True
    assert check(evaluator, "NOT = { german_region = { owned_by = POL } }") is True
    assert check(evaluator, "NOT = { german_region = { owned_by = BOH } }") is False


def test_an_if_chain_is_one_alternative_of_an_or(evaluator: Evaluator):
    # The `if` applies (HAB), so its `else_if` is skipped, not true on its own (D-054).
    script = (
        "OR = { if = { limit = { tag = HAB } adm_tech = 99 } "
        "else_if = { limit = { tag = BOH } adm_tech = 1 } adm_tech = 50 }"
    )
    assert check(evaluator, script) is False
    script = "OR = { if = { limit = { tag = BOH } adm_tech = 99 } else = { adm_tech = 1 } }"
    assert check(evaluator, script) is True  # the else applies


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


def test_country_scopes(evaluator: Evaluator):
    assert check(evaluator, "any_subject_country = { tag = HUN }") is True
    assert check(evaluator, "all_subject_country = { religion = catholic }") is True
    assert check(evaluator, "any_ally = { tag = CAS }") is True
    assert check(evaluator, "any_rival_country = { tag = POL }") is True
    assert check(evaluator, "any_neighbor_country = { tag = HUN }") is False
    assert check(evaluator, "any_country = { tag = POL }") is True
    assert check(evaluator, "any_country = { tag = DED }") is False  # does not exist
    assert check(evaluator, "any_subject_country = { unsupported = yes }") is None
    script = "any_subject_country = { limit = { tag = BOH } is_subject_of_type = tributary_state }"
    assert check(evaluator, script) is False


def test_more_province_conditions(evaluator: Evaluator):
    assert check(evaluator, "134 = { is_state = yes has_owner_religion = yes }") is True
    assert check(evaluator, "133 = { has_owner_religion = no }") is True
    assert check(evaluator, "134 = { culture_group = germanic num_of_buildings_in_province = 2 }")
    assert check(evaluator, "266 = { is_state = no }") is True  # area held by nobody
