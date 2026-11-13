import re
from pathlib import Path

from chancellor.app.ui import WEB_DIR, PanelApi, save_changed_script
from chancellor.context.campaign import Campaign
from chancellor.save.parser import parse_lazy

SAVE = "countries={ HAB={ owned_provinces={ 1 } treasury=10.000 powers={ 1 2 3 } } }"


class _Toolbox:
    def __init__(self, campaign: Campaign) -> None:
        self.campaign = campaign


class _Provider:
    """Stands in for CampaignProvider: one fixed save, or a failure."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.save_path = Path("Austria1475_06_21.eu4")

    def toolbox(self) -> _Toolbox:
        if self.error:
            raise self.error
        return _Toolbox(Campaign({"player": "HAB", "date": "1475.6.21"}, parse_lazy(SAVE)))


def test_status_returns_plain_values():
    result = PanelApi(_Provider(), clock=lambda: 1000.0).status()
    assert result["ok"] is True
    assert result["read_at"] == 1000.0
    assert result["status"]["tag"] == "HAB"
    assert result["status"]["save_name"] == "Austria1475_06_21.eu4"
    assert result["status"]["monarch_power"] == (1, 2, 3)


def test_status_reports_errors_to_the_page():
    result = PanelApi(_Provider(RuntimeError("EU4_SAVE_DIR is not set"))).status()
    assert result == {"ok": False, "error": "EU4_SAVE_DIR is not set"}


def test_chat_mode_is_claude_desktop_until_the_player_switches():
    assert PanelApi(_Provider()).chat_mode() == {"mode": "claude_desktop", "api_available": False}


def test_page_and_script_agree_on_element_ids():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    script = (WEB_DIR / "panel.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([\w-]+)"', html))
    used = set(re.findall(r'\$\("([\w-]+)"\)', script))
    used |= set(re.findall(r'setText\("([\w-]+)"', script))
    assert used <= ids, f"panel.js uses ids missing from index.html: {used - ids}"
    assert 'href="panel.css"' in html and 'src="panel.js"' in html


def test_save_changed_script_passes_the_name_as_json():
    script = save_changed_script(Path('Austria "1476".eu4'))
    assert script.startswith("window.dispatchEvent(new CustomEvent('save-changed'")
    assert '{"save": "Austria \\"1476\\".eu4"}' in script


def test_page_listens_for_new_saves():
    script = (WEB_DIR / "panel.js").read_text(encoding="utf-8")
    assert 'addEventListener("save-changed"' in script


def test_alerts_come_back_as_plain_values():
    result = PanelApi(_Provider()).alerts()
    assert result == {"ok": True, "alerts": []}  # a quiet country


def test_alerts_report_errors_to_the_page():
    result = PanelApi(_Provider(RuntimeError("No .eu4 files"))).alerts()
    assert result == {"ok": False, "error": "No .eu4 files"}


def test_dock_reports_errors_to_the_page(monkeypatch):
    from chancellor.app import layout

    monkeypatch.setattr(layout.sys, "platform", "linux")
    api = PanelApi(_Provider())
    assert api.dock() == {"ok": False, "error": "Docking is only available on Windows."}
    assert api.undock() == {"ok": True}  # nothing docked, nothing to undo
