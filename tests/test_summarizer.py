import shutil
from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.summarizer import summarize, summarize_save
from chancellor.game.localisation import Localisation
from chancellor.save.loader import load_save

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"
NAMES = {
    "HAB": "Austria",
    "TUR": "Ottomans",
    "BOH": "Bohemia",
    "PROV134": "Wien",
    "PROV150": "Nikopol",
}


@pytest.fixture
def raw(tmp_path: Path):
    path = tmp_path / "mini.eu4"
    shutil.copy(FIXTURE, path)
    return load_save(path)


@pytest.fixture
def campaign(raw) -> Campaign:
    return Campaign.from_raw(raw, Localisation(NAMES))


@pytest.fixture
def briefing(campaign: Campaign) -> str:
    return summarize(campaign)


# --- player briefing -------------------------------------------------------------------


def test_header(briefing: str):
    assert briefing.startswith("# Campaign briefing: Austria (HAB), 1471.10.2")
    assert "Played by the user." in briefing
    assert "- Capital: Wien" in briefing
    assert "Great Power, rank #7 in score" in briefing


def test_ruler_resolved_from_history(briefing: str):
    assert "- Ruler: Ladislaus von Habsburg (3/3/2), age 31" in briefing
    assert "industrious personality" in briefing  # humanised when not localised


def test_economy(briefing: str):
    assert "- Treasury: 36.1 ducats" in briefing
    assert "- Last month balance: +1.7 ducats" in briefing
    assert "- Loans: 2 totalling 176.0 ducats" in briefing


def test_military(briefing: str):
    assert "- Manpower: 63,781 / 63,781" in briefing
    assert "- Land forces: 3 regiments in 2 armies" in briefing
    assert "- Navy: 1 ships in 1 fleets" in briefing


def test_diplomacy_uses_neutral_wording(briefing: str):
    assert "- Rivals: Ottomans (TUR)" in briefing
    assert "- Rivalled by: Ottomans (TUR)" in briefing


def test_only_own_wars_are_listed(briefing: str):
    assert "Austrian Conquest of Nikopol** (HAB is attacker" in briefing
    assert "war goal: cb conquest Nikopol" in briefing
    assert "Unrelated war" not in briefing


def test_key_countries_table(briefing: str):
    header = "| Country | Relation | Development | Regiments | Mil tech | Their opinion of HAB |"
    assert header in briefing
    assert "| Ottomans (TUR) | rival, rivals it, at war | 498 | 2 | 6 | -25" in briefing
    assert "| Bohemia (BOH) | ally, neighbour | 170 | 1 | 5 | +150" in briefing
    assert "| HUN (HUN) | subject, neighbour | 298 | 0 | 5 | +42" in briefing


def test_player_briefing_has_no_relation_section(briefing: str):
    assert "Relation to the player" not in briefing


def test_summarize_save_wrapper(raw):
    assert summarize_save(raw).startswith("# Campaign briefing: HAB (HAB)")
    assert summarize_save(raw, tag="TUR").startswith("# Country briefing: TUR (TUR)")


def test_peace_when_no_wars(tmp_path: Path):
    path = tmp_path / "peace.eu4"
    text = FIXTURE.read_text(encoding="cp1252").split("active_war=")[0]
    path.write_bytes(text.encode("cp1252"))
    assert "At peace." in summarize_save(load_save(path))


# --- other countries -------------------------------------------------------------------


@pytest.fixture
def ottoman(campaign: Campaign) -> str:
    return summarize(campaign, "TUR")


def test_other_country_header(ottoman: str):
    assert ottoman.startswith("# Country briefing: Ottomans (TUR), 1471.10.2")
    assert "AI-controlled country" in ottoman
    assert "The user plays Austria (HAB)." in ottoman


def test_relation_to_player(ottoman: str):
    assert "## Relation to the player" in ottoman
    assert "rivals the player" in ottoman
    assert "rivalled by the player" in ottoman
    assert "borders the player" in ottoman
    assert "at war with the player (Austrian Conquest of Nikopol)" in ottoman
    assert "- Its opinion of HAB: -25" in ottoman


