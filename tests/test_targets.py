import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.targets import (
    Quota,
    find_targets,
    provinces_in,
    render_targets,
    wanted_provinces,
)
from chancellor.game.decisions import DecisionLibrary, parse_decision_file
from chancellor.game.localisation import Localisation
from chancellor.game.missions import MissionLibrary, parse_mission_file
from chancellor.game.rules import GameRules
from chancellor.save.parser import parse

RULES = GameRules(
    culture_groups={"austrian": "germanic"},
    geography={
        "venetia_area": frozenset({112, 108}),
        "bohemia_area": frozenset({266}),
        "iberia_region": frozenset({219, 220}),
        "europe": frozenset(range(1, 500)),  # too broad to be a target
    },
)


def ids(script: str) -> set[int]:
    return provinces_in(parse(script), RULES)


# --- extracting provinces from conditions --------------------------------------------


def test_owns_style_conditions():
    assert ids("owns_core_province = 50 owns = 57 controls = 65") == {50, 57, 65}
    assert ids("OR = { owns_core_province = 1868 owns_core_province = 70 }") == {1868, 70}


def test_province_counts_expand_areas():
    script = "num_of_owned_provinces_with = { value = 2 area = venetia_area }"
    assert ids(script) == {112, 108}


def test_scopes_only_count_when_about_ownership():
    assert ids("266 = { owned_by = ROOT }") == {266}
    assert ids("bohemia_area = { type = all country_or_non_sovereign_subject_holds = ROOT }") == {
        266
    }
    assert ids("266 = { culture = czech }") == set()  # not about ownership
    assert ids("iberia_region = { type = all religion = catholic }") == set()


def test_area_mentioned_outside_counts_is_ignored():
    assert ids("capital_scope = { area = venetia_area }") == set()


def test_huge_geography_is_ignored():
    assert ids("num_of_owned_provinces_with = { value = 5 region = europe }") == set()


def quotas(script: str) -> dict[int, Quota | None]:
    return wanted_provinces(parse(script), RULES)


def test_counted_conditions_keep_their_quota():
    script = "num_of_owned_provinces_with = { value = 1 region = iberia_region }"
    assert quotas(script) == {
        219: Quota(1, ("iberia_region",), 2, False),
        220: Quota(1, ("iberia_region",), 2, False),
    }


def test_quota_inside_or_is_optional():
    script = """
    OR = {
        legitimacy = 100
        num_of_owned_provinces_with = { value = 1 region = iberia_region }
    }
    """
    assert all(q is not None and q.optional for q in quotas(script).values())


def test_count_of_every_province_is_no_quota():
    script = "num_of_owned_provinces_with = { value = 2 area = venetia_area }"
    assert quotas(script) == {112: None, 108: None}


def test_province_named_on_its_own_wins_over_a_quota():
    script = """
    owns = 219
    num_of_owned_provinces_with = { value = 1 region = iberia_region }
    """
    found = quotas(script)
    assert found[219] is None
    assert found[220] == Quota(1, ("iberia_region",), 2, False)


# --- the report ------------------------------------------------------------------------

MISSIONS = """
hab_series = {
    slot = 1
    hab_venice = {
        position = 1
        trigger = { num_of_provinces_owned_or_owned_by_non_sovereign_subjects_with = {
            value = 2 area = venetia_area } }
    }
    hab_locked = {
        position = 2
        required_missions = { hab_venice }
        trigger = { owns = 999 }
    }
}
"""

DECISIONS = """
country_decisions = {
    form_germany = {
        potential = { culture_group = germanic }
        allow = { owns_core_province = 50 owns_core_province = 266 }
        effect = { change_tag = GER }
    }
}
"""

