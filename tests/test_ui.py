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
    assert PanelApi(_Provider()).chat_mode()["mode"] == "claude_desktop"


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


class _Window:
    """Stands in for a pywebview window."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def show(self) -> None:
        self.calls.append("show")

    def hide(self) -> None:
        self.calls.append("hide")

    def destroy(self) -> None:
        self.calls.append("destroy")

    def evaluate_js(self, script: str) -> None:
        self.calls.append(script)

    def set_open(self, open_: bool) -> None:  # the floating icon's method
        self.calls.append(f"set_open {open_}")


def test_layout_mode_follows_the_mode():
    api = PanelApi(_Provider())
    api._attach(panel=_Window())
    assert api.layout_mode() == {"mode": "two_screens", "docked": False, "side": "right"}
    api._mode = "overlay"
    assert api.layout_mode() == {"mode": "overlay", "docked": False, "side": "right"}


def test_overlay_needs_the_panel_window():
    api = PanelApi(_Provider())
    assert api.toggle_overlay() == {"ok": False, "error": "The panel window is not ready yet."}


def test_quit_closes_every_window_off_the_calling_thread():
    import time

    panel, icon = _Window(), _Window()
    api = PanelApi(_Provider())
    api._attach(panel=panel, icon=icon)
    assert api.quit() == {"ok": True}
    deadline = time.monotonic() + 2
    while "destroy" not in icon.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert panel.calls == ["destroy"] and icon.calls == ["destroy"]


def test_closing_the_panel_in_overlay_mode_only_puts_it_away():
    from chancellor.app.ui import _on_closing

    api = PanelApi(_Provider())
    api._mode = "overlay"
    assert _on_closing(api) is False  # the close is cancelled
    api._quitting = True
    assert _on_closing(api) is True  # unless the app is quitting


def test_closing_the_panel_on_two_screens_quits():
    from chancellor.app.ui import _on_closing

    icon = _Window()
    docker = _ScreenDocker(docked=True)
    api = PanelApi(_Provider())
    api._docker = docker
    api._attach(panel=_Window(), icon=icon)
    assert _on_closing(api) is True
    assert api._quitting and api._stop_icon.is_set()
    assert icon.calls == ["destroy"]
    assert docker.calls == ["undock"]


class _Docker:
    """Stands in for layout.Docker: records focus requests, or fails like it would."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.focused = 0

    def focus_chat(self) -> None:
        if self.error:
            raise self.error
        self.focused += 1


def test_quick_questions_are_plain_values():
    questions = PanelApi(_Provider()).quick_questions()["questions"]
    assert [q["id"] for q in questions] == ["campaign", "expand", "threats", "goals"]
    assert all(q["label"] and len(q["prompt"]) > len(q["label"]) for q in questions)


def test_ask_copies_the_prompt_and_brings_claude_desktop_forward():
    copied: list[str] = []
    api = PanelApi(_Provider(), copy=copied.append)
    api._docker = _Docker()
    assert api.ask("expand") == {"ok": True, "focused": True}
    assert copied[0].startswith("Where should I expand next?")
    assert api._docker.focused == 1


def test_ask_still_copies_when_claude_desktop_is_closed():
    from chancellor.app.layout import DockError

    copied: list[str] = []
    api = PanelApi(_Provider(), copy=copied.append)
    api._docker = _Docker(DockError("Open Claude Desktop first, then try again."))
    result = api.ask("campaign")
    assert result == {
        "ok": True,
        "focused": False,
        "error": "Open Claude Desktop first, then try again.",
    }
    assert len(copied) == 1


def test_ask_reports_unknown_questions_and_clipboard_failures():
    from chancellor.app.clipboard import ClipboardError

    api = PanelApi(_Provider(), copy=lambda _text: None)
    assert api.ask("nope") == {"ok": False, "error": "Unknown question 'nope'."}

    def broken(_text: str) -> None:
        raise ClipboardError("Could not open the clipboard")

    api = PanelApi(_Provider(), copy=broken)
    assert api.ask("campaign") == {"ok": False, "error": "Could not open the clipboard"}


