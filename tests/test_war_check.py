import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.war_check import check_war, render_war_check
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse

# A small world:
#   HAB (player, Emperor, in HRE) with vassal LAN, tributary TRI and ally CAS.
#   BUR (target, in HRE) with ally FRA, a vassal GEL, guarantor ENG and ally SAV,
#   which is also allied to HAB.
#   VEN belongs to a coalition against HAB together with GEN.
#   POL is outside the HRE.
WORLD = """
date=1475.6.21
countries={
    HAB={ owned_provinces={ 134 } capital=134 subjects={ LAN TRI } allies={ CAS SAV }
          coalition_against_us="VEN" coalition_against_us="GEN"
          army={ regiment={ } regiment={ } regiment={ } }
          manpower=50.000 max_manpower=60.000 raw_development=190.000
          technology={ mil_tech=6 } }
    LAN={ owned_provinces={ 1 } overlord=HAB army={ regiment={ } } manpower=5.000 }
    TRI={ owned_provinces={ 2 } overlord=HAB manpower=1.000 }
    CAS={ owned_provinces={ 3 } allies={ HAB } army={ regiment={ } regiment={ } }
          manpower=20.000 }
    SAV={ owned_provinces={ 4 } allies={ HAB BUR } manpower=3.000 }
    BUR={ owned_provinces={ 192 } capital=192 subjects={ GEL } allies={ FRA SAV }
          army={ regiment={ } regiment={ } } manpower=10.000 max_manpower=20.000
          raw_development=250.000 technology={ mil_tech=6 } }
    GEL={ owned_provinces={ 5 } overlord=BUR manpower=2.000 }
    FRA={ owned_provinces={ 183 } allies={ BUR } army={ regiment={ } regiment={ } }
          navy={ ship={ } army={ regiment={ } regiment={ } } } manpower=40.000 }
    ENG={ owned_provinces={ 236 } manpower=15.000 }
    VEN={ owned_provinces={ 112 } capital=112 army={ regiment={ } } manpower=8.000 }
    GEN={ owned_provinces={ 101 } army={ regiment={ } } manpower=6.000 }
    POL={ owned_provinces={ 262 } capital=262 manpower=20.000 }
    DED={ }
}
diplomacy={
    dependency={ first="HAB" second="LAN" subject_type="vassal" }
    dependency={ first="HAB" second="TRI" subject_type="tributary_state" }
    dependency={ first="BUR" second="GEL" subject_type="vassal" }
    dependency={ first="HAB" second="OLD" subject_type="vassal" end_date=1460.1.1 }
    guarantee={ first="ENG" second="BUR" }
    guarantee={ first="POL" second="BUR" end_date=1470.1.1 }
}
empire={ emperor=HAB }
provinces={
    -134={ hre=yes }
    -192={ hre=yes }
    -112={ }
    -262={ }
}
active_war={ name="Polish war" attackers={ POL } defenders={ GEN } }
"""


@pytest.fixture
def campaign() -> Campaign:
    meta = {"player": "HAB", "date": "1475.6.21"}
    names = {"HAB": "Austria", "BUR": "Burgundy", "FRA": "France", "VEN": "Venice"}
    return Campaign(meta, parse(WORLD), Localisation(names))


def roles(people):
    return {p.tag: (p.roles, p.likelihood) for p in people}


def test_defenders_of_burgundy(campaign: Campaign):
    check = check_war(campaign, "BUR")
    defenders = roles(check.defenders)
    assert defenders["BUR"] == (["target"], "certain")
    assert defenders["GEL"] == (["subject (vassal)"], "certain")
    assert defenders["FRA"] == (["ally"], "likely")
    assert defenders["ENG"] == (["guarantor"], "possible")
    assert "POL" not in defenders  # expired guarantee


def test_attackers_include_subjects_and_allies(campaign: Campaign):
    attackers = roles(check_war(campaign, "BUR").attackers)
    assert attackers["HAB"] == (["attacker"], "certain")
    assert attackers["LAN"] == (["subject (vassal)"], "certain")
    assert attackers["TRI"] == (["subject (tributary state)"], "possible")
    assert attackers["CAS"] == (["ally"], "likely")


def test_ally_of_both_sides_is_neutral(campaign: Campaign):
    check = check_war(campaign, "BUR")
    assert "SAV" in roles(check.neutral)
    assert "SAV" not in roles(check.attackers)
    assert "SAV" not in roles(check.defenders)


