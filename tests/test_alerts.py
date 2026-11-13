import pytest

from chancellor.context.alerts import campaign_alerts
from chancellor.context.campaign import Campaign
from chancellor.game.imperial_reforms import ImperialReformLibrary, parse_reform_file
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse_lazy

# HAB: at war with VEN, a coalition of VEN against it, MIL at 60 AE outside it, a truce
# with its rival TUR ending within two years and one with distant ARA, losing money, two
# loans, overextended, negative stability, nearly capped administrative power, Emperor
# with enough authority for the next reform.
SAVE = """
countries={
    HAB={ owned_provinces={ 1 } capital=1 neighbours={ MIL } allies={ BRA }
          rival={ country="TUR" } coalition_against_us="VEN"
          ledger={ lastmonthincome=10.000 lastmonthexpense=12.500 }
          loan={ amount=100.000 } loan={ amount=50.000 }
          overextension_percentage=0.250 war_exhaustion=6.500 stability=-1.000
          powers={ 950 100 200 }
          active_relations={
              TUR={ truce=yes last_war="1475.1.1" last_warscore=0 }
              ARA={ truce=yes last_war="1475.1.1" last_warscore=0 } } }
    VEN={ owned_provinces={ 2 } active_relations={ HAB={
        opinion={ modifier="aggressive_expansion" current_opinion=-70.000 } } } }
    MIL={ owned_provinces={ 3 } active_relations={ HAB={
        opinion={ modifier="aggressive_expansion" current_opinion=-60.000 } } } }
    BRA={ owned_provinces={ 4 } active_relations={ HAB={
        opinion={ modifier="aggressive_expansion" current_opinion=-80.000 } } } }
    TUR={ owned_provinces={ 5 } }
    ARA={ owned_provinces={ 6 } }
    CAS={ owned_provinces={ 7 } }
}
active_war={ name="Venetian War" attackers={ HAB } defenders={ VEN } }
empire={ emperor="HAB" imperial_influence=60.000 passed_reform=emperor_reichsreform }
"""
REFORMS = ImperialReformLibrary(
    parse_reform_file(
        """
        emperor_reichsreform = { empire = hre potential = { has_dlc = "Emperor" } }
        emperor_reichsregiment = { empire = hre potential = { has_dlc = "Emperor" }
            required_reform = emperor_reichsreform }
        """
    )
)
NAMES = {
    "HAB": "Austria",
    "VEN": "Venice",
    "MIL": "Milan",
    "TUR": "Ottomans",
    "emperor_reichsregiment_title": "Instituir Reichsregiment",
}


@pytest.fixture
def campaign() -> Campaign:
    meta = {"player": "HAB", "date": "1478.6.1", "dlc_enabled": ["Emperor"]}
    return Campaign(meta, parse_lazy(SAVE), Localisation(NAMES))


def texts(campaign: Campaign, **kwargs) -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = {}
    for alert in campaign_alerts(campaign, **kwargs):
        found.setdefault(alert.kind, []).append((alert.severity, alert.text))
    return found


def test_every_rule(campaign: Campaign):
    found = texts(campaign, reforms=REFORMS)
    assert found["war"] == [("high", "At war: Venetian War")]
    assert found["coalition"] == [("high", "Coalition of 1 country against you")]
    # MIL could join; VEN is already in, BRA is an ally.
    assert found["aggressive_expansion"] == [
        ("medium", "1 more could join a coalition (50+ AE): Milan")
    ]
    # TUR is a rival: 5-year truce from 1475.1.1 ends in 1480, within two years.
    # ARA is neither rival nor neighbour, so its truce is not mentioned.
    assert found["truce"] == [
        ("medium", "Truce with Ottomans (rival) ends around 1480.1.1 (estimate)")
    ]
    assert found["balance"] == [("medium", "Losing 2.5 ducats a month")]
    assert found["loans"] == [("medium", "2 loans, 150 ducats of debt")]
    assert found["overextension"] == [("medium", "Overextension 25%")]
    assert found["war_exhaustion"] == [("medium", "War exhaustion 6.5")]
    assert found["stability"] == [("high", "Stability -1")]
    assert found["monarch_power"] == [
        ("info", "Administrative power at 950 of 999: spend it before it is wasted")
    ]
    assert found["imperial_reform"] == [
        ("info", "Instituir Reichsregiment can be proposed (imperial authority 60)")
    ]


def test_most_severe_first(campaign: Campaign):
    severities = [a.severity for a in campaign_alerts(campaign, reforms=REFORMS)]
    assert severities == sorted(severities, key=["high", "medium", "info"].index)


def test_reform_alert_needs_the_game_files(campaign: Campaign):
    assert "imperial_reform" not in texts(campaign)


def test_quiet_country_has_no_alerts(campaign: Campaign):
    assert campaign_alerts(campaign, "CAS") == []


def test_unknown_country_raises(campaign: Campaign):
    with pytest.raises(KeyError):
        campaign_alerts(campaign, "XXX")
