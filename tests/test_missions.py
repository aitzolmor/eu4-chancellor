from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.missions import mission_tree, render_missions
from chancellor.context.script import clean_text, describe
from chancellor.game.localisation import Localisation
from chancellor.game.missions import MissionLibrary, parse_mission_file
from chancellor.save.parser import parse

MISSIONS = """
hab_column_1 = {
    slot = 1
    generic = no
    potential = { tag = HAB }
    has_country_shield = yes

    hab_second = {
        icon = icon_b
        position = 2
        required_missions = { hab_first }
        trigger = { owns_core_province = 266 }
        effect = { give_claims = { area = silesia_area } }
    }
    hab_first = {
        icon = icon_a
        position = 1
        required_missions = { }
        trigger = { BOH = { is_subject_of = ROOT } }
        effect = {
            add_country_modifier = { name = hab_union duration = 5475 }
            hidden_effect = { set_country_flag = secret }
        }
    }
}
hab_column_2 = {
    slot = 2
    hab_third = {
        position = 1
        required_missions = { hab_first hab_second }
        effect = { add_prestige = 10 }
    }
    hab_alone = {
        position = 2
        trigger = { is_emperor = yes }
    }
}
"""

NAMES = {
    "HAB": "Austria",
    "BOH": "Bohemia",
    "PROV266": "Praga",
    "silesia_area": "Silesia",
    "hab_first_title": "§YFirst§! mission",
    "hab_second_title": "Second mission",
    "hab_union": "Crown of Bohemia",
    "my_tooltip": "If [BOH.GetName] agrees",
}


@pytest.fixture
def library() -> MissionLibrary:
    return MissionLibrary(parse_mission_file(MISSIONS))


@pytest.fixture
def campaign() -> Campaign:
    world = parse(
        """
        countries={
            HAB={
                owned_provinces={ 1 }
                completed_missions={ hab_first }
                country_missions={
                    mission_slot={ hab_column_1 }
                    mission_slot={ hab_column_2 mod_series }
                }
            }
            BOH={ owned_provinces={ 2 } }
        }
        """
    )
    return Campaign({"player": "HAB", "date": "1450.1.1"}, world, Localisation(NAMES))


# --- game files ------------------------------------------------------------------------


def test_parse_series_and_missions(library: MissionLibrary):
    series = library.series("hab_column_1")
    assert series.slot == 1
    assert not series.generic
    assert [m.name for m in series.missions] == ["hab_first", "hab_second"]  # by position
    second = library.mission("hab_second")
    assert second.required == ["hab_first"]
    assert second.icon == "icon_b"
    assert library.mission("hab_first").required == []


def test_settings_are_not_missions(library: MissionLibrary):
    assert library.mission("potential") is None
    assert library.mission("slot") is None


def test_load_from_game_dir_handles_both_encodings(tmp_path: Path):
    folder = tmp_path / "missions"
    folder.mkdir()
    (folder / "a.txt").write_text("a_series = { slot = 1 a_m = { position = 1 } }", "utf-8")
    (folder / "b.txt").write_bytes(
        'b_series = { slot = 2 b_m = { position = 1 effect = { x = "Señor" } } }'.encode("cp1252")
    )
    library = MissionLibrary.load(tmp_path)
    assert len(library) == 2
    assert library.mission("b_m").effect == {"x": "Señor"}


def test_load_without_missions_folder(tmp_path: Path):
    assert len(MissionLibrary.load(tmp_path)) == 0


# --- tree ------------------------------------------------------------------------------


def test_tree_status(campaign: Campaign, library: MissionLibrary):
    tree = mission_tree(campaign, library, "HAB")
    states = {m.mission.name: m for c in tree.columns for m in c.missions}
    assert states["hab_first"].status == "completed"
    assert states["hab_second"].status == "available"
    assert states["hab_third"].status == "locked"
    assert states["hab_third"].missing == ["hab_second"]
    assert states["hab_alone"].status == "available"
    assert (tree.count("completed"), tree.count("available"), tree.count("locked")) == (1, 2, 1)
    assert tree.total == 4


