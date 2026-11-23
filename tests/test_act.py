"""Act: prepare an action for computer use, then check it in the next save (D-069)."""

from pathlib import Path

import pytest

from chancellor.context.act import (
    Action,
    ActionError,
    ActionStore,
    actions_path,
    prepare,
    render_prepared,
    verify,
)
from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox, ToolInputError
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse

WORLD = """
countries={
    HAB={
        owned_provinces={ 134 133 } capital=134 treasury=300.0 stability=1.0
        technology={ adm_tech=9 dip_tech=8 mil_tech=11 } powers={ 400 150 90 }
        completed_missions={ hab_first }
        active_idea_groups={ HAB_ideas=2 diplomatic_ideas=4 }
        loan={ amount=120.0 } loan={ amount=200.0 }
    }
    NAP={ owned_provinces={ 121 } }
}
provinces={
    -134={ owner="HAB" controller="HAB" cores={ "HAB" } name="Wien" }
    -133={ owner="HAB" controller="HAB" name="Linz" }
    -121={ owner="NAP" controller="NAP" cores={ "NAP" } name="Napoli" }
}
"""
NAMES = {"HAB": "Austria", "NAP": "Nápoles", "adm_tech": "Tecnología administrativa"}


def campaign(date: str = "1540.1.1", world: str = WORLD) -> Campaign:
    return Campaign({"player": "HAB", "date": date}, parse(world), Localisation(NAMES))


def later(change: str, date: str = "1540.3.1") -> Campaign:
    """The same world, saved later with one change made."""
    old, new = change.split(" => ")
    assert old in WORLD
    return campaign(date, WORLD.replace(old, new, 1))


def test_only_supported_kinds_with_their_targets():
    with pytest.raises(ActionError, match="cannot be carried out automatically"):
        prepare(campaign(), "fix_deficit", None)
    with pytest.raises(ActionError, match="needs a target"):
        prepare(campaign(), "core_province", None)
    with pytest.raises(ActionError, match="adm, dip or mil"):
        prepare(campaign(), "buy_technology", "army")


def test_a_possible_action_comes_with_steps_and_rules():
    prepared = prepare(campaign(), "buy_technology", "adm", tech_cost=350)
    assert prepared.possible and prepared.action.before == {"level": 9}
    assert prepared.action.title == "Buy «Tecnología administrativa» 10"
    text = render_prepared(campaign(), prepared)
    assert "- [x] 400 points for a cost of about 350" in text
    assert "1. Pause the game (Space)." in text
    assert "3. CONFIRM with the player, then click the button under" in text
    assert "Stay inside the Europa Universalis IV window" in text
    assert "running as administrator" in text


def test_the_save_can_rule_an_action_out():
    prepared = prepare(campaign(), "buy_technology", "dip", tech_cost=478)
    assert not prepared.possible
    text = render_prepared(campaign(), prepared)
    assert text.startswith("# Not possible now:") and "Do not carry it out" in text
    assert "## Steps" not in text  # no steps for an action that cannot be done
    assert not prepare(campaign(), "complete_mission", "hab_first").possible  # done already
    assert not prepare(campaign(), "complete_mission", "hab_next", ready_missions=[]).possible
    assert not prepare(campaign(), "core_province", "134").possible  # a core already
    assert not prepare(campaign(), "declare_war", "XXX").possible  # no such country


def test_verify_waits_for_a_later_save():
    action = prepare(campaign(), "repay_loan", None).action
    done, why = verify(campaign(), action)
    assert done is None and "ask the player to save" in why


@pytest.mark.parametrize(
    ("kind", "target", "change", "expected"),
    [
        ("buy_technology", "adm", "adm_tech=9 => adm_tech=10", True),
        ("buy_technology", "adm", "dip_tech=8 => dip_tech=9", False),
        ("raise_stability", None, "stability=1.0 => stability=2.0", True),
        ("repay_loan", None, "loan={ amount=120.0 } => ", True),
        ("buy_idea", None, "diplomatic_ideas=4 => diplomatic_ideas=5", True),
        ("complete_mission", "hab_next", "{ hab_first } => { hab_first hab_next }", True),
        ("core_province", "133", "powers={ 400 150 90 } => powers={ 310 150 90 }", True),
        ("core_province", "133", "powers={ 400 150 90 } => powers={ 395 150 90 }", False),
        ("core_province", "133", '-133={ owner="HAB" => -133={ cores={ "HAB" } owner="HAB"', True),
        (
            "declare_war",
            "NAP",
            '}\nprovinces={ => }\nactive_war={ attackers={ "HAB" } defenders={ "NAP" } }\n'
            "provinces={",
            True,
        ),
    ],
)
def test_verify_reads_the_next_save(kind, target, change, expected):
    prepared = prepare(campaign(), kind, target, core_cost=100)
    done, _why = verify(later(change), prepared.action)
    assert done is expected


def test_forming_a_nation_is_seen_under_the_new_tag():
    action = Action(1, "form_nation", "form_germany", "Form Germany", "HAB", "1540.1.1")
    action.before = {"forms": "GER"}
    world = WORLD.replace("    HAB={", "    GER={", 1)
    formed = Campaign({"player": "GER", "date": "1540.3.1"}, parse(world), Localisation())
    assert verify(formed, action)[0] is True


def test_the_store_keeps_ids_and_status(tmp_path: Path):
    store = ActionStore(actions_path(tmp_path / "player_context.json"))
    assert store.all() == []
    first = store.add(prepare(campaign(), "repay_loan", None).action)
    second = store.add(prepare(campaign(), "raise_stability", None).action)
    assert (first.id, second.id) == (1, 2)
    second.status = "done"
    store.update(second)
    assert [a.status for a in store.all()] == ["prepared", "done"]


def test_the_tools_prepare_then_verify(tmp_path: Path):
    context = tmp_path / "player_context.json"
    text = Toolbox(campaign(), None, context).run("prepare_action", {"kind": "repay_loan"})
    assert text.startswith("# Action #1: Repay a loan")
    after = later("loan={ amount=120.0 } => ")
    assert "**Done**" in Toolbox(after, None, context).run("verify_action", {})
    assert ActionStore(actions_path(context)).all()[0].status == "done"
    # An action the save rules out is not recorded.
    blocked = Toolbox(campaign(), None, context).run(
        "prepare_action", {"kind": "complete_mission", "target": "hab_first"}
    )
    assert blocked.startswith("# Not possible now")
    assert len(ActionStore(actions_path(context)).all()) == 1
    with pytest.raises(ToolInputError, match="cannot be carried out"):
        Toolbox(campaign(), None, context).run("prepare_action", {"kind": "fix_deficit"})
    with pytest.raises(ToolInputError, match="No prepared action with id 9"):
        Toolbox(campaign(), None, context).run("verify_action", {"id": 9})
