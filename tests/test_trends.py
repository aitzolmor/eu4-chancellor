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


def test_snapshots_keep_the_rivals_and_great_powers_numbers():
    from chancellor.player.journal import take_snapshot

    world = """
    countries={
        HAB={ owned_provinces={ 1 } raw_development=300.0 rival={ country="FRA" } }
        FRA={ owned_provinces={ 2 3 } raw_development=800.0 ledger={ lastmonthincome=94.0 } }
        TUR={ owned_provinces={ 4 } raw_development=990.0 }
    }
    great_powers={ original={ rank=2 country="HAB" } original={ rank=1 country="TUR" } }
    """
    campaign = Campaign({"player": "HAB", "date": "1525.9.6"}, parse(world), Localisation())
    snapshot = take_snapshot(campaign)
    assert snapshot["rivals"] == ["FRA"] and snapshot["great_powers"] == ["TUR"]
    assert snapshot["others"]["FRA"] == {
        "development": 800.0,
        "regiments": 0.0,
        "income": 94.0,
        "provinces": 2.0,
    }  # numbers the save does not have are left out, not zero
    assert list(snapshot["others"]) == ["FRA", "TUR"]  # rivals first


def test_trends_compare_with_rivals_or_else_great_powers():
    names = {"HAB": "Austria", "FRA": "Francia", "TUR": "Otomanos"}
    campaign = Campaign({"player": "HAB", "date": "1525.1.1"}, parse(""), Localisation(names))
    first = {
        "date": "1500.1.1",
        "numbers": {"development": 300.0},
        "others": {"TUR": {"development": 700.0}},
    }
    last = {
        "date": "1520.1.1",
        "numbers": {"development": 600.0},
        "rivals": ["FRA"],
        "great_powers": ["TUR"],
        "others": {"FRA": {"development": 800.0}, "TUR": {"development": 990.0}},
    }
    data = trend_data([first, last], "1525.1.1", campaign)
    assert (data["compare"], data["compare_basis"]) == (["FRA", None, None], "rivals")
    assert data["others"]["FRA"]["development"] == [None, 800.0]  # not recorded at first
    assert data["names"] == {"HAB": "Austria", "FRA": "Francia"}
    table = render_trends(data, "Austria (HAB)")
    assert "Compared with the rivals, 1500.1.1 → 1520.1.1:" in table
    assert "| Austria | 300 → 600 |" in table and "| Francia | 800 → 800 |" in table
    last["rivals"] = []  # no rivals: the strongest great powers instead
    data = trend_data([first, last], "1525.1.1", campaign)
    assert (data["compare"], data["compare_basis"]) == (["TUR"], "great powers")
    assert data["others"]["TUR"]["development"] == [700.0, 990.0]


def test_the_comparison_charts_use_three_hues_and_a_dashed_fourth():
    charts = (WEB_DIR / "charts.js").read_text(encoding="utf-8")
    css = (WEB_DIR / "panel.css").read_text(encoding="utf-8")
    assert '{ title: "Development", key: "development" }' in charts
    assert '"var(--series-other)"' in charts and '"stroke-dasharray"' in charts
    assert "--series-other: #9aa3b5" in css


def test_a_rival_keeps_its_colour_when_another_changes():
    from chancellor.player.journal import rival_slots

    history = [
        {"date": "1500.1.1", "rivals": ["FRA", "POL", "TUR"]},
        {"date": "1510.1.1"},  # a trimmed snapshot without the lists changes nothing
        {"date": "1520.1.1", "rivals": ["FRA", "HUN", "TUR"]},  # Hungary replaces Poland
        {"date": "1530.1.1", "rivals": ["BOH", "FRA", "TUR"]},  # Bohemia replaces Hungary
    ]
    assert rival_slots(history[:1]) == ["FRA", "POL", "TUR"]
    assert rival_slots(history[:3]) == ["FRA", "HUN", "TUR"]  # France and Turkey stay put
    assert rival_slots(history) == ["FRA", "BOH", "TUR"]
    assert rival_slots([{"date": "1540.1.1", "rivals": ["TUR"]}]) == ["TUR", None, None]


def test_old_snapshots_keep_the_others_once_a_year(tmp_path: Path):
    from chancellor.player.journal import DETAILED, JournalStore

    store = JournalStore(tmp_path / "journal.json")
    for month in range(1, 13):  # a year of monthly autosaves, then the detailed ones
        store.record("c", {"date": f"1500.{month}.1", "numbers": {}, "others": {"FRA": {}}})
    for day in range(1, DETAILED + 1):
        store.record("c", {"date": f"1501.1.{day}", "numbers": {}, "others": {"FRA": {}}})
    kept = store.snapshots("c")
    assert len(kept) == 12 + DETAILED  # every save keeps its own numbers
    assert ["others" in s for s in kept[:12]] == [True] + [False] * 11  # once in 1500
    assert all("others" in s for s in kept[12:])


