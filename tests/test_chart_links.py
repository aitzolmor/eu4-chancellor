"""Pointing the player at a chart (D-068) and opening PDX Tools (D-067)."""

import re
from pathlib import Path
from types import SimpleNamespace

from chancellor.app import ui
from chancellor.app.ui import WEB_DIR, PanelApi
from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.player.charts import CHARTS, read_request, render_chart, request_path, write_request
from chancellor.save.loader import load_save

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"

DATA = {
    "dates": ["1500.1.1", "1510.1.1", "1520.1.1"],
    "series": {"treasury": [100.0, None, 340.5], "development": [300.0, 320.0, 360.0]},
    "labels": {"treasury": "treasury", "development": "development"},
    "events": [{"date": "1510.1.1", "year": 1510, "text": "War began: Conquest of Bohemia"}],
    "budget": {"income": {"Taxation": [10.0, 12.0, 14.0]}, "expenses": {}, "one_off": []},
    "names": {"HAB": "Austria", "FRA": "Francia"},
    "compare": ["FRA", None],
    "others": {"FRA": {"development": [500.0, 510.0, 520.0]}},
}


def test_the_tool_and_the_page_name_the_same_charts():
    script = (WEB_DIR / "charts.js").read_text(encoding="utf-8")
    assert set(re.findall(r'\bid: "(\w+)"', script)) == set(CHARTS)
    assert 'window.addEventListener("show-chart"' in (WEB_DIR / "panel.js").read_text(
        encoding="utf-8"
    )


def test_a_request_round_trips_and_bad_files_are_ignored(tmp_path: Path):
    path = request_path(tmp_path / "player_context.json")
    assert read_request(path) is None
    written = write_request(path, "treasury")
    assert read_request(path) == written
    path.write_text('{"chart": "no_such_chart"}', encoding="utf-8")
    assert read_request(path) is None
    path.write_text("not json", encoding="utf-8")
    assert read_request(path) is None


def test_the_chart_comes_with_its_numbers():
    text = render_chart(DATA, CHARTS["treasury"], shown=True)
    assert text.startswith("# Chart: Treasury (ducats)")
    assert "| 1500.1.1 | 100 |" in text and "| 1510.1.1 | - |" in text
    assert "- 1510.1.1: War began: Conquest of Bohemia" in text
    assert 'Refer the player to the chart "Treasury (ducats)"' in text
    compare = render_chart(DATA, CHARTS["compare_development"], shown=True)
    assert "| Date | Austria | Francia |" in compare and "| 1520.1.1 | 360 | 520 |" in compare
    budget = render_chart(DATA, CHARTS["income_by_source"], shown=False)
    assert "| Date | Taxation |" in budget and "could not be asked" in budget
    assert "Not enough saves" in render_chart(DATA, CHARTS["one_off_spending"], shown=True)


def test_show_chart_asks_the_panel(tmp_path: Path):
    campaign = Campaign.from_raw(load_save(FIXTURE))
    context = tmp_path / "player_context.json"
    toolbox = Toolbox(campaign, None, context)
    toolbox.remember_save()
    text = toolbox.run("show_chart", {"chart": "regiments"})
    assert text.startswith("# Chart: Regiments")
    assert read_request(request_path(context))["chart"] == "regiments"
    assert any(d["name"] == "show_chart" for d in toolbox.definitions)


class _Window:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def show(self) -> None:
        self.calls.append("show")

    def restore(self) -> None:
        self.calls.append("restore")

    def evaluate_js(self, script: str) -> None:
        self.calls.append(script)


def test_the_panel_comes_up_on_the_chart():
    api = PanelApi(SimpleNamespace())
    window = _Window()
    api._attach(panel=window)
    api._mode = "two_screens"
    api.show_requested_chart({"chart": "treasury", "at": 1})
    assert window.calls[:2] == ["show", "restore"]
    assert "show-chart" in window.calls[2] and '"chart": "treasury"' in window.calls[2]


def test_only_new_requests_are_shown(tmp_path: Path):
    path = tmp_path / "chart_request.json"
    write_request(path, "treasury")  # from before the panel started: not shown
    api = PanelApi(SimpleNamespace())
    shown: list[str] = []
    api.show_requested_chart = lambda request: shown.append(request["chart"])
    waits = iter([False, False, True])

    def wait(_interval: float) -> bool:
        stop = next(waits)
        if not stop and not shown and len(list(tmp_path.iterdir())) == 1:
            write_request(path, "development")
        return stop

    api._stop_icon = SimpleNamespace(wait=wait)
    api._watch_chart_requests(path, interval=0)
    assert shown == ["development"]


def test_pdx_tools_opens_with_the_latest_save(tmp_path: Path, monkeypatch):
    (tmp_path / "Austria1539_12_25.eu4").write_text("x", encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(ui.webbrowser, "open", opened.append)
    monkeypatch.setattr(ui.subprocess, "Popen", lambda args: opened.append(" ".join(args)))
    api = PanelApi(SimpleNamespace(settings=SimpleNamespace(save_dir=tmp_path)))
    assert api.open_pdx_tools() == {"ok": True, "save": "Austria1539_12_25.eu4"}
    assert opened[0] == ui.PDX_TOOLS_URL
    no_folder = PanelApi(SimpleNamespace(settings=SimpleNamespace(save_dir=None)))
    assert no_folder.open_pdx_tools()["ok"] is False
