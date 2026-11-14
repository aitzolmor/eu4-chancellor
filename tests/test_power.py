"""Monarch power: costs from the game's rules applied to a small save (D-029).

The rules were checked against the game's own tooltips for Austria on 1483.3.2:
administrative 7 costs 677, diplomatic 7 costs 653, military 8 costs 1194; +6/+8/+8 a
month; 3 of 5 leaders without upkeep. :func:`test_austria_1483_matches_the_game`
rebuilds that case.
"""

from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.power import months_until_affordable, power_report, render_power
from chancellor.game.localisation import Localisation
from chancellor.game.power_rules import PowerRules, TechLevel, parse_technology_file
from chancellor.save.parser import parse

# Austria on 1483.3.2, trimmed to what the costs depend on: ruler 3/3/2 (recorded as an
# heir who came to the throne), military focus, 100 power projection, a diplomat advisor
# of skill 2 hired in its capital, three generals, two diplomatic ideas, two active
# modifiers that change technology costs, corruption and innovativeness. Its neighbour
# BOH already has administrative and diplomatic technology 7.
WORLD = """
date=1483.3.2
countries={
    HAB={
        owned_provinces={ 134 133 } capital=134 neighbours={ BOH }
        technology={ adm_tech=6 dip_tech=6 mil_tech=7 }
        institutions={ 1 1 0 }
        powers={ 51 64 394 } stability=1.000 national_focus=MIL
        current_power_projection=100.000 corruption=0.395 innovativeness=1.710
        active_idea_groups={ HAB_ideas=0 diplomatic_ideas=2 }
        modifier={ modifier="narrowminded_modifier" date=1490.1.1 }
        modifier={ modifier="warriors_do_not_read_books" date=1490.1.1 }
        modifier={ modifier="poor_iron" date=1490.1.1 }
        monarch={ id=3666 type=48 }
        advisor={ id=21352 type=51 }
        leader={ id=1 type=49 } leader={ id=2 type=49 } leader={ id=3 type=49 }
        history={
            1440.2.22={ heir={ name="Ladislaus" ADM=3 DIP=3 MIL=2 id={ id=3666 type=48 } } }
            1456.11.18={ monarch_heir={ name="Ladislaus" ADM=3 DIP=3 MIL=2
                         id={ id=3666 type=48 } } }
            1458.1.1={ leader={ name="Georg" type=general fire=2 shock=1 maneuver=1 siege=2
                       personality=strict_drillmaster_personality id={ id=1 type=49 } } }
            1460.1.1={ leader={ name="Ladislav" type=general fire=2 shock=2 id={ id=2 type=49 } } }
            1470.1.1={ leader={ name="Ernst" type=general shock=4 maneuver=1 siege=1
                       id={ id=3 type=49 } } }
        }
    }
    BOH={ owned_provinces={ 266 } technology={ adm_tech=7 dip_tech=7 mil_tech=6 } }
}
provinces={
    -134={ owner="HAB" history={ 1479.5.12={ advisor={ name="Heinrich" type=diplomat skill=2
           id={ id=21352 type=51 } } } } }
    -133={ owner="HAB" }
}
empire={ emperor=HAB }
"""

# The game's technology years, from tech 0 (1350) on.
YEARS = [1350, 1390, 1420, 1440, 1453, 1466, 1479, 1492, 1505, 1518]


def _levels(institutions: dict[int, dict[str, float]] | None = None) -> list[TechLevel]:
    return [TechLevel(i, year, (institutions or {}).get(i, {})) for i, year in enumerate(YEARS)]


@pytest.fixture
def rules() -> PowerRules:
    return PowerRules(
        techs={"adm": _levels(), "dip": _levels(), "mil": _levels()},
        institutions=["feudalism", "renaissance", "new_world_i"],
        advisor_categories={"diplomat": "dip"},
        idea_categories={"diplomatic_ideas": "dip"},
        tech_cost_modifiers={
            "narrowminded_modifier": {"technology_cost": 0.05},
            "warriors_do_not_read_books": {
                "adm_tech_cost_modifier": 0.1,
                "dip_tech_cost_modifier": 0.1,
            },
        },
    )