def test_emperor_attacking_member_gets_note_not_defender(campaign: Campaign):
    check = check_war(campaign, "BUR")
    assert "HAB" not in roles(check.defenders)
    assert any("is the Emperor" in note for note in check.notes)


def test_emperor_defends_member_against_outsider(campaign: Campaign):
    check = check_war(campaign, "BUR", attacker="POL")
    assert roles(check.defenders)["HAB"] == (["Holy Roman Emperor"], "possible")
    assert any("POL" in note and "already at war" in note for note in check.notes)


def test_coalition_joins_when_a_member_is_attacked(campaign: Campaign):
    check = check_war(campaign, "VEN")
    defenders = roles(check.defenders)
    assert defenders["VEN"][1] == "certain"
    assert defenders["GEN"] == (["coalition member"], "certain")
    assert any("coalition of 2 countries" in note for note in check.notes)


def test_attacking_own_subject_is_flagged(campaign: Campaign):
    check = check_war(campaign, "LAN")
    assert "LAN" not in roles(check.attackers)
    assert any("cannot be attacked by their overlord" in note for note in check.notes)


def test_dead_countries_are_left_out(campaign: Campaign):
    check = check_war(campaign, "BUR")
    everyone = roles(check.attackers) | roles(check.defenders) | roles(check.neutral)
    assert "DED" not in everyone


def test_participant_strength(campaign: Campaign):
    burgundy = next(p for p in check_war(campaign, "BUR").defenders if p.tag == "BUR")
    assert burgundy.regiments == 2
    assert burgundy.manpower == 10.0
    assert burgundy.max_manpower == 20.0
    assert burgundy.development == 250.0
    assert burgundy.mil_tech == 6


def test_totals(campaign: Campaign):
    check = check_war(campaign, "BUR")
    expected = check.totals("defenders", worst_case=False)
    worst = check.totals("defenders", worst_case=True)
    assert (expected.regiments, expected.countries) == (6, 3)  # BUR 2, FRA 4 (2 at sea), GEL 0
    assert worst.countries == 4  # + ENG
    assert worst.manpower == pytest.approx(10 + 2 + 40 + 15)


def test_self_war_rejected(campaign: Campaign):
    with pytest.raises(ValueError):
        check_war(campaign, "HAB")


def test_unknown_country_rejected(campaign: Campaign):
    with pytest.raises(KeyError):
        check_war(campaign, "XXX")


def test_render(campaign: Campaign):
    text = render_war_check(campaign, check_war(campaign, "BUR"))
    assert text.startswith("# War check: Austria (HAB) vs Burgundy (BUR), 1475.6.21")
    assert "| Defenders | 3 | 6 | 52.0k | 6 | 67.0k |" in text
    assert "| France (FRA) | ally | likely | 4 |" in text
    assert "## Tied to both sides" in text
    assert "Likelihoods are estimates" in text


def test_coalition_written_as_list_is_accepted(campaign: Campaign):
    campaign.country("HAB")["coalition_against_us"] = ["VEN", "GEN"]
    assert "GEN" in roles(check_war(campaign, "VEN").defenders)


def test_attacking_an_ally_keeps_sides_apart(campaign: Campaign):
    check = check_war(campaign, "CAS")  # CAS and HAB are allied
    assert "HAB" not in roles(check.defenders)
    assert "CAS" not in roles(check.attackers)
    assert any("currently allied with the attacker" in note for note in check.notes)


def test_truce_with_the_target_is_reported(campaign: Campaign):
    campaign.country("HAB")["active_relations"] = {
        "BUR": {"truce": True, "last_war": "1475.6.21", "last_warscore": 41}
    }
    check = check_war(campaign, "BUR")
    assert check.truce is not None
    assert (check.truce.last_war, check.truce.warscore) == ("1475.6.21", 41)
    text = render_war_check(campaign, check)
    assert (
        "**Truce: Austria and Burgundy are under a truce since 1475.6.21 (war score 41), "
        "ends around 1484.7.28 (estimate). Declaring war now means breaking it.**"
    ) in text
    assert check_war(campaign, "VEN").truce is None


def test_participants_with_a_truce_with_the_other_side_are_noted(campaign: Campaign):
    # France defends Burgundy but is under a truce with Austria; its end is unknown.
    campaign.country("FRA")["active_relations"] = {"HAB": {"truce": True}}
    notes = check_war(campaign, "BUR").notes
    assert "France (FRA) has a truce with Austria: end unknown." in notes
