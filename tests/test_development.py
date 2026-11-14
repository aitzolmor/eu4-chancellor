"""Province terrain and development costs (D-031).

The costs were checked against the game's tooltips for Austria on 1483.3.2: Vienna 59,
Ostmark 53, Tirol 56. :func:`test_austria_1483_matches_the_game` rebuilds that case.
"""

import struct
from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.development import development_costs, render_development
from chancellor.game.development_rules import DevelopmentRules
from chancellor.game.localisation import Localisation
from chancellor.game.rules import GameRules
from chancellor.game.terrain import TerrainMap, majority_terrain, parse_definitions
from chancellor.save.parser import parse

# --- terrain from the map images --------------------------------------------------------------


def _bmp(width: int, height: int, bits: int, rows: list[bytes]) -> bytes:
    """A bottom-up BMP: ``rows`` from the bottom row up, already ``width`` pixels wide."""
    palette = bytes(1024) if bits == 8 else b""
    stride = (width * bits // 8 + 3) // 4 * 4
    pixels = b"".join(row.ljust(stride, b"\0") for row in rows)
    offset = 14 + 40 + len(palette)
    header = b"BM" + struct.pack("<IHHI", offset + len(pixels), 0, 0, offset)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, bits, 0, len(pixels), 0, 0, 0, 0)
    return header + info + palette + pixels


RED, BLUE = (200, 0, 0), (0, 0, 200)


def _bgr(colour: tuple[int, int, int]) -> bytes:
    return bytes(reversed(colour))


def test_majority_terrain_per_province():
    # 4x2 map: province 1 (red) on the left, 2 (blue) on the right.
    provinces = _bmp(4, 2, 24, [(_bgr(RED) * 2 + _bgr(BLUE) * 2)] * 2)
    # Terrain indices: 6 = mountain, 1 = hills, 0 = grasslands.
    terrain = _bmp(4, 2, 8, [bytes([6, 6, 1, 0]), bytes([6, 1, 0, 0])])
    result = majority_terrain(
        provinces, terrain, {RED: 1, BLUE: 2}, {6: "mountain", 1: "hills", 0: "grasslands"}, step=1
    )
    assert result == {1: "mountain", 2: "grasslands"}


def test_definitions():
    text = "province;red;green;blue;x;x\n1;128;34;64;Stockholm;x\n2;0;36;128;Ost;x\n"
    assert parse_definitions(text) == {(128, 34, 64): 1, (0, 36, 128): 2}


def test_terrain_map_reads_the_game_and_applies_overrides(tmp_path: Path):
    map_dir = tmp_path / "map"
    map_dir.mkdir()
    (map_dir / "terrain.txt").write_text(
        "categories = {\n"
        "  mountain = { local_development_cost = 0.35 }\n"
        "  farmlands = { local_development_cost = -0.05 terrain_override = { 2 } }\n"
        "}\n"
        "terrain = {\n"
        "  mountain = { type = mountain color = { 6 } }\n"
        "}\n",
        encoding="utf-8",
    )
    (map_dir / "definition.csv").write_text(
        "province;red;green;blue;x;x\n1;200;0;0;A;x\n2;0;0;200;B;x\n", encoding="utf-8"
    )
    (map_dir / "provinces.bmp").write_bytes(_bmp(2, 1, 24, [_bgr(RED) + _bgr(BLUE)]))
    (map_dir / "terrain.bmp").write_bytes(_bmp(2, 1, 8, [bytes([6, 6])]))
    terrain = TerrainMap.load(tmp_path)
    assert terrain.provinces == {1: "mountain", 2: "farmlands"}  # 2 is overridden
    assert terrain.development_cost(1) == 0.35
    assert terrain.development_cost(2) == -0.05
    assert terrain.development_cost(99) == 0.0
    assert TerrainMap.parse_game(tmp_path / "missing").provinces == {}


# --- development costs -------------------------------------------------------------------------

WORLD = """
countries={
    HAB={ owned_provinces={ 134 1770 73 } capital=134 religion=catholic raw_development=285.000
          institutions={ 1 1 0 } corruption=0.395 innovativeness=1.710 }
}
provinces={
    -134={ owner="HAB" name="Viena" hre=yes base_tax=9 base_production=9 base_manpower=9
           center_of_trade=2 modifier={ modifier="foreign_merchant_community" date=1485.9.2 } }
    -1770={ owner="HAB" name="Ostmark" hre=yes base_tax=4 base_production=3 base_manpower=4 }
    -73={ owner="HAB" name="Tirol" hre=yes base_tax=4 base_production=7 base_manpower=2
          modifier={ modifier="hab_tirol_mine" date=1490.1.1 } }
}
map_area_data{
    austria_proper_area={ state={ area="austria_proper_area"
        country_state={ prosperity=100.000 country="HAB" } } }
    tirol_area={ state={ area="tirol_area" country_state={ prosperity=100.000 country="HAB" }
        country_state={ prosperity=77.000 country="TNT" } } }
}
religion_instance_data={ catholic={
    papacy={ controller="CAS" golden_bull="praeclara_carissimi" } } }
empire={ emperor=HAB passed_reform=emperor_reichsreform }
"""