WORLD = """
countries={
    HAB={ owned_provinces={ 134 } core_provinces={ 134 133 } claim_provinces={ 300 }
          primary_culture=austrian subjects={ BOH } allies={ BRA }
          coalition_against_us="VEN"
          country_missions={ mission_slot={ hab_series } }
          army={ regiment={ } regiment={ } regiment={ } regiment={ } } }
    BOH={ owned_provinces={ 266 } overlord=HAB }
    BRA={ owned_provinces={ 50 } allies={ HAB } army={ regiment={ } } }
    VEN={ owned_provinces={ 112 108 } army={ regiment={ } regiment={ } regiment={ }
          regiment={ } regiment={ } regiment={ } } }
    SAL={ owned_provinces={ 133 } army={ regiment={ } } }
    POL={ owned_provinces={ 300 } army={ regiment={ } regiment={ } } }
}
provinces={
    -134={ owner="HAB" cores={ "HAB" } }
    -133={ owner="SAL" cores={ "HAB" "SAL" }
           base_tax=3.000 base_production=3.000 base_manpower=2.000 }
    -266={ owner="BOH" cores={ "BOH" } base_tax=5.000 }
    -50={ owner="BRA" cores={ "BRA" } base_tax=4.000 }
    -112={ owner="VEN" base_tax=10.000 }
    -108={ owner="VEN" base_tax=5.000 }
    -300={ owner="POL" base_tax=2.000 }
    -999={ owner="POL" }
}
diplomacy={ dependency={ first="HAB" second="BOH" subject_type="vassal" } }
"""


@pytest.fixture
def report():
    campaign = Campaign(
        {"player": "HAB", "date": "1475.1.1"},
        parse(WORLD),
        Localisation({"HAB": "Austria", "VEN": "Venice", "PROV112": "Venezia"}),
    )
    missions = MissionLibrary(parse_mission_file(MISSIONS))
    decisions = DecisionLibrary(parse_decision_file(DECISIONS))
    return campaign, find_targets(campaign, RULES, missions, decisions)


def by_owner(report):
    return {t.owner: t for t in report[1].targets}


def test_targets_grouped_by_owner(report):
    targets = by_owner(report)
    assert set(targets) == {"VEN", "BOH", "BRA", "SAL", "POL"}
    assert targets["VEN"].provinces == [108, 112]
    assert targets["VEN"].development == 15
    assert targets["VEN"].reasons == ["mission: hab venice"]
    assert targets["SAL"].reasons == ["cores"]
    assert targets["POL"].reasons == ["claims"]  # the locked mission's province is not listed
    assert targets["POL"].provinces == [300]
    assert targets["BRA"].reasons == ["formable: GER"]


def test_relations_and_flags(report):
    targets = by_owner(report)
    assert targets["BOH"].relation == "subject"
    assert targets["BRA"].relation == "ally"
    assert targets["BOH"].peaceful and targets["BRA"].peaceful
    assert targets["VEN"].coalition
    assert not targets["SAL"].coalition


def test_war_odds(report):
    targets = by_owner(report)
    salzburg = targets["SAL"]
    assert (salzburg.attacker_regiments, salzburg.defender_regiments) == (5, 1)  # HAB + ally BRA
    assert salzburg.odds == 5
    assert targets["VEN"].odds < 1
    assert targets["BOH"].attacker_regiments == 0  # no war check for subjects


def test_order(report):
    order = [t.owner for t in report[1].targets]
    assert order[:2] == ["BOH", "BRA"]  # peaceful first, by development
    assert order.index("SAL") < order.index("VEN")  # favourable before unfavourable


def test_render(report):
    campaign, result = report
    text = render_targets(campaign, result)
    assert text.startswith("# Expansion targets: Austria (HAB), 1475.1.1")
    assert "## War targets" in text
    assert "| 1 | SAL (SAL) | 1 | 8 | cores | 5 vs 1 | 5.0x |  |" in text
    assert "## Hard targets (defenders outnumber you)" in text
    assert (
        "| Venice (VEN) | 2 | 15 | hab venice | 5 vs 6 | 0.8x | in a coalition against you |"
        in text
    )
    assert "BOH (BOH) (your subject: annex or integrate)" in text
    assert "Venezia" in text