def test_hotkey_is_reported_only_when_registered():
    from chancellor.app.hotkey import GlobalHotkey

    api = PanelApi(_Provider())
    assert api.hotkey() == {"registered": False}
    api._hotkey = GlobalHotkey("ctrl+shift+space", lambda: None)
    assert api.hotkey() == {"registered": False}  # not started
    api._hotkey.registered = True
    assert api.hotkey() == {"registered": True, "keys": "Ctrl+Shift+Space"}


def test_hotkey_brings_claude_desktop_forward_on_two_screens():
    api = PanelApi(_Provider())
    api._docker = _Docker()
    api._attach(panel=_Window())
    api._on_hotkey()
    assert api._docker.focused == 1


class _ScreenDocker:
    """Stands in for layout.Docker when screens come and go."""

    def __init__(self, docked: bool = False) -> None:
        self.docked = docked
        self.calls: list[str] = []

    def undock(self) -> None:
        self.calls.append("undock")
        self.docked = False

    def dock(self, side: str = "right") -> dict:
        self.calls.append("dock")
        self.docked = True
        return {"mode": "two_screens", "game_found": True}


def test_second_screen_dropping_switches_to_the_overlay():
    from chancellor.app.ui import LAYOUT_CHANGED_SCRIPT

    panel, icon = _Window(), _Window()
    docker = _ScreenDocker(docked=True)
    api = PanelApi(_Provider())
    api._docker = docker
    api._attach(panel=panel, icon=icon)

    api._set_screens(1)
    assert api._mode == "overlay"
    assert docker.calls == ["undock"]  # docked windows go back where they were
    assert panel.calls == ["hide", LAYOUT_CHANGED_SCRIPT]
    assert icon.calls == ["set_open False"]

    api._set_screens(1)  # no change, nothing happens
    assert panel.calls == ["hide", LAYOUT_CHANGED_SCRIPT]


def test_second_screen_returning_docks_again_if_it_was_docked():
    from chancellor.app.ui import LAYOUT_CHANGED_SCRIPT

    panel = _Window()
    docker = _ScreenDocker(docked=True)
    api = PanelApi(_Provider())
    api._docker = docker
    api._attach(panel=panel, icon=_Window())
    api._set_screens(1)
    panel.calls.clear()

    api._set_screens(2)
    assert api._mode == "two_screens"
    assert docker.calls == ["undock", "dock"]
    assert panel.calls == ["show", LAYOUT_CHANGED_SCRIPT]
    assert api.layout_mode() == {"mode": "two_screens", "docked": True, "side": "right"}


def test_second_screen_returning_leaves_an_undocked_panel_alone():
    docker = _ScreenDocker(docked=False)
    api = PanelApi(_Provider())
    api._docker = docker
    api._attach(panel=_Window(), icon=_Window())
    api._set_screens(1)
    api._set_screens(2)
    assert docker.calls == []


def test_page_follows_layout_changes():
    script = (WEB_DIR / "panel.js").read_text(encoding="utf-8")
    assert 'addEventListener("layout-changed"' in script


class _SideDocker:
    """Stands in for layout.Docker while the overlay is open."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def dock(self, side: str = "right") -> dict:
        self.calls.append(f"dock {side}")
        return {"mode": "overlay", "game_found": True}

    def raise_icon(self, title: str) -> None:
        self.calls.append("raise_icon")


def test_overlay_side_is_the_players_choice_and_is_remembered():
    from chancellor.app.state import load_overlay_side

    api = PanelApi(_Provider())
    assert api.set_overlay_side("left") == {"ok": True, "side": "left"}
    assert api.layout_mode()["side"] == "left"
    assert load_overlay_side() == "left"
    assert api.set_overlay_side("top") == {"ok": False, "error": "Unknown side 'top'."}
    assert api.layout_mode()["side"] == "left"


def test_an_open_overlay_moves_to_the_chosen_side_at_once():
    docker = _SideDocker()
    api = PanelApi(_Provider())
    api._docker = docker
    api._overlay_open = True
    api.set_overlay_side("left")
    assert docker.calls == ["dock left", "raise_icon"]


def test_the_overlay_does_not_follow_the_icon():
    import inspect

    from chancellor.app.ui import PanelApi as Api

    source = inspect.getsource(Api.toggle_overlay)
    assert "docker.dock(side=self._side)" in source
    assert "icon_side" not in source