@pytest.fixture
def campaign() -> Campaign:
    return Campaign({"player": "HAB", "date": "1483.3.2"}, parse(WORLD), Localisation({}))


@pytest.fixture
def rules() -> DevelopmentRules:
    return DevelopmentRules(
        terrain=TerrainMap(
            categories={
                "farmlands": {"local_development_cost": -0.05},
                "hills": {"local_development_cost": 0.25},
                "mountain": {"local_development_cost": 0.35},
            },
            provinces={134: "farmlands", 1770: "hills", 73: "mountain"},
        ),
        static={"prosperity": -0.1, "development_scaled": 0.03},
        centers_of_trade={2: -0.05},
        state_centers_of_trade={3: -0.1},
        institutions={"renaissance": -0.05},
        institution_order=["feudalism", "renaissance", "new_world_i"],
        golden_bulls={"praeclara_carissimi": -0.05},
        imperial_reforms={"emperor_reichsreform": {"province": -0.05}},
        modifiers={"foreign_merchant_community": -0.1, "hab_tirol_mine": -0.1},
    )


@pytest.fixture
def geography() -> GameRules:
    return GameRules(
        geography={"austria_proper_area": frozenset({134, 1770}), "tirol_area": frozenset({73})}
    )


def test_austria_1483_matches_the_game(campaign, rules, geography):
    costs = {c.name: c.cost for c in development_costs(campaign, rules, geography)}
    assert costs == {"Viena": 59, "Ostmark": 53, "Tirol": 56}


def test_parts_are_the_games(campaign, rules, geography):
    vienna = next(c for c in development_costs(campaign, rules, geography) if c.province == 134)
    assert dict(vienna.parts) == {
        "capital (285 total development)": -0.142,
        "renaissance": -0.05,
        "praeclara carissimi": -0.05,  # names without translation lose underscores
        "foreign merchant community": -0.1,
        "centre of trade level 2": -0.05,
        "emperor reichsreform": -0.05,
        "farmlands": -0.05,
        "prosperity": -0.1,
        "development already there": 0.78,  # 10 points at 3% and 8 at 6%
        "corruption": 0.003,
        "innovativeness": -0.001,
    }


def test_the_golden_bull_only_applies_to_its_religion(campaign, rules, geography):
    campaign.country("HAB")["religion"] = "protestant"
    vienna = next(c for c in development_costs(campaign, rules, geography) if c.province == 134)
    assert "praeclara carissimi" not in dict(vienna.parts)


def test_a_level_3_centre_helps_its_whole_state(campaign, rules, geography):
    campaign.province(134)["center_of_trade"] = 3
    ostmark = next(c for c in development_costs(campaign, rules, geography) if c.province == 1770)
    assert dict(ostmark.parts)["level 3 centre of trade in the state"] == -0.1


def test_render_lists_the_cheapest_and_the_capital(campaign, rules, geography):
    costs = development_costs(campaign, rules, geography)
    line = render_development(costs, 134, shown=1)
    assert line.startswith("- Developing a province (+1, same price in any category): cheapest")
    assert "Ostmark 53, capital Viena 59; dearest Viena 59" in line


def test_rules_are_read_from_the_game_files(tmp_path: Path):
    common = tmp_path / "common"
    for folder, text in {
        "static_modifiers": "prosperity = { local_development_cost = -0.1 }\n"
        "development_scaled = { local_development_cost = 0.03 }\n"
        "corruption = { all_power_cost = 1.0 }\n",
        "centers_of_trade": "market_town = { level = 2 province_modifiers = { "
        "local_development_cost = -0.05 } }\n"
        "world_port = { level = 3 state_modifiers = { local_development_cost = -0.1 } }\n",
        "institutions": "feudalism = { bonus = { } }\n"
        "renaissance = { bonus = { development_cost = -0.05 } }\n",
        "golden_bulls": "pietas = { modifier = { development_cost = -0.05 } }\n",
        "imperial_reforms": "reichsreform = { province = { local_development_cost = -0.05 } }\n",
        "event_modifiers": "mine = { local_development_cost = -0.1 }\nother = { prestige = 1 }\n",
    }.items():
        (common / folder).mkdir(parents=True)
        (common / folder / "f.txt").write_text(text, encoding="utf-8")
    (tmp_path / "map").mkdir()
    (tmp_path / "map" / "climate.txt").write_text("arid = { 1 2 }\nmild_winter = { 3 }\n", "utf-8")
    rules = DevelopmentRules.load(tmp_path)
    assert rules.static == {"prosperity": -0.1, "development_scaled": 0.03}
    assert (rules.centers_of_trade, rules.state_centers_of_trade) == ({2: -0.05}, {3: -0.1})
    assert rules.institutions == {"renaissance": -0.05}
    assert rules.institution_order == ["feudalism", "renaissance"]
    assert rules.golden_bulls == {"pietas": -0.05}
    assert rules.imperial_reforms == {"reichsreform": {"province": -0.05}}
    assert rules.modifiers == {"mine": -0.1}
    assert rules.climate == {1: "arid", 2: "arid"}
    assert rules.corruption_power_cost == 1.0