def test_no_targets():
    campaign = Campaign(
        {"player": "HAB", "date": "1475.1.1"},
        parse("countries={ HAB={ owned_provinces={ 1 } } }"),
    )
    result = find_targets(campaign, RULES, MissionLibrary(), DecisionLibrary())
    assert result.targets == []
    assert "No foreign-held provinces" in render_targets(campaign, result)


def test_owners_under_a_truce_come_last_with_the_estimated_end(report):
    campaign, _ = report
    # HAB beat SAL two years ago with full war score: a 15-year truce.
    campaign.country("HAB")["active_relations"] = {
        "SAL": {"truce": True, "last_war": "1473.1.1", "last_warscore": 100}
    }
    missions = MissionLibrary(parse_mission_file(MISSIONS))
    decisions = DecisionLibrary(parse_decision_file(DECISIONS))
    result = find_targets(campaign, RULES, missions, decisions)
    targets = {t.owner: t for t in result.targets}
    assert targets["SAL"].truce is not None
    assert targets["SAL"].truce.estimated_end == "1488.1.1"
    order = [t.owner for t in result.targets]
    assert order.index("VEN") < order.index("SAL")  # even a hard target beats a truced one
    text = render_targets(campaign, result)
    assert "| 2 | SAL (SAL) | 1 | 8 | cores | 5 vs 1 | 5.0x | truce until about 1488.1.1 |" in text
    assert "| 1 | POL (POL) |" in text  # the weaker target without a truce goes first
    hidden = render_targets(campaign, result, top=1)
    assert (
        "Not shown because of a truce or an allied defender: "
        "SAL (SAL) (truce until about 1488.1.1)." in hidden
    )


def test_owners_defended_by_your_own_ally_come_last(report):
    campaign, _ = report
    # SAL becomes a subject of BRA, which is allied with HAB: BRA must defend SAL.
    campaign.country("SAL")["overlord"] = "BRA"
    campaign.country("BRA")["subjects"] = ["SAL"]
    missions = MissionLibrary(parse_mission_file(MISSIONS))
    decisions = DecisionLibrary(parse_decision_file(DECISIONS))
    result = find_targets(campaign, RULES, missions, decisions)
    targets = {t.owner: t for t in result.targets}
    assert targets["SAL"].allied_defenders == ["BRA"]
    assert targets["SAL"].blocked and not targets["POL"].blocked
    order = [t.owner for t in result.targets]
    assert order.index("VEN") < order.index("SAL")
    text = render_targets(campaign, result)
    assert "| defended by your ally BRA |" in text


def test_reasons_describe_quotas_and_merge_named_provinces():
    missions = MissionLibrary(
        parse_mission_file(
            """
            hab_series = {
                slot = 1
                hab_iberia = {
                    position = 1
                    trigger = { OR = {
                        legitimacy = 100
                        num_of_owned_provinces_with = { value = 1 region = iberia_region }
                    } }
                }
                hab_venice = {
                    position = 2
                    trigger = {
                        owns = 112
                        num_of_owned_provinces_with = { value = 1 area = venetia_area }
                    }
                }
            }
            """
        )
    )
    world = WORLD.replace("    POL={", "    CAS={ owned_provinces={ 219 220 } } POL={").replace(
        "    -999={",
        '    -219={ owner="CAS" base_tax=1.000 } -220={ owner="CAS" base_tax=1.000 } -999={',
    )
    campaign = Campaign(
        {"player": "HAB", "date": "1475.1.1"},
        parse(world),
        Localisation({"iberia_region": "Iberia", "venetia_area": "Veneto"}),
    )
    result = find_targets(campaign, RULES, missions, DecisionLibrary({}))
    targets = {t.owner: t for t in result.targets}
    assert targets["CAS"].reasons == [
        "mission: hab iberia (any 1 of 2 provinces in Iberia; one of several ways)"
    ]
    assert targets["VEN"].reasons == [
        "mission: hab venice (specific provinces, plus any 1 of 2 provinces in Veneto)"
    ]