@pytest.fixture
def campaign() -> Campaign:
    names = {
        "narrowminded_modifier": "Aumento de intolerantes e intransigentes",
        "warriors_do_not_read_books": "Los guerreros no leen libros",
        "renaissance": "Renaissance",
    }
    return Campaign({"player": "HAB", "date": "1483.3.2"}, parse(WORLD), Localisation(names))


def test_austria_1483_matches_the_game(campaign, rules):
    report = power_report(campaign, rules)
    assert {c: t.cost for c, t in report.techs.items()} == {"adm": 677, "dip": 653, "mil": 1194}
    assert report.monthly == {"adm": 6, "dip": 8, "mil": 8}
    assert (report.free_leaders, report.leader_upkeep) == (3, 0)


def test_technology_parts_are_the_games(campaign, rules):
    report = power_report(campaign, rules)
    adm = report.techs["adm"]
    assert (adm.level, adm.year) == (7, 1479)  # the one after level 6
    assert dict(adm.parts) == {
        "increase over time": 0.027,
        "Aumento de intolerantes e intransigentes": 0.05,
        "Los guerreros no leen libros": 0.1,
        "corruption": 0.003,  # 0.395 corruption, cut to a thousandth
        "innovativeness": -0.001,  # 1.71 innovativeness, cut to a thousandth
        "a neighbour already has it": -0.05,
    }
    dip = dict(report.techs["dip"].parts)
    assert dip["2 diplomatic ideas"] == pytest.approx(-0.04)  # ideas of its own category only
    mil = report.techs["mil"]
    assert (mil.level, mil.year) == (8, 1492)
    assert dict(mil.parts)["9 years ahead of its time"] == pytest.approx(0.9)  # whole years
    assert dict(mil.parts)["increase over time"] == 0.038
    assert "a neighbour already has it" not in dict(mil.parts)


def test_institutions_not_embraced_raise_the_cost(campaign, rules):
    rules.techs["adm"] = _levels({6: {"feudalism": 0.5, "renaissance": 0.3}})
    campaign.country("HAB")["institutions"] = [1, 0, 0]
    parts = dict(power_report(campaign, rules).techs["adm"].parts)
    assert parts["Renaissance not embraced"] == 0.3
    assert "feudalism not embraced" not in parts


def test_monthly_gain_and_leader_upkeep(campaign, rules):
    report = power_report(campaign, rules)
    assert dict(report.monthly_parts["mil"]) == {
        "base": 3,
        "ruler": 2,
        "national focus": 2,
        "power projection 50+": 1,
    }
    assert dict(report.monthly_parts["dip"])["advisors"] == 2
    # Without power projection: one free leader fewer and no +1 a month.
    campaign.country("HAB")["current_power_projection"] = 0.0
    report = power_report(campaign, rules)
    assert report.monthly == {"adm": 5, "dip": 7, "mil": 6}
    assert (report.free_leaders, report.leader_upkeep) == (2, 1)


def test_people_are_read_from_country_and_province_history(campaign, rules):
    report = power_report(campaign, rules)
    assert [p.name for p in report.leaders] == ["Georg", "Ladislav", "Ernst"]
    assert report.leaders[1].detail == "fire/shock/maneuver/siege 2/2/0/0"  # zeros omitted
    assert [(p.name, p.kind) for p in report.advisors] == [("Heinrich", "diplomat")]


def test_waiting_lets_the_ahead_of_time_penalty_shrink(campaign, rules):
    report = power_report(campaign, rules)
    # The game's tooltip expects January 1492 for administrative 7 (no penalty to shrink).
    assert months_until_affordable(report, "adm") == 105
    # Military 8 gets cheaper every year until 1492, so it comes before the 100 months
    # the game's tooltip expects at today's cost.
    months = months_until_affordable(report, "mil")
    mil = report.techs["mil"]
    assert months is not None and months < 100
    assert 394 + 8 * months >= mil.cost_after(months)
    assert 394 + 8 * (months - 1) < mil.cost_after(months - 1)


