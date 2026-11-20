"""Guide: the game's screens and buttons for each recommendation (D-059)."""

from chancellor.context.campaign import Campaign
from chancellor.context.guide import UI, steps, ui
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse

# Spanish interface texts, as the game's localisation has them.
NAMES = {
    "POL": "Polonia",
    "hab_milan_title": "Ducado de Milán",
    "HEADER_MISSIONS": "Misiones",
    "HEADER_TECHNOLOGY": "Tecnología",
    "WARTITLE": "Declarar la guerra",
    "CV_BUILD_CORE": "Crear un núcleo",
    "mil_tech": "Tecnología militar",
    "PROV2746": "Vidin",
}


def _campaign() -> Campaign:
    world = parse('countries={ HAB={ } POL={ } } provinces={ -2746={ name="Widin" } }')
    return Campaign({"player": "HAB", "date": "1535.8.2"}, world, Localisation(NAMES))


def test_names_come_from_the_games_language_with_an_english_fallback():
    campaign = _campaign()
    assert ui(campaign, "missions") == "«Misiones»"
    assert ui(campaign, "repay_loan") == "«Repay Loan»"  # no localisation: English
    assert all(isinstance(k, str) and isinstance(f, str) for k, f in UI.values())


def test_steps_per_kind():
    campaign = _campaign()
    assert steps(campaign, "complete_mission", "hab_milan") == [
        "F1 (your country) → «Misiones» tab",
        "click «Ducado de Milán»: it is highlighted when it can be completed",
    ]
    assert steps(campaign, "time_mission", "hab_milan")[-1].startswith("or leave it")
    assert steps(campaign, "buy_technology", "mil") == [
        "F1 (your country) → «Tecnología» tab",
        "click the button under «Tecnología militar»",
    ]
    war = steps(campaign, "declare_war", "POL")
    assert war[0].startswith("click any province of Polonia on the map")
    assert war[1] == "click «Declarar la guerra» and choose the casus belli"
    core = steps(campaign, "core_province", "2746")
    assert core[0].startswith("click Widin on the map")  # the save's name, as on the map
    assert core[1] == "click «Crear un núcleo» in the province window"


def test_no_steps_for_what_is_not_one_action():
    campaign = _campaign()
    assert steps(campaign, "plan_income", None) == []
    assert steps(campaign, "declare_war", None) == []
    assert steps(campaign, "unknown_kind", "X") == []
