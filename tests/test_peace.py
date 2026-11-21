# ruff: noqa: E501  (the fixture keeps each province on one line)
"""What a peace can demand and its war score cost, as the 1.37 peace screen prices it (D-064)."""

from pathlib import Path

from chancellor.context.campaign import Campaign
from chancellor.context.peace import peace_options, province_cost, render_peace
from chancellor.context.tools import Toolbox
from chancellor.context.wars import war_reports
from chancellor.game.localisation import Localisation
from chancellor.live.war_score import LiveWarScore
from chancellor.save.parser import parse

# Austria (with its vassal Hungary) against Poland, whose junior partner Lithuania fights
# too. Barlad is the war goal and a claim of Hungary; Poznan is occupied by Austria's
# ally Glogow; Viazma is Lithuanian and not occupied; Krakow is neither (left out).
WORLD = """
countries={
    HAB={ subjects={ HUN } }
    HUN={ overlord=HAB }
    GLG={ }
    POL={ subjects={ LIT } raw_development=303.0 owned_provinces={ 1 2 3 } }
    LIT={ overlord=POL raw_development=393.0 owned_provinces={ 4 5 } }
}
diplomacy={
    dependency={ first="HAB" second="HUN" subject_type="vassal" }
    dependency={ first="POL" second="LIT" subject_type="personal_union" }
}
provinces={
    -1={ name="Barlad" owner="POL" controller="HAB" claims={ "HUN" } base_tax=3 base_production=1 base_manpower=1 }
    -2={ name="Poznan" owner="POL" controller="GLG" base_tax=9 base_production=11 base_manpower=5 }
    -3={ name="Krakow" owner="POL" controller="POL" base_tax=10 }
    -4={ name="Vilnius" owner="LIT" controller="HAB" base_tax=11 base_production=10 base_manpower=3 }
    -5={ name="Viazma" owner="LIT" controller="LIT" claims={ "HAB" } base_tax=4 base_production=3 base_manpower=1 }
}
active_war={
    name="Conquista de Barlad"
    history={ 1535.10.12={ add_attacker="HAB" add_defender="POL" } }
    attackers={ "HAB" "HUN" "GLG" } defenders={ "POL" "LIT" }
    persistent_attackers={ "HAB" "HUN" "GLG" } persistent_defenders={ "POL" "LIT" }
    take_province={ type=take_claim province=1 casus_belli=cb_conquest }
    last_warscore_quarter=87
}
"""
NAMES = {"HAB": "Austria", "HUN": "Hungría", "POL": "Polonia", "LIT": "Lituania"}


def _campaign() -> Campaign:
    return Campaign({"player": "HAB", "date": "1537.12.17"}, parse(WORLD), Localisation(NAMES))


def test_costs_match_the_peace_screen():
    # The user's 1537 peace screen: Barlad 4.0, Poznan 20.0, Varsovia 17.6, Vilnius 19.2.
    assert [province_cost(d) for d in (5, 25, 22, 24)] == [4.0, 20.0, 17.6, 19.2]


def test_what_can_be_demanded():
    campaign = _campaign()
    (war,) = war_reports(campaign)
    options = peace_options(campaign, war)
    assert (options.score, options.source) == (87, "the game's last quarterly check")
    found = {p.name: (p.cost, p.occupied, p.claimant, p.war_goal) for p in options.provinces}
    assert found == {
        "Barlad": (4.0, True, "HUN", True),  # a vassal's claim: no AE
        "Poznan": (20.0, True, "", False),  # occupied by an ally
        "Vilnius": (19.2, True, "", False),
        "Viazma": (6.4, False, "HAB", False),  # a claim, not occupied
    }
    assert [p.name for p in options.provinces][:2] == ["Barlad", "Viazma"]  # goal, claims
    assert options.releases == [("LIT", "POL", 100.0)]  # 0.4 × 0.8 × 393 = 126: capped
    assert options.development["POL"] == (303.0, 696.0)
    live = LiveWarScore("1537.11.22", 88.0, {})
    assert peace_options(campaign, war, live=live).score == 88.0


def test_the_report(tmp_path: Path):
    campaign = _campaign()
    text = render_peace(campaign, [peace_options(campaign, w) for w in war_reports(campaign)])
    assert "- War score: +87 against Polonia (the game's last quarterly check)." in text
    assert "- Polonia (POL): development 303, 696 with its subjects" in text
    assert "- Lituania (LIT) from Polonia: 100.0 (more than the war score)" in text
    assert "| Barlad (war goal) | Polonia | 5 | 4.0 | yes | Hungría |" in text
    assert "| Viazma | Lituania | 8 | 6.4 | no | yours |" in text
    assert "Krakow" not in text
    assert "War reparations (10% of their income for 10 years) 10" in text
    toolbox = Toolbox(campaign, None, tmp_path / "context.json")
    assert toolbox.run("get_peace_options", {}).startswith("# Peace terms: Austria (HAB)")
    peace = Campaign({"player": "HAB"}, parse("countries={ HAB={ } }"), Localisation())
    assert "At peace." in render_peace(peace, [])