def test_a_country_that_formed_another_keeps_its_history():
    world = 'countries={ HAB={ } SPA={ owned_provinces={ 1 } previous_country_tags="CAS" } }'
    names = {"HAB": "Austria", "SPA": "España"}
    campaign = Campaign({"player": "HAB", "date": "1525.1.1"}, parse(world), Localisation(names))
    snapshots = [
        {"date": "1500.1.1", "numbers": {}, "others": {"CAS": {"development": 400.0}}},
        {"date": "1520.1.1", "numbers": {}, "others": {"SPA": {"development": 800.0}}},
    ]
    data = trend_data(snapshots, "1525.1.1", campaign, chosen=["SPA"])
    assert data["compare_basis"] == "countries you picked"
    assert data["others"]["SPA"]["development"] == [400.0, 800.0]  # Castile, then Spain


def test_the_picked_countries_are_saved_tracked_and_charted(tmp_path: Path):
    from chancellor.app.ui import PanelApi

    world = """
    countries={
        HAB={ owned_provinces={ 1 } raw_development=300.0 rival={ country="FRA" } }
        FRA={ owned_provinces={ 2 } raw_development=800.0 }
        CAS={ owned_provinces={ 3 } raw_development=400.0 }
    }
    """
    names = {"HAB": "Austria", "FRA": "Francia", "CAS": "Castilla"}
    meta = {"player": "HAB", "date": "1525.1.1", "campaign_id": "c1"}
    campaign = Campaign(meta, parse(world), Localisation(names))
    toolbox = Toolbox(campaign, None, tmp_path / "context.json")
    toolbox.remember_save()
    assert toolbox.trends()["compare"] == ["FRA", None, None]  # the rivals by default
    assert toolbox.set_compare(["Castilla", "CAS", "Francia"]) == ["CAS", "FRA"]
    toolbox.remember_save()
    data = toolbox.trends()
    assert (data["compare"], data["compare_basis"]) == (["CAS", "FRA"], "countries you picked")
    assert data["others"]["CAS"]["development"] == [400.0]
    options = toolbox.compare_options()
    assert options["picked"] == ["CAS", "FRA"]
    assert {o["tag"] for o in options["options"]} >= {"CAS", "FRA"}
    assert toolbox.trends(["FRA"])["compare"] == ["FRA"]  # ad hoc: the picks stay
    assert toolbox.compare_options()["picked"] == ["CAS", "FRA"]
    assert toolbox.set_compare([]) == []
    assert toolbox.trends()["compare"] == ["FRA", None, None]

    class Provider:
        save_path = None

        def toolbox(self) -> Toolbox:
            return toolbox

    api = PanelApi(Provider())
    assert api.set_compare(["Castilla"]) == {"ok": True, "picked": ["CAS"]}
    assert api.trends()["compare"]["picked"] == ["CAS"]
    assert api.set_compare(["Narnia"])["ok"] is False


def test_the_budget_is_recorded_and_charted_by_category(tmp_path: Path):
    from chancellor.player.journal import JournalStore, take_snapshot

    world = """
    countries={ HAB={ ledger={
        lastmonthincometable={ 24.97 16.35 13.84 12.93 0 3.47 0 0 10.42 }
        lastmonthexpensetable={ 10.5 0 4.6 0 0 0 35.1 1.7 11.4 0 0 0 0 20.0 }
    } } }
    """
    campaign = Campaign({"player": "HAB", "date": "1535.8.2"}, parse(world), Localisation())
    snapshot = take_snapshot(campaign)
    assert snapshot["budget"]["income"]["War reparations"] == 10.42
    assert snapshot["budget"]["expenses"]["Building fortresses"] == 20.0
    older = {"date": "1530.1.1", "tag": "HAB", "numbers": {}}  # recorded before D-053
    middle = {
        "date": "1533.1.1",
        "tag": "HAB",
        "numbers": {},
        "budget": {
            "income": {"Taxation": 20.0, "Gifts": 2.0},
            "expenses": {"Army maintenance": 30.0},
        },
    }
    data = trend_data([older, middle, snapshot], "1535.8.2", campaign)
    income = data["budget"]["income"]
    assert list(income) == ["Taxation", "Production", "Trade", "Other"]
    assert income["Taxation"] == [None, 20.0, 24.97]
    assert income["Other"] == [None, 2.0, round(12.93 + 3.47 + 10.42, 2)]
    expenses = data["budget"]["expenses"]  # recurring only; building is one-off
    assert list(expenses) == [
        "Army maintenance",
        "Fort maintenance",
        "Advisor maintenance",
        "Other",
    ]
    assert data["budget"]["one_off"] == [None, 0.0, 20.0]
    text = render_trends(data, "Austria")
    assert "Income by source a month, first and latest save that recorded it:" in text
    assert "| Taxation | 20 → 25 |" in text
    journal = JournalStore(tmp_path / "journal.json")
    for i in range(30):  # trimmed old snapshots (past DETAILED) keep the budget
        journal.record("c", {**snapshot, "date": f"{1500 + i}.1.1", "wars": ["x"]})
    oldest = journal.snapshots("c")[0]
    assert "budget" in oldest and "wars" not in oldest


def test_the_budget_charts_are_drawn():
    charts = (WEB_DIR / "charts.js").read_text(encoding="utf-8")
    assert '"Income by source (a month)", budgetSeries(budget.income)' in charts
    assert '"Recurring expenses (a month)", budgetSeries(budget.expenses)' in charts
    assert "const index = name === OTHER ? DASHED : i;" in charts  # "Other" is the dashed line
    assert "budgetColumns(data)" in charts  # and in the table
