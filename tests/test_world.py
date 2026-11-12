import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.world import render_world, world_overview
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse, parse_lazy

# HAB (player) is allied with CAS and has a vassal LAN and a tributary TRI.
# FRA is allied with SCO; FRA and HAB are both great powers. MNG is big and alone.
# POL is in a personal union over LIT. One war: FRA vs BUR.
WORLD = """
great_powers={
    original={ rank=1 country="FRA" value=700.0 }
    original={ rank=2 country="HAB" value=450.5 }
}
countries={
    HAB={ owned_provinces={ 1 } raw_development=190.000 allies={ CAS }
          army={ regiment={ } regiment={ } regiment={ } } }
    LAN={ owned_provinces={ 2 } raw_development=70.000 army={ regiment={ } } }
    TRI={ owned_provinces={ 3 } raw_development=10.000 army={ regiment={ } } }
    CAS={ owned_provinces={ 4 } raw_development=350.000 allies={ HAB }
          army={ regiment={ } regiment={ } } }
    FRA={ owned_provinces={ 5 } raw_development=560.000 allies={ SCO }
          army={ regiment={ } regiment={ } regiment={ } regiment={ } }
          army={ regiment={ } } }
    SCO={ owned_provinces={ 6 } raw_development=60.000 army={ regiment={ } } }
    BUR={ owned_provinces={ 7 } raw_development=250.000 army={ regiment={ } regiment={ } } }
    MNG={ owned_provinces={ 8 } raw_development=1100.000
          army={ regiment={ } regiment={ } regiment={ } regiment={ } regiment={ }
                 regiment={ } } }
    POL={ owned_provinces={ 9 } raw_development=280.000 }
    LIT={ owned_provinces={ 10 } raw_development=300.000 }
    DED={ raw_development=99.000 army={ regiment={ } } }
}
diplomacy={
    alliance={ first="HAB" second="CAS" }
    alliance={ first="FRA" second="SCO" }
    alliance={ first="FRA" second="HAB" end_date=1460.1.1 }
    dependency={ first="HAB" second="LAN" subject_type="vassal" }
    dependency={ first="HAB" second="TRI" subject_type="tributary_state" }
    dependency={ first="POL" second="LIT" subject_type="personal_union" }
}
empire={ emperor=HAB electors={ BOH SAX } }
active_war={ name=" French conquest of Dijon" attackers={ "FRA" } defenders={ "BUR" } }
"""


@pytest.fixture
def campaign() -> Campaign:
    meta = {"player": "HAB", "date": "1475.6.21"}
    names = {"HAB": "Austria", "FRA": "France", "CAS": "Castile", "MNG": "Ming"}
    return Campaign(meta, parse(WORLD), Localisation(names))


def test_quick_stats_skip_dead_countries(campaign: Campaign):
    stats = campaign.quick_stats
    assert stats["FRA"] == (560.0, 5)
    assert stats["POL"] == (280.0, 0)
    assert "DED" not in stats


def test_quick_stats_on_lazy_blocks_match_full_parse(campaign: Campaign):
    lazy = Campaign(campaign.meta, parse_lazy(WORLD))
    assert lazy.quick_stats == campaign.quick_stats


def test_rankings(campaign: Campaign):
    world = world_overview(campaign, top=3)
    assert [c.tag for c in world.by_development] == ["MNG", "FRA", "CAS"]
    assert [c.tag for c in world.by_army] == ["MNG", "FRA", "HAB"]
    assert world.player_development_rank == 7  # MNG FRA CAS LIT POL BUR HAB
    assert world.player_army_rank == 3
    assert world.living_countries == 10


def test_great_powers(campaign: Campaign):
    powers = world_overview(campaign).great_powers
    assert [(gp.rank, gp.tag, gp.score) for gp in powers] == [(1, "FRA", 700.0), (2, "HAB", 450.5)]
    assert powers[0].allies == ["SCO"]
    assert powers[0].at_war


def test_networks(campaign: Campaign):
    blocs = {b.members[0]: b for b in world_overview(campaign).blocs}
    assert blocs["HAB"].members == ["HAB", "CAS", "LAN"]  # tributary TRI does not fight
    assert blocs["HAB"].regiments == 6
    assert blocs["HAB"].includes_player
    assert blocs["FRA"].members == ["FRA", "SCO"]  # expired alliance with HAB ignored
    assert "MNG" not in blocs  # no allies, no network


def test_player_network_comes_first(campaign: Campaign):
    assert world_overview(campaign).blocs[0].members[0] == "HAB"


def test_wars_and_unions(campaign: Campaign):
    world = world_overview(campaign)
    assert [(w.name, w.attacker_regiments, w.defender_regiments) for w in world.wars] == [
        ("French conquest of Dijon", 5, 2)
    ]
    assert world.personal_unions == [("POL", "LIT")]
    assert world.emperor == "HAB"
    assert world.electors == ["BOH", "SAX"]


def test_render(campaign: Campaign):
    text = render_world(campaign, world_overview(campaign, top=3))
    assert text.startswith("# World overview, 1475.6.21")
    assert "ranked #7 by development and #3 by army size" in text
    assert "| 1 | France (FRA) | 700 | 560 | 5 | SCO | yes |" in text
    assert "| 2 | Austria (HAB) **(you)** | 450 |" in text
    assert "| Austria (HAB) **(you)** | Castile, LAN | 6 |" in text
    assert "| French conquest of Dijon | France | BUR | 5 vs 2 |" in text
    assert "POL (POL) over LIT (LIT)" in text
    assert "- Emperor: Austria (HAB)" in text


def test_empty_world():
    campaign = Campaign({"player": "HAB", "date": "1444.11.11"}, parse("countries={ }"))
    text = render_world(campaign, world_overview(campaign))
    assert "No alliances." in text
    assert "The world is at peace." in text
