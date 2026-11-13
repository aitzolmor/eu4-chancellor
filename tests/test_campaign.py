import shutil
from pathlib import Path

import pytest

from chancellor.context.campaign import (
    Campaign,
    CountryLookupError,
    Truce,
    count_regiments,
    estimate_truce_end,
    land_armies,
    normalize,
)
from chancellor.game.localisation import Localisation
from chancellor.save.loader import load_save
from chancellor.save.parser import parse, parse_lazy

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"
NAMES = {
    "HAB": "Austria",
    "HUN": "Hungría",
    "OLD": "Hungría",
    "TUR": "Otomanos",
    "BOH": "Bohemia",
    "BHU": "Bohemian Union",
}


@pytest.fixture
def campaign(tmp_path: Path) -> Campaign:
    path = tmp_path / "mini.eu4"
    shutil.copy(FIXTURE, path)
    return Campaign.from_raw(load_save(path), Localisation(NAMES))


def test_basic_facts(campaign: Campaign):
    assert campaign.player == "HAB"
    assert campaign.date == "1471.10.2"
    assert "TUR" in campaign.country_blocks


def test_country_is_cached(campaign: Campaign):
    assert campaign.country("TUR") is campaign.country("TUR")
    assert campaign.country("XXX") is None


def test_exists(campaign: Campaign):
    assert campaign.exists("TUR")
    assert not campaign.exists("OLD")


def test_wars(campaign: Campaign):
    assert len(campaign.wars) == 2
    assert [w["name"].strip() for w in campaign.wars_of("TUR")] == ["Austrian Conquest of Nikopol"]
    assert campaign.wars_of("BOH") == []


def test_names(campaign: Campaign):
    assert campaign.name("TUR") == "Otomanos"
    assert campaign.label("TUR") == "Otomanos (TUR)"
    assert campaign.name("C00") == "Austrian Antilles"
    assert campaign.text("attitude_loyal") == "attitude loyal"


def test_normalize():
    assert normalize("  Borgoña ") == "borgona"
    assert normalize("ÉTATS   Pontificaux") == "etats pontificaux"


@pytest.mark.parametrize(
    ("query", "tag"),
    [
        ("TUR", "TUR"),
        ("tur", "TUR"),
        ("Otomanos", "TUR"),
        ("otomanos", "TUR"),
        ("Otom", "TUR"),  # prefix
        ("hungria", "HUN"),  # accent-insensitive; living country beats dead OLD
        ("union", "BHU"),  # start of a later word
        ("austrian antilles", "C00"),  # dynamic tag named in the save
    ],
)
def test_resolve_country(campaign: Campaign, query: str, tag: str):
    assert campaign.resolve_country(query) == tag


def test_resolve_ambiguous(campaign: Campaign):
    with pytest.raises(CountryLookupError) as exc:
        campaign.resolve_country("bohem")
    assert exc.value.ambiguous
    assert [t for t, _ in exc.value.candidates] == ["BOH", "BHU"]
    assert "Use the tag instead" in str(exc.value)


def test_resolve_not_found_with_suggestions(campaign: Campaign):
    with pytest.raises(CountryLookupError) as exc:
        campaign.resolve_country("Otomania")
    assert not exc.value.ambiguous
    assert ("TUR", "Otomanos") in exc.value.candidates


def test_resolve_not_found_without_suggestions(campaign: Campaign):
    with pytest.raises(CountryLookupError) as exc:
        campaign.resolve_country("zzz")
    assert exc.value.candidates == []


def test_resolve_empty_query(campaign: Campaign):
    with pytest.raises(CountryLookupError):
        campaign.resolve_country("   ")


# TUR has one army on land and one carried by a fleet, which the save nests in ``navy``.
EMBARKED = """
countries={
    TUR={ owned_provinces={ 1 } raw_development=470.000
          army={ name="Land" regiment={ } regiment={ } }
          navy={ name="Fleet" ship={ } ship={ }
                 army={ name="At sea" regiment={ } regiment={ } regiment={ } } } }
}
"""


def test_land_armies_include_armies_at_sea():
    country = parse(EMBARKED)["countries"]["TUR"]
    assert [a["name"] for a in land_armies(country)] == ["Land", "At sea"]
    assert count_regiments(country) == 5