def test_strength_comparison(ottoman: str):
    assert "| | Ottomans | Austria (player) |" in ottoman
    assert "| Development | 498 | 185 |" in ottoman
    assert "| Regiments | 2 | 3 |" in ottoman
    assert "| Treasury | 250.0 ducats | 36.1 ducats |" in ottoman


def test_other_country_lists_player_first_in_key_countries(ottoman: str):
    table = ottoman.split("## Key countries")[1]
    first_row = table.strip().splitlines()[2]
    assert first_row.startswith("| Austria (HAB) | player, rival, at war, neighbour")


def test_ally_of_player_is_reported(campaign: Campaign):
    assert "allied with the player" in summarize(campaign, "BOH")


def test_unknown_tag_raises(campaign: Campaign):
    with pytest.raises(KeyError):
        summarize(campaign, "XXX")


def test_dead_country_is_flagged(campaign: Campaign):
    assert "no longer exists" in summarize(campaign, "OLD")
    assert "no longer exists" not in summarize(campaign, "TUR")


def test_foreign_heir_is_resolved():
    from chancellor.context.summarizer import _find_person

    country = {
        "monarch": {"id": 7, "type": 48},
        "history": {"1514.8.2": {"foreign_heir": {"id": {"id": 7, "type": 48}, "name": "August"}}},
    }
    assert _find_person(country, country["monarch"])["name"] == "August"


# --- Holy Roman Empire -----------------------------------------------------------------

# HAB is Emperor, BOH and SAX are electors (SAX backs Brandenburg), BAV is a plain member
# and FRA lies outside the Empire.
EMPIRE = """
countries={
    HAB={ owned_provinces={ 134 } capital=134 }
    BOH={ owned_provinces={ 266 } capital=266 preferred_emperor="HAB" }
    SAX={ owned_provinces={ 61 } capital=61 preferred_emperor="BRA" }
    BAV={ owned_provinces={ 65 } capital=65 }
    FRA={ owned_provinces={ 183 } capital=183 }
}
provinces={
    -134={ hre=yes } -266={ hre=yes } -61={ hre=yes } -65={ hre=yes } -183={ }
}
empire={
    emperor="HAB" imperial_influence=59.683
    passed_reform=emperor_reichsreform passed_reform=emperor_reichsregiment
    electors={ BOH SAX }
}
"""
EMPIRE_NAMES = {
    "HAB": "Austria",
    "BOH": "Bohemia",
    "SAX": "Saxony",
    "BRA": "Brandenburg",
    "BAV": "Bavaria",
    "FRA": "France",
    "emperor_reichsreform_title": "Call for Reichsreform",
}


@pytest.fixture
def empire() -> Campaign:
    from chancellor.save.parser import parse_lazy

    meta = {"player": "HAB", "date": "1475.6.21"}
    return Campaign(meta, parse_lazy(EMPIRE), Localisation(EMPIRE_NAMES))


def _hre_section(briefing: str) -> str:
    return briefing.split("## Holy Roman Empire", 1)[1].split("\n## ", 1)[0]


def test_emperor_sees_authority_reforms_and_electors(empire: Campaign):
    section = _hre_section(summarize(empire))
    assert "- Role: Emperor" in section
    assert "- Emperor:" not in section
    assert "- Imperial authority: 59.7" in section
    # Localised title when there is one, humanised key otherwise.
    assert "2: Call for Reichsreform, emperor reichsregiment" in section
    assert (
        "- Electors: 2; 1 favours Austria (HAB) (Bohemia); 1 favours Brandenburg (BRA) (Saxony)"
        in section
    )


def test_elector_and_member_see_the_emperor(empire: Campaign):
    assert "- Role: Elector\n- Emperor: Austria (HAB)" in _hre_section(summarize(empire, "BOH"))
    assert "- Role: Member" in _hre_section(summarize(empire, "BAV"))