def test_render(campaign, rules):
    text = render_power(power_report(campaign, rules))
    assert "## Monarch power: what it buys" in text
    assert "| Points | 51 | 64 | 394 |" in text
    assert "| Monthly gain (est.) | +6 | +8 | +8 |" in text
    assert "| Next technology | 7: ~677 | 7: ~653 | 8: ~1194 |" in text
    assert "9 years ahead of its time +90.0%" in text
    assert "so the leaders cost no upkeep now" in text
    assert "Can be bought now: a general (it may cost upkeep: the known free pool is full)." in text
    assert "Heinrich (diplomat, skill 2, +2 dip a month)" in text


def test_last_level_has_no_next_technology(campaign, rules):
    campaign.country("HAB")["technology"]["dip_tech"] = len(YEARS)
    report = power_report(campaign, rules)
    assert "dip" not in report.techs
    assert "none left" in render_power(report)


def test_rules_are_read_from_the_game_files(tmp_path: Path):
    common = tmp_path / "common"
    (common / "technologies").mkdir(parents=True)
    (common / "technologies" / "mil.txt").write_text(
        "monarch_power = MIL\n"
        "technology = { year = 1350 }\n"
        "technology = { year = 1390 expects_institution = { feudalism = 0.25 } }\n",
        encoding="utf-8",
    )
    (common / "institutions").mkdir()
    (common / "institutions" / "i.txt").write_text(
        "feudalism = { history = { } }\nrenaissance = { history = { } }\n", encoding="utf-8"
    )
    (common / "advisortypes").mkdir()
    (common / "advisortypes" / "a.txt").write_text(
        "philosopher = { monarch_power = ADM }\n", encoding="utf-8"
    )
    (common / "ideas").mkdir()
    (common / "ideas" / "i.txt").write_text(
        "diplomatic_ideas = { category = DIP }\nHAB_ideas = { start = { } }\n", encoding="utf-8"
    )
    (common / "event_modifiers").mkdir()
    (common / "event_modifiers" / "e.txt").write_text(
        "slow = { technology_cost = 0.05 }\nunrelated = { prestige = 1 }\n", encoding="utf-8"
    )
    (common / "static_modifiers").mkdir()
    (common / "static_modifiers" / "s.txt").write_text(
        "base_values = { free_leader_pool = 1 }\nemperor = { free_leader_pool = 2 }\n"
        "power_projection_25 = { free_leader_pool = 1 }\n"
        "corruption = { all_power_cost = 2.0 }\ninnovativeness = { all_power_cost = -0.2 }\n",
        encoding="utf-8",
    )
    (common / "defines.lua").write_text(
        'NDefines = {\n\tSTART_DATE = "1444.11.11",\n\tEND_DATE = "1821.1.2",\n'
        "\tPS_ADVANCE_TECH = 700,\t-- comment\n\tIDEA_TO_TECH = -0.03,\n}\n",
        encoding="utf-8",
    )
    rules = PowerRules.load(tmp_path)
    assert rules.define("PS_ADVANCE_TECH") == 700
    assert rules.define("IDEA_TO_TECH") == -0.03
    assert rules.define("PS_BUY_IDEA") == 400  # not in the file: the 1.37 value
    assert [(t.level, t.year, t.institutions) for t in rules.techs["mil"]] == [
        (0, 1350, {}),
        (1, 1390, {"feudalism": 0.25}),
    ]
    assert rules.institutions == ["feudalism", "renaissance"]
    assert rules.advisor_categories == {"philosopher": "adm"}
    assert rules.idea_categories == {"diplomatic_ideas": "dip"}
    assert rules.tech_cost_modifiers == {"slow": {"technology_cost": 0.05}}
    assert (rules.base_free_leaders, rules.emperor_free_leaders) == (1, 2)
    assert (rules.corruption_power_cost, rules.innovativeness_power_cost) == (2.0, -0.2)
    assert rules.start_year == pytest.approx(1444 + 10 / 12 + 10 / 365)
    assert rules.end_year == pytest.approx(1821 + 1 / 365)


def test_parse_technology_file_without_category():
    assert parse_technology_file("technology = { year = 1400 }")[0] is None
