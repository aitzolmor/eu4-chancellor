import shutil
from pathlib import Path

import pytest

from chancellor.context.campaign import (
    Campaign,
    CountryLookupError,
    count_regiments,
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
