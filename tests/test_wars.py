"""A country's wars in detail: start, occupations, losses, battles (D-050)."""

from chancellor.context.campaign import Campaign
from chancellor.context.summarizer import summarize
from chancellor.context.tools import Toolbox
from chancellor.context.wars import losses_from, render_wars, war_line, war_reports, war_start
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse

# Austria attacks Ragusa in 1528; the Ottomans join Ragusa. Austria holds Ragusa (137)
# and an Ottoman province (149); the Ottomans hold nothing of Austria's. The save is from
# 1532.1.1, which is also the war's `action`: not its start.
WORLD = """
countries={ HAB={ owned_provinces={ 134 } } RAG={ } TUR={ } MAM={ } }
provinces={
    -134={ owner="HAB" controller="HAB" name="Wien" }
    -137={ owner="RAG" controller="HAB" previous_controller="RAG" name="Ragusa"
           base_tax=8 base_production=7 base_manpower=4 }
    -149={ owner="TUR" controller="HAB" name="Edirne" base_tax=6 base_production=5 base_manpower=4 }
    -151={ owner="TUR" controller="TUR" name="Konstantiniyye" base_tax=15 }
}
active_war={
    name=" Conquista austríaco de Ragusa"
    history={
        1528.9.17={ add_attacker="HAB" add_defender="RAG" }
        1528.9.27={ battle={ name="Mar Egeo" result=no
            attacker={ light_ship=4 losses=5 country="MAM" }
            defender={ galley=26 losses=0 country="TUR" } } }
        1529.6.1={ battle={ name="Varna" result=yes
            attacker={ infantry=20000 losses=1500 country="HAB" }
            defender={ infantry=15000 losses=6000 country="TUR" } } }
        1528.10.1={ add_defender="TUR" }
    }
    attackers={ "HAB" "MAM" } defenders={ "RAG" "TUR" }
    persistent_attackers={ "HAB" "MAM" } persistent_defenders={ "RAG" "TUR" }
    participants={ value=325.7 tag="HAB"
        losses={ members={ 6062 13013 0 1017 5260 0 1340 3103 0 0 0 0 0 0 0 0 0 0 0 0 0 } } }
    participants={ value=447.5 tag="TUR"
        losses={ members={ 6763 19552 0 301 9550 0 0 4796 0 0 0 0 8 0 0 6 0 0 0 0 0 } } }
    participants={ value=50.7 tag="MAM" losses={ members={ 0 0 0 0 0 0 0 0 0 0 0 0 3 0 0 } } }
    participants={ value=14.6 tag="RAG" }
    action=1532.1.1
    take_province={ type=take_claim province=137 casus_belli=cb_conquest }
    last_warscore_quarter=56
    next_quarter_update=1532.3.11
}
"""

NAMES = {"HAB": "Austria", "RAG": "Ragusa", "TUR": "Otomanos", "MAM": "Mamelucos"}


def _campaign() -> Campaign:
    return Campaign({"player": "HAB", "date": "1532.1.1"}, parse(WORLD), Localisation(NAMES))


def test_the_war_began_at_its_first_history_entry_not_at_action():
    campaign = _campaign()
    war = campaign.wars_of("HAB")[0]
    assert war["action"] == "1532.1.1"
    assert war_start(war) == "1528.9.17"
    assert war_start({}) is None


def test_occupations_losses_and_battles():
    (war,) = war_reports(_campaign())
    assert (war.side, war.our_side, war.their_side) == ("attacker", ["HAB", "MAM"], ["RAG", "TUR"])
    assert war.goal == ("cb_conquest", 137)
    assert war.occupied_by_us == [(137, "RAG"), (149, "TUR")]
    assert war.occupied_by_them == []
    assert (war.losses["HAB"].battle, war.losses["HAB"].attrition) == (8419, 21376)
    assert war.losses["TUR"].ships == 14 and war.losses["MAM"].ships == 3
    assert war.quarterly_score == 56 and war.next_check == "1532.3.11"
    assert [(b.date, b.won, b.naval) for b in war.battles] == [
        ("1528.9.27", False, True),  # the Mamelukes' fleet lost
        ("1529.6.1", True, False),  # Austria attacked and won
    ]
    assert losses_from([1, 2, 3]).battle == 1


def test_the_report_and_the_briefing_line():
    campaign = _campaign()
    text = render_wars(campaign, war_reports(campaign))
    assert "- Began 1528.9.17; Austria is the attacker." in text
    assert "(controlled by Austria)" in text
    assert "- We occupy 2 provinces (34 development):" in text
    assert "  - of Ragusa (1): Province 137 19" in text
    assert "- They occupy nothing." in text
    assert "  - Otomanos: 7,064 in battle, 33,898 to attrition, 14 ships" in text
    assert "the game keeps only some, so they are not a tally" in text
    assert "last quarterly check: 56 (next check 1532.3.11)" in text
    line = war_line(campaign, war_reports(campaign)[0])
    assert line.startswith("began 1528.9.17; we occupy 2 of their provinces")
    briefing = summarize(campaign)
    assert "started 1528.9.17" in briefing and "started 1532.1.1" not in briefing
    assert "  - State: began 1528.9.17;" in briefing


def test_the_tool(tmp_path):
    toolbox = Toolbox(_campaign(), None, tmp_path / "context.json")
    assert toolbox.run("get_wars", {}).startswith("# Wars of Austria (HAB)")
    peace = Campaign({"player": "RAG"}, parse("countries={ RAG={ } }"), Localisation())
    assert "At peace." in render_wars(peace, war_reports(peace))