def test_quick_stats_matches_full_parse_with_armies_at_sea():
    lazy = Campaign({"player": "TUR"}, parse_lazy(EMBARKED))
    full = Campaign({"player": "TUR"}, parse(EMBARKED))
    assert lazy.quick_stats["TUR"] == full.quick_stats["TUR"] == (470.0, 5)


# VEN and POL hold AE against HAB; POL also against TUR. MIL mentions HAB but has no AE.
GRIEVANCES = """
countries={
    HAB={ owned_provinces={ 1 } }
    TUR={ owned_provinces={ 2 } }
    VEN={ owned_provinces={ 3 } active_relations={
        HAB={ opinion={ modifier="aggressive_expansion" current_opinion=-62.898 }
              attitude="attitude_rivalry" } } }
    POL={ owned_provinces={ 4 } active_relations={
        HAB={ opinion={ modifier="improved_relation" current_opinion=11.0 }
              opinion={ modifier="aggressive_expansion" current_opinion=-48.898 }
              attitude="attitude_outraged" }
        TUR={ opinion={ modifier="aggressive_expansion" current_opinion=-5.0 } } } }
    MIL={ owned_provinces={ 5 } active_relations={
        HAB={ opinion={ modifier="improved_relation" current_opinion=20.0 } }
        TUR={ opinion={ modifier="aggressive_expansion" current_opinion=-1.0 } } } }
    DED={ active_relations={
        HAB={ opinion={ modifier="aggressive_expansion" current_opinion=-90.0 } } } }
}
"""


@pytest.mark.parametrize("parser", [parse, parse_lazy])
def test_aggressive_expansion_towards(parser):
    campaign = Campaign({"player": "HAB"}, parser(GRIEVANCES))
    grievances = campaign.aggressive_expansion_towards("HAB")
    assert [(g.tag, round(g.value, 3), g.attitude) for g in grievances] == [
        ("VEN", 62.898, "attitude_rivalry"),
        ("POL", 48.898, "attitude_outraged"),
    ]  # MIL has no AE against HAB; DED no longer exists
    assert [g.tag for g in campaign.aggressive_expansion_towards("TUR")] == ["POL", "MIL"]
    assert campaign.aggressive_expansion_towards("POL") == []


@pytest.mark.parametrize(
    ("last_war", "warscore", "end"),
    [
        ("1475.6.21", 0, "1480.6.21"),  # base 5 years
        ("1475.6.21", 100, "1490.6.21"),  # plus 10 at full war score
        ("1475.6.21", 41, "1484.7.28"),  # 9.1 years, 365-day calendar
        ("1475.12.31", 0, "1480.12.31"),
        ("1475.6.21", 150, "1490.6.21"),  # war score is capped
        ("unknown", 50, None),
    ],
)
def test_estimate_truce_end(last_war: str, warscore: int, end: str | None):
    assert estimate_truce_end(last_war, warscore) == end


def test_truce_between_two_countries():
    save = """
    countries={
        HAB={ owned_provinces={ 1 } active_relations={
            TUR={ last_war="1475.6.21" last_warscore=41 truce=yes }
            VEN={ last_war="1450.1.1" last_warscore=20 } } }
        TUR={ owned_provinces={ 2 } }
    }
    """
    campaign = Campaign({"player": "HAB"}, parse_lazy(save))
    assert campaign.truce("HAB", "TUR") == Truce("TUR", "1475.6.21", 41, "1484.7.28")
    assert campaign.truce("HAB", "VEN") is None  # an old war, no truce left
    assert campaign.truce("TUR", "HAB") is None  # nothing recorded on TUR's side here


def test_truces_soonest_first():
    save = """
    countries={
        HAB={ owned_provinces={ 1 } active_relations={
            TUR={ last_war="1475.6.21" last_warscore=41 truce=yes }
            FER={ last_war="1467.1.6" last_warscore=72 truce=yes }
            OLD={ last_war="1470.1.1" last_warscore=0 truce=yes }
            NOE={ truce=yes }
            VEN={ last_war="1450.1.1" last_warscore=20 } } }
        TUR={ owned_provinces={ 2 } } FER={ owned_provinces={ 3 } } NOE={ owned_provinces={ 4 } }
        OLD={ }
    }
    """
    campaign = Campaign({"player": "HAB"}, parse_lazy(save))
    # FER ends 1479.3, TUR 1484.7, NOE has no war date; OLD no longer exists.
    assert [t.other for t in campaign.truces("HAB")] == ["FER", "TUR", "NOE"]
