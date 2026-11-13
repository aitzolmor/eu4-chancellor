from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.script import describe
from chancellor.game.localisation import Localisation
from chancellor.game.modifiers import ModifierLibrary, format_effect, parse_modifier_file
from chancellor.save.parser import parse

LOC = Localisation(
    {
        "MODIFIER_DIPLOMATIC_UPKEEP": "Relaciones diplomáticas",
        "local_development_cost": "Coste de desarrollo local",
        "DIPLOMATIC_REPUTATION": "A very long description of what diplomatic reputation does "
        "in the game, far longer than a stat name",
        "diplomatic_reputation": "Reputación diplomática",
        "hab_union": "Crown of Bohemia",
        "ballrooms": "Ballrooms",
        "DIPLOMATS": "Una $DIRECTION$ de $VALUE$ diplomáticos.",
    }
)


def test_parse_modifier_file_keeps_only_stats():
    text = """
        hab_union = { diplomatic_upkeep = 1 reduced_liberty_desire = 10 picture = "x" }
        ballrooms = {
            potential = { always = yes }
            trigger = { owner = { prestige = 80 } }
            monthly_splendor = 4
            can_fabricate = yes
        }
    """
    result = parse_modifier_file(text)
    assert result["hab_union"] == [("diplomatic_upkeep", 1), ("reduced_liberty_desire", 10)]
    assert result["ballrooms"] == [("monthly_splendor", 4), ("can_fabricate", True)]


def test_load_from_game_dir(tmp_path: Path):
    for folder, text in (
        ("event_modifiers", "a = { global_tax_modifier = 0.1 }"),
        ("province_triggered_modifiers", "b = { trigger = { } local_tax_modifier = 0.2 }"),
    ):
        path = tmp_path / "common" / folder
        path.mkdir(parents=True)
        (path / "00.txt").write_text(text, encoding="utf-8")
    library = ModifierLibrary.load(tmp_path)
    assert len(library) == 2
    assert "b" in library
    assert library.effects("missing") == []


@pytest.mark.parametrize(
    ("stat", "value", "expected"),
    [
        ("diplomatic_upkeep", 1, "Relaciones diplomáticas +1"),
        ("local_development_cost", -0.1, "Coste de desarrollo local -10%"),
        ("diplomatic_reputation", 1, "Reputación diplomática +1"),  # long text skipped
        ("global_manpower_modifier", 0.25, "global manpower modifier +25%"),
        ("yearly_corruption", -0.05, "yearly corruption -0.05"),
        ("war_exhaustion", -0.03, "war exhaustion -0.03"),
        ("can_fabricate", True, "can fabricate"),
        ("diplomats", 1, "diplomats +1"),  # sentence template skipped
    ],
)
def test_format_effect(stat, value, expected):
    assert format_effect(stat, value, LOC) == expected


def test_mission_rewards_list_modifier_bonuses():
    campaign = Campaign({"player": "HAB", "date": "1450.1.1"}, parse("countries={ }"), LOC)
    library = ModifierLibrary(
        {
            "hab_union": [("diplomatic_upkeep", 1), ("local_development_cost", -0.1)],
            "ballrooms": [("monthly_splendor", 4)],
        }
    )
    script = parse(
        """
        add_country_modifier = { name = hab_union duration = 5475 }
        add_province_triggered_modifier = ballrooms
        add_country_modifier = { name = unknown duration = 365 }
        """
    )
    assert describe(script, campaign, modifiers=library) == [
        "- add_country_modifier: Crown of Bohemia (hab_union, 15 years): "
        "Relaciones diplomáticas +1, Coste de desarrollo local -10%",
        "- add_country_modifier: unknown (1 years)",  # repeated keys are grouped by the parser
        "- add_province_triggered_modifier: Ballrooms (ballrooms): monthly splendor +4",
    ]
    # Without the library, only names and durations are shown.
    assert (
        describe(script, campaign)[0]
        == "- add_country_modifier: Crown of Bohemia (hab_union, 15 years)"
    )
