"""The player's context kept per campaign (D-039)."""

from pathlib import Path

import pytest

from chancellor.app.cli import main
from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox, ToolInputError
from chancellor.game.localisation import Localisation
from chancellor.player.context import (
    PlayerContextError,
    PlayerContextStore,
    SaveKey,
    context_path,
)
from chancellor.save.parser import parse


@pytest.fixture
def store(tmp_path: Path) -> PlayerContextStore:
    return PlayerContextStore(tmp_path / "context.json")


AUSTRIA_1492 = SaveKey("id-1492", "HAB", "1492.2.2")


def test_entries_are_kept_per_campaign_and_for_the_player(store):
    goal = store.add(AUSTRIA_1492, "goal", "  Form   Germany ")
    store.add(AUSTRIA_1492, "preference", "No colonies")
    store.add(AUSTRIA_1492, "player", "Not an expert: explain mechanics")
    view = store.view(AUSTRIA_1492)
    assert view.campaign is not None and not view.matched_by_country
    assert [(e.id, e.kind, e.text) for e in view.campaign.entries] == [
        (1, "goal", "Form Germany"),
        (2, "preference", "No colonies"),
    ]
    assert [e.text for e in view.player] == ["Not an expert: explain mechanics"]
    assert goal.game_date == "1492.2.2"
    # Another country's game shares the player's entries, not the campaign's.
    other = store.view(SaveKey("id-cas", "CAS", "1500.1.1"))
    assert other.campaign is None and len(other.player) == 1


def test_a_new_campaign_id_joins_the_same_countrys_campaign(store):
    store.add(AUSTRIA_1492, "goal", "Form Germany")
    later = SaveKey("id-1519", "HAB", "1519.4.2")  # the game gave the save a new id
    view = store.view(later)
    assert view.campaign is not None and view.matched_by_country
    store.add(later, "decision", "Gelre becomes a vassal")
    view = store.view(later)
    assert not view.matched_by_country  # the new id joined on the write
    assert view.campaign.campaign_ids == ["id-1492", "id-1519"]
    assert (view.campaign.first_date, view.campaign.last_date) == ("1492.2.2", "1519.4.2")
    # A new game of the same country starts before it: a campaign of its own.
    assert store.view(SaveKey("id-new", "HAB", "1444.11.11")).campaign is None


def test_remove_and_replace(store):
    goal = store.add(AUSTRIA_1492, "goal", "Take Naples")
    changed = store.replace(AUSTRIA_1492, goal.id, "Take Naples after Gelre")
    assert (changed.kind, changed.text) == ("goal", "Take Naples after Gelre")
    assert store.remove(AUSTRIA_1492, changed.id).text == "Take Naples after Gelre"
    assert store.view(AUSTRIA_1492).campaign.entries == []
    with pytest.raises(PlayerContextError, match="No entry #99"):
        store.remove(AUSTRIA_1492, 99)
    kept = store.add(AUSTRIA_1492, "goal", "Keep this")
    with pytest.raises(PlayerContextError, match="empty"):
        store.replace(AUSTRIA_1492, kept.id, "   ")
    assert [e.text for e in store.view(AUSTRIA_1492).campaign.entries] == ["Keep this"]


def test_bad_requests(store):
    with pytest.raises(PlayerContextError, match="Unknown kind 'wish'"):
        store.add(AUSTRIA_1492, "wish", "x")
    with pytest.raises(PlayerContextError, match="under 300"):
        store.add(AUSTRIA_1492, "note", "x" * 301)


def test_a_broken_file_reads_as_empty(store):
    store.path.write_text("{not json", encoding="utf-8")
    assert store.view(AUSTRIA_1492).campaign is None
    assert store.add(AUSTRIA_1492, "goal", "Form Germany").id == 1


def test_context_path_is_in_the_games_user_folder(tmp_path: Path):
    saves = tmp_path / "Europa Universalis IV" / "save games"
    assert context_path(saves) == (
        tmp_path / "Europa Universalis IV" / "eu4-chancellor" / "player_context.json"
    )


@pytest.fixture
def toolbox(tmp_path: Path) -> Toolbox:
    meta = {"player": "HAB", "date": "1519.4.2", "campaign_id": "id-1519"}
    campaign = Campaign(meta, parse("countries={ HAB={ } }"), Localisation({"HAB": "Austria"}))
    return Toolbox(campaign, None, tmp_path / "context.json")


def test_the_tools(toolbox):
    empty = toolbox.run("get_player_context", {})
    assert empty.startswith("# Player context: Austria (HAB)")
    assert "Nothing recorded yet for this campaign" in empty
    added = toolbox.run(
        "update_player_context", {"action": "add", "kind": "goal", "text": "Formar Alemania"}
    )
    assert added == "Recorded #1 (goal): Formar Alemania"
    text = toolbox.run("get_player_context", {})
    assert "## Goals\n\n- #1 Formar Alemania (recorded at 1519.4.2)" in text
    assert "Record only what the player says" in text
    replaced = toolbox.run(
        "update_player_context", {"action": "replace", "entry": 1, "text": "Formar el Imperio"}
    )
    assert replaced == "Replaced #1 with #2 (goal): Formar el Imperio"
    assert toolbox.run("update_player_context", {"action": "remove", "entry": 2}).startswith(
        "Removed #2"
    )
    for args, message in (
        ({"action": "add", "text": "x"}, "add needs `kind` and `text`"),
        ({"action": "remove"}, "remove needs `entry`"),
        ({"action": "replace", "entry": 1}, "replace needs `text`"),
        ({"action": "drop"}, "must be add, remove or replace"),
        ({"action": "add", "kind": "wish", "text": "x"}, "Unknown kind"),
    ):
        with pytest.raises(ToolInputError, match=message):
            toolbox.run("update_player_context", args)


def test_cli_shows_and_removes(toolbox, tmp_path: Path, monkeypatch, capsys):
    toolbox.run("update_player_context", {"action": "add", "kind": "goal", "text": "Gelre"})
    monkeypatch.setattr("chancellor.app.cli.context_path", lambda _: toolbox.context_file)
    monkeypatch.setattr(
        "chancellor.app.cli._load_campaign", lambda args, settings: (toolbox.campaign, tmp_path)
    )
    assert main(["player-context"]) == 0
    assert "- #1 Gelre" in capsys.readouterr().out
    assert main(["player-context", "--remove", "1"]) == 0
    captured = capsys.readouterr()
    assert "Removed #1 (goal): Gelre" in captured.err
    assert "Nothing recorded yet" in captured.out
    assert main(["player-context", "--remove", "7"]) == 1