def test_countries_outside_the_empire_have_no_hre_section(empire: Campaign):
    assert "Holy Roman Empire" not in summarize(empire, "FRA")


# --- aggressive expansion, overextension and monarch power -----------------------------

AE_SAVE = """
countries={
    HAB={ owned_provinces={ 1 } capital=1 allies={ CAS } powers={ 450 79 425 }
          coalition_against_us="VEN" overextension_percentage=0.288 }
    VEN={ owned_provinces={ 2 } active_relations={ HAB={
        opinion={ modifier="aggressive_expansion" current_opinion=-62.898 }
        attitude="attitude_rivalry" } } }
    LAN={ owned_provinces={ 3 } active_relations={ HAB={
        opinion={ modifier="aggressive_expansion" current_opinion=-70.898 }
        attitude="attitude_loyal" } } }
    CAS={ owned_provinces={ 4 } active_relations={ HAB={
        opinion={ modifier="aggressive_expansion" current_opinion=-10.0 } } } }
    TUR={ owned_provinces={ 5 } }
}
diplomacy={ dependency={ first="HAB" second="LAN" subject_type="vassal" } }
"""
AE_NAMES = {
    "HAB": "Austria",
    "VEN": "Venice",
    "LAN": "Florence",
    "CAS": "Castile",
    "attitude_rivalry": "Rivalry",
    "attitude_loyal": "Loyal",
}


@pytest.fixture
def ae() -> Campaign:
    from chancellor.save.parser import parse_lazy

    meta = {"player": "HAB", "date": "1475.6.21"}
    return Campaign(meta, parse_lazy(AE_SAVE), Localisation(AE_NAMES))


def test_aggressive_expansion_section(ae: Campaign):
    briefing = summarize(ae)
    section = briefing.split("## Aggressive expansion", 1)[1].split("\n## ", 1)[0]
    assert "3 countries hold aggressive expansion (AE) against Austria; 2 at 50 or more" in (
        section
    )
    assert "1 are in a coalition against it. AE decays by 2 a year at base." in section
    rows = [line for line in section.splitlines() if line.startswith("| ") and "(" in line]
    assert rows == [
        "| Florence (LAN) | 71 | subject | Loyal |",
        "| Venice (VEN) | 63 | in coalition | Rivalry |",
        "| Castile (CAS) | 10 | ally |  |",
    ]


def test_no_aggressive_expansion_section_without_ae(ae: Campaign):
    assert "Aggressive expansion" not in summarize(ae, "TUR")


def test_overextension_and_monarch_power(ae: Campaign):
    briefing = summarize(ae)
    assert "- Overextension: 29%" in briefing
    assert "- Monarch power (adm/dip/mil): 450/79/425" in briefing
    assert "- Overextension: 0%" in summarize(ae, "TUR")  # the key is omitted at 0


def test_next_imperial_reform_with_the_game_files(empire: Campaign):
    from chancellor.game.imperial_reforms import ImperialReformLibrary, parse_reform_file

    reforms = ImperialReformLibrary(
        parse_reform_file(
            """
            emperor_reichsreform = { empire = hre potential = { has_dlc = "Emperor" } }
            emperor_reichsregiment = { empire = hre potential = { has_dlc = "Emperor" }
                required_reform = emperor_reichsreform emperor = { diplomats = 1 } }
            emperor_reichsstabilitaet = { empire = hre potential = { has_dlc = "Emperor" }
                required_reform = emperor_reichsregiment province = { local_unrest = -2 } }
            """
        )
    )
    empire.meta["dlc_enabled"] = ["Emperor"]
    section = _hre_section(summarize(empire, reforms=reforms))
    assert (
        "- Next reform: emperor reichsstabilitaet (HRE provinces: local unrest -2). "
        "Needs 50 imperial authority, now 59.7, and the electors' votes"
    ) in section
    assert "Next reform" not in _hre_section(summarize(empire))  # no game files, no line
