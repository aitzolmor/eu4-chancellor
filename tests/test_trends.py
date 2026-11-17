"""Trend charts and backfilling the journal from older saves (D-045)."""

import json
from pathlib import Path

from chancellor.app.cli import main
from chancellor.app.ui import WEB_DIR
from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.game.localisation import Localisation
from chancellor.player.backfill import backfill, pick, render_groups, save_groups
from chancellor.player.journal import TREND_KEYS, render_trends, trend_data
from chancellor.save.loader import load_save
from chancellor.save.parser import parse

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"


def _save(folder: Path, name: str, date: str, campaign_id: str, player: str = "HAB") -> Path:
    """The fixture save, with its date, player and campaign id changed."""
    text = FIXTURE.read_text(encoding="cp1252")
    text = text.replace("date=1471.10.2", f"date={date}", 1)
    text = text.replace('player="HAB"', f'player="{player}"\ncampaign_id="{campaign_id}"', 1)
    path = folder / name
    path.write_text(text, encoding="cp1252")
    return path


def test_saves_are_grouped_by_campaign_id_and_picked_by_prefix(tmp_path: Path):
    _save(tmp_path, "a.eu4", "1460.1.1", "aaaa1111-x")
    _save(tmp_path, "b.eu4", "1455.1.1", "aaaa1111-x")
    _save(tmp_path, "c.eu4", "1470.1.1", "bbbb2222-y")
    _save(tmp_path, "d.eu4", "1470.1.1", "cccc3333-z", player="CAS")  # another country
    groups = save_groups(tmp_path, "HAB")
    assert [(g.campaign_id, g.first, g.last, len(g.saves)) for g in groups] == [
        ("aaaa1111-x", "1455.1.1", "1460.1.1", 2),
        ("bbbb2222-y", "1470.1.1", "1470.1.1", 1),
    ]
    text = render_groups(groups, "bbbb2222-y")
    assert "aaaa1111  1455.1.1 to 1460.1.1  (2 saves)" in text
    assert "bbbb2222  1470.1.1 to 1470.1.1  (1 saves)  <- the current save" in text
    assert [g.campaign_id for g in pick(groups, ["AAAA", " "])] == ["aaaa1111-x"]
    read: list[str] = []
    count = backfill(groups, lambda path: read.append(path.name) or True)
    assert (count, read) == (3, ["b.eu4", "a.eu4", "c.eu4"])  # oldest first


def test_backfilled_saves_join_the_current_campaigns_journal(tmp_path: Path):
    saves = tmp_path / "save games"
    saves.mkdir()
    _save(saves, "old.eu4", "1455.1.1", "old-id")
    current = Campaign.from_raw(load_save(_save(saves, "new.eu4", "1471.10.2", "new-id")))
    toolbox = Toolbox(current, None, tmp_path / "player_context.json")
    toolbox.remember_save()
    assert toolbox.remember_other(Campaign.from_raw(load_save(saves / "old.eu4"))) is True
    data = toolbox.trends()
    assert data["dates"] == ["1455.1.1", "1471.10.2"]
    assert set(data["series"]) == set(TREND_KEYS)
    assert toolbox.run("get_trends", {}).startswith("# Trends: HAB (HAB)")  # no localisation


def test_trend_data_and_its_table():
    campaign = Campaign({"player": "HAB", "date": "1520.1.1"}, parse(""), Localisation())
    snapshots = [
        {"date": "1500.1.1", "numbers": {"treasury": 100.0}, "wars": []},
        {"date": "1510.7.1", "numbers": {"treasury": 50.0}, "wars": ["War on Gelre"]},
        {"date": "1530.1.1", "numbers": {"treasury": 9.0}, "wars": []},  # after this save
    ]
    data = trend_data(snapshots, "1520.1.1", campaign)
    assert data["dates"] == ["1500.1.1", "1510.7.1"]
    assert data["years"] == [1500.0, 1510.5]
    assert data["series"]["treasury"] == [100.0, 50.0]
    assert data["series"]["income"] == [None, None]
    assert data["events"] == [
        {"date": "1510.7.1", "year": 1510.5, "text": "War began: War on Gelre"}
    ]
    table = render_trends(data, "Austria (HAB)")
    assert "| 1500.1.1 | 100 | - |" in table and "- 1510.7.1: War began: War on Gelre" in table
    assert "Not enough saves" in render_trends(trend_data([], "1520.1.1", campaign), "X")


def test_cli_backfill_lists_then_reads(tmp_path: Path, monkeypatch, capsys):
    saves = tmp_path / "save games"
    saves.mkdir()
    _save(saves, "old.eu4", "1455.1.1", "old-id")
    current = _save(saves, "new.eu4", "1471.10.2", "new-id")
    monkeypatch.setenv("EU4_SAVE_DIR", str(saves))
    monkeypatch.delenv("EU4_GAME_DIR", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    assert main(["journal", "--backfill", "--save", str(current)]) == 0
    listing = capsys.readouterr().out
    assert "old-id  1455.1.1 to 1455.1.1  (1 saves)" in listing
    assert "new-id  1471.10.2 to 1471.10.2  (1 saves)  <- the current save" in listing
    assert main(["journal", "--backfill", "--ids", "old", "--save", str(current)]) == 0
    assert "Recorded 1 saves in the journal." in capsys.readouterr().out
    journal = json.loads((tmp_path / "eu4-chancellor" / "journal.json").read_text("utf-8"))
    assert [s["date"] for s in next(iter(journal.values()))] == ["1455.1.1", "1471.10.2"]
    assert main(["journal", "--backfill", "--ids", "zzz", "--save", str(current)]) == 1


def test_the_charts_tab_is_wired():
    script = (WEB_DIR / "panel.js").read_text(encoding="utf-8")
    charts = (WEB_DIR / "charts.js").read_text(encoding="utf-8")
    assert 'import { renderCharts } from "./charts.js";' in script
    assert "window.pywebview.api.trends()" in script
    # One measure per chart (never two y-scales); income and expenses share a unit.
    assert '{ title: "Income and expenses (a month)", keys: ["income", "expenses"] }' in charts