def test_tree_titles_and_unknown_series(campaign: Campaign, library: MissionLibrary):
    tree = mission_tree(campaign, library, "HAB")
    assert tree.columns[0].missions[0].title == "First mission"
    assert tree.columns[1].missions[1].title == "hab alone"  # no localisation
    assert tree.unknown_series == ["mod_series"]


def test_country_without_missions(campaign: Campaign, library: MissionLibrary):
    tree = mission_tree(campaign, library, "BOH")
    assert tree.columns == []
    assert "records no mission tree" in render_missions(campaign, tree)


def test_unknown_country(campaign: Campaign, library: MissionLibrary):
    with pytest.raises(KeyError):
        mission_tree(campaign, library, "XXX")


def test_render(campaign: Campaign, library: MissionLibrary):
    text = render_missions(campaign, mission_tree(campaign, library, "HAB"))
    assert text.startswith("# Missions: Austria (HAB), 1450.1.1")
    assert "1 of 4 missions completed, 2 available now, 1 locked." in text
    assert "- [x] First mission (`hab_first`)" in text
    assert "- [ ] **Second mission (`hab_second`)**, available now" in text
    assert "- owns_core_province: Praga (#266)" in text
    assert "- give_claims: area: Silesia" in text
    assert "- [-] hab third (`hab_third`), after: Second mission" in text
    assert "mod_series" in text


def test_render_brief(campaign: Campaign, library: MissionLibrary):
    text = render_missions(campaign, mission_tree(campaign, library, "HAB"), brief=True)
    assert "Requires" not in text
    assert "Rewards" not in text
    assert "Second mission" in text


# --- script descriptions ---------------------------------------------------------------


def lines(script: str, campaign: Campaign, **kwargs) -> list[str]:
    return describe(parse(script), campaign, **kwargs)


def test_tags_provinces_and_areas(campaign: Campaign):
    assert lines("BOH = { is_subject_of = ROOT } owns = 266 area = silesia_area", campaign) == [
        "- Bohemia (BOH): is_subject_of: ROOT",
        "- owns: Praga (#266)",
        "- area: Silesia",
    ]


def test_hidden_and_noise_keys_are_skipped(campaign: Campaign):
    script = "add_prestige = 5 hidden_effect = { x = 1 } ai_weight = { factor = 2 }"
    assert lines(script, campaign) == ["- add_prestige: 5"]


def test_tooltips_are_localised(campaign: Campaign):
    script = """
        custom_tooltip = my_tooltip
        custom_tooltip = SEPERATOR_TOOLTIP
        custom_trigger_tooltip = { tooltip = my_tooltip owns = 1 }
    """
    assert lines(script, campaign) == ["- If Bohemia agrees", "- If Bohemia agrees"]


def test_if_else(campaign: Campaign):
    script = "if = { limit = { is_emperor = yes } add_prestige = 5 } else = { add_prestige = 1 }"
    assert lines(script, campaign) == [
        "- If (is_emperor: yes):",
        "  - add_prestige: 5",
        "- Otherwise:",
        "  - add_prestige: 1",
    ]


def test_complex_dynamic_effect_with_script_strings(campaign: Campaign):
    script = """
        complex_dynamic_effect = {
            first_custom_tooltip = my_tooltip
            first_limit = "
                BOH = { is_subject_of = ROOT }
            "
            first_effect = "
                add_prestige = 10
            "
        }
    """
    assert lines(script, campaign) == ["- If Bohemia agrees:", "  - add_prestige: 10"]


def test_modifiers_are_compact(campaign: Campaign):
    script = """
        add_country_modifier = { name = hab_union duration = 5475 }
        add_province_modifier = { name = unknown_mod duration = -1 }
    """
    assert lines(script, campaign) == [
        "- add_country_modifier: Crown of Bohemia (hab_union, 15 years)",
        "- add_province_modifier: unknown_mod (permanent)",
    ]


def test_truncation(campaign: Campaign):
    script = " ".join(f"a{i} = {i}" for i in range(20))
    result = lines(script, campaign, max_lines=3)
    assert result == ["- a0: 0", "- a1: 1", "- a2: 2", "- …"]


def test_clean_text(campaign: Campaign):
    assert clean_text("§YHello§! [BOH.GetName]\\nworld [Root.GetFlag]", campaign) == (
        "Hello Bohemia world"
    )
