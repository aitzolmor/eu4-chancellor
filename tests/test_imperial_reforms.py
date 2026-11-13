from pathlib import Path

import pytest

from chancellor.game.imperial_reforms import ImperialReformLibrary, parse_reform_file

# A trimmed copy of the game's layout: a DLC mainline, two exclusive branches after the
# diet, a reform for players without the DLC, and a Celestial Empire reform.
REFORMS = """
emperor_reichsreform = {
    empire = hre
    potential = { has_dlc = "Emperor" }
    province = { local_build_cost = -0.05 }
    gui_container = mainline
}
emperor_reichsregiment = {
    empire = hre
    potential = { has_dlc = "Emperor" }
    emperor = { diplomatic_reputation = 1 diplomats = 1 }
    province = { local_unrest = -2 }
    required_reform = emperor_reichsreform
    gui_container = mainline
}
emperor_perpetual_diet = {
    empire = hre
    potential = { has_dlc = "Emperor" }
    required_reform = emperor_reichsregiment
    gui_container = mainline
}
emperor_reichstag_collegia = {
    empire = hre
    potential = { has_dlc = "Emperor" }
    required_reform = emperor_perpetual_diet
    disabled_by = emperor_hofgericht
    gui_container = left_branch
}
emperor_hofgericht = {
    empire = hre
    potential = { has_dlc = "Emperor" }
    required_reform = emperor_perpetual_diet
    gui_container = right_branch
}
reichsreform = {
    empire = hre
    potential = { NOT = { has_dlc = "Emperor" } }
}
mandate_reform = {
    empire = celestial_empire
}
"""
LIBRARY = ImperialReformLibrary(parse_reform_file(REFORMS))
MAINLINE = ["emperor_reichsreform", "emperor_reichsregiment", "emperor_perpetual_diet"]


def names(passed: list[str], dlc: bool = True) -> list[str]:
    return [r.name for r in LIBRARY.next_reforms(passed, has_emperor_dlc=dlc)]


def test_parse_reform_file():
    regiment = LIBRARY.get("emperor_reichsregiment")
    assert regiment is not None
    assert regiment.required == "emperor_reichsreform"
    assert regiment.dlc is True
    assert regiment.modifiers == {
        "emperor": [("diplomatic_reputation", 1), ("diplomats", 1)],
        "province": [("local_unrest", -2)],
    }
    assert LIBRARY.get("reichsreform").dlc is False
    assert LIBRARY.get("emperor_reichstag_collegia").disabled_by == "emperor_hofgericht"


@pytest.mark.parametrize(
    ("passed", "dlc", "expected"),
    [
        ([], True, ["emperor_reichsreform"]),
        ([], False, ["reichsreform"]),  # the set without the Emperor DLC
        (["emperor_reichsreform"], True, ["emperor_reichsregiment"]),
        (MAINLINE, True, ["emperor_reichstag_collegia", "emperor_hofgericht"]),  # two branches
        ([*MAINLINE, "emperor_hofgericht"], True, []),  # the other branch is now closed
        ([*MAINLINE, "emperor_reichstag_collegia"], True, []),  # and the reverse
    ],
)
def test_next_reforms(passed: list[str], dlc: bool, expected: list[str]):
    assert names(passed, dlc) == expected


def test_load_reads_the_game_folder(tmp_path: Path):
    folder = tmp_path / "common" / "imperial_reforms"
    folder.mkdir(parents=True)
    (folder / "00_hre.txt").write_text(REFORMS, encoding="utf-8")
    assert len(ImperialReformLibrary.load(tmp_path)) == 7
