"""The campaign journal: what changed between saves (D-043)."""

from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.game.localisation import Localisation
from chancellor.player.journal import (
    DETAILED,
    JournalStore,
    changes,
    journal_entries,
    journal_path,
    render_journal,
    take_snapshot,
)
from chancellor.save.parser import parse

NAMES = {"HAB": "Austria", "SAV": "Saboya", "GEL": "Gelre", "BOH": "Bohemia"}

BEFORE = """
countries={
    HAB={ owned_provinces={ 1 2 } core_provinces={ 1 } treasury=55.0 raw_development=368.0
          technology={ adm_tech=7 dip_tech=7 mil_tech=9 } allies={ SAV }
          active_idea_groups={ HAB_ideas=0 diplomatic_ideas=2 }
          monarch={ id=1 type=48 }
          history={ 1440.1.1={ monarch={ name="Ladislaus" dynasty="von Habsburg"
                                          id={ id=1 type=48 } } } } }
    SAV={ owned_provinces={ 9 } }
}
provinces={ -1={ owner="HAB" name="Wien" } -2={ owner="HAB" name="Padua" } }
"""

AFTER = """
countries={
    HAB={ owned_provinces={ 1 2 3 } core_provinces={ 1 2 } treasury=122.0 raw_development=377.0
          technology={ adm_tech=8 dip_tech=7 mil_tech=9 } subjects={ GEL }
          active_idea_groups={ HAB_ideas=0 diplomatic_ideas=3 offensive_ideas=0 }
          monarch={ id=2 type=48 } heir={ id=3 type=48 }
          history={ 1440.1.1={ monarch={ name="Ladislaus" dynasty="von Habsburg"
                                          id={ id=1 type=48 } } }
                    1510.1.1={ monarch={ name="Maximilian" dynasty="von Habsburg"
                                          id={ id=2 type=48 } }
                               heir={ name="Ferdinand" dynasty="von Habsburg"
                                      id={ id=3 type=48 } } } } }
    SAV={ owned_provinces={ 9 } }
    GEL={ owned_provinces={ 4 } overlord="HAB" }
}
provinces={ -1={ owner="HAB" name="Wien" } -2={ owner="HAB" name="Padua" }
            -3={ owner="HAB" name="Istrien" } }
active_war={ name="Conquest of Gelre" attackers={ "HAB" } defenders={ "GEL" } }
"""


def _campaign(world: str, date: str, campaign_id: str = "c1") -> Campaign:
    meta = {"player": "HAB", "date": date, "campaign_id": campaign_id}
    return Campaign(meta, parse(world), Localisation(NAMES))


def test_changes_between_two_saves():
    before = take_snapshot(_campaign(BEFORE, "1507.11.1"))
    after_campaign = _campaign(AFTER, "1514.2.17")
    after = take_snapshot(after_campaign)
    events = changes(before, after, after_campaign)
    assert "Gained Istrien" in events
    assert "Cored Padua" in events
    assert "War began: Conquest of Gelre" in events
    assert "Alliance ended with: Saboya" in events
    assert "New subject: Gelre" in events
    assert "New ruler: Maximilian von Habsburg (after Ladislaus von Habsburg)" in events
    assert "New heir: Ferdinand von Habsburg" in events
    assert "diplomatic ideas: 2 → 3 ideas" in events
    assert "New idea group: offensive ideas" in events
    assert "Administrative technology: 7 → 8" in events
    numbers = next(e for e in events if e.startswith("Numbers: "))
    assert "treasury 55 → 122" in numbers and "development 368 → 377" in numbers
    assert "provinces 2 → 3" in numbers
    assert changes(after, after, after_campaign) == []


def test_the_store_keeps_one_snapshot_a_date_and_trims_old_ones(tmp_path: Path):
    store = JournalStore(tmp_path / "journal.json")
    first = {"date": "1500.1.1", "tag": "HAB", "numbers": {"treasury": 1.0}, "wars": []}
    assert store.record("c", first) is True
    assert store.record("c", first) is False  # the same save read again
    store.record("c", {**first, "numbers": {"treasury": 2.0}})  # same date: replaced
    assert [s["numbers"]["treasury"] for s in store.snapshots("c")] == [2.0]
    for month in range(1, DETAILED + 3):
        store.record("c", {**first, "date": f"1501.{month}.1"})
    kept = store.snapshots("c")
    assert len(kept) == DETAILED + 3
    assert "wars" not in kept[0] and "numbers" in kept[0]  # trimmed to its numbers
    assert "wars" in kept[-1]
    (tmp_path / "journal.json").write_text("{broken", encoding="utf-8")
    assert store.snapshots("c") == []


def test_entries_stop_at_the_save_being_read():
    campaign = _campaign(AFTER, "1514.2.17")
    snapshots = [
        {"date": "1500.1.1", "numbers": {"treasury": 1.0}},
        {"date": "1510.1.1", "numbers": {"treasury": 5.0}},
        {"date": "1520.1.1", "numbers": {"treasury": 9.0}},  # a later save, reloaded from
    ]
    entries = journal_entries(snapshots, "1514.2.17", campaign, saves=6)
    assert entries == [("1500.1.1", "1510.1.1", ["Numbers: treasury 1 → 5"])]
    text = render_journal(entries, "Austria (HAB)", 3)
    assert "## 1500.1.1 → 1510.1.1" in text and "- Numbers: treasury 1 → 5" in text
    assert "Only 1 save recorded" in render_journal([], "Austria (HAB)", 1)


def test_the_toolbox_records_saves_and_reports_the_journal(tmp_path: Path):
    context = tmp_path / "player_context.json"
    first = Toolbox(_campaign(BEFORE, "1507.11.1", "id-a"), None, context)
    assert first.remember_save() is True
    assert "Only 1 save recorded" in first.run("get_campaign_journal", {})
    # The game gave the next save a new campaign id: matched by country and date.
    second = Toolbox(_campaign(AFTER, "1514.2.17", "id-b"), None, context)
    assert second.remember_save() is True
    journal = second.run("get_campaign_journal", {"saves": 3})
    assert journal.startswith("# Campaign journal: Austria (HAB)")
    assert "## 1507.11.1 → 1514.2.17" in journal and "- Gained Istrien" in journal
    assert journal_path(context).is_file()
    hint = second.run("get_country_briefing", {}).rstrip().splitlines()[-1]
    assert "Since the previous save (1507.11.1):" in hint and "(get_campaign_journal)" in hint
    since = second.player_plan()["since"]
    assert since[0]["from"] == "1507.11.1" and "Gained Istrien" in since[0]["events"]


@pytest.mark.parametrize("saves", [0, 99])
def test_the_number_of_steps_is_bounded(tmp_path: Path, saves: int):
    toolbox = Toolbox(_campaign(BEFORE, "1507.11.1"), None, tmp_path / "c.json")
    toolbox.remember_save()
    assert toolbox.run("get_campaign_journal", {"saves": saves}).startswith("# Campaign")
