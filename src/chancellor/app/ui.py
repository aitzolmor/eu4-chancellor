"""The Chancellor's desktop panel: a pywebview window beside the game (D-021, UI_DESIGN).

The page under ``app/web/`` is plain HTML, CSS and JavaScript. It calls the methods of
:class:`PanelApi` through pywebview's ``js_api`` bridge; each call returns plain JSON
values, so the class is testable without a window. pywebview is an optional dependency
(``pip install -e ".[ui]"``) and is imported only when the window opens.

Build order steps 1-6: the header (country, date, save), alerts and the key numbers,
refreshed when the game writes a new save (:class:`chancellor.watcher.SaveWatcher` fires
a ``save-changed`` event in the page), and arranging the panel and Claude Desktop around
the game (:mod:`chancellor.app.layout`, D-022): docked on the second screen when there
are two, or behind a floating icon that opens them as an overlay when there is one.
Quick questions copy a ready-made prompt and bring Claude Desktop to the front, and a
system-wide shortcut (:mod:`chancellor.app.hotkey`) opens the overlay or Claude Desktop
from inside the game. The app follows a second screen appearing or dropping while it
runs (a Miracast link, for instance) and remembers where the icon was left
(:mod:`chancellor.app.state`). By default the chat runs in Claude Desktop; the paid API
chat (:mod:`chancellor.app.api_chat`) is a mode the player switches on for the session,
within a budget (D-020, D-028).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chancellor.app.api_chat import ApiChat
from chancellor.app.clipboard import ClipboardError, copy_to_clipboard
from chancellor.app.hotkey import DEFAULT_HOTKEY, GlobalHotkey, HotkeyError, describe_hotkey
from chancellor.app.icon_window import FloatingIcon
from chancellor.app.layout import Docker, DockError, enable_dpi_awareness
from chancellor.app.mcp_server import CampaignProvider
from chancellor.app.quick_questions import QUICK_QUESTIONS, find_question
from chancellor.app.state import (
    load_icon_place,
    load_overlay_side,
    save_icon_place,
    save_overlay_side,
)
from chancellor.config import Settings
from chancellor.context.alerts import campaign_alerts
from chancellor.context.campaign import Campaign
from chancellor.context.status import campaign_status
from chancellor.game.imperial_reforms import ImperialReformLibrary
from chancellor.watcher import SaveWatcher

WEB_DIR = Path(__file__).parent / "web"
WINDOW_TITLE = "Chancellor"
ICON_TITLE = "Chancellor icon"
# Logical pixels; the main screen at 150% scaling is about 1493×933 (UI_DESIGN).
WINDOW_SIZE = (440, 860)
MIN_SIZE = (320, 300)  # small enough for the overlay's top 40% on a 1400 px screen
ICON_SIZE = 64
SIDES = ("left", "right")  # where the overlay can open on one screen
SCREEN_CHECK_SECONDS = 2.0  # how often the app looks for screens appearing or dropping
BACKGROUND = "#0f1726"  # matches the page, so the window does not flash white


class PanelApi:
    """What the page can ask for. Public methods are exposed to JavaScript.

    Attributes are private on purpose: pywebview exposes public attributes to the page
    too, and the provider is not meant to be reachable from JavaScript.
    """

    def __init__(
        self,
        provider: CampaignProvider,
        clock: Callable[[], float] = time.time,
        game_dir: Path | None = None,
        copy: Callable[[str], None] = copy_to_clipboard,
    ) -> None:
        """Create the API.

        Args:
            provider: Loads the newest save and reloads it when it changes.
            clock: Seconds since the epoch; replaceable in tests.
            game_dir: The game installation, for alerts that need game data (the next
                imperial reform). Without it those alerts are skipped.
            copy: Puts text on the clipboard; replaceable in tests.
        """
        self._provider = provider
        self._clock = clock
        self._copy = copy
        self._hotkey: GlobalHotkey | None = None
        self._game_dir = game_dir
        self._reforms: ImperialReformLibrary | None = None
        self._docker: Docker | None = None
        self._windows: dict[str, Any] = {}
        self._overlay_open = False
        self._mode = "two_screens"  # or "overlay" (one screen, behind the floating icon)
        self._side = "right"  # the overlay side the player chose (set_overlay_side)
        self._redock = False  # docked when the second screen dropped: dock again on return
        self._quitting = False
        self._stop_icon = threading.Event()
        self._chat: ApiChat | None = None  # the paid API chat, when settings allow it

    def status(self) -> dict[str, Any]:
        """The current campaign's key facts, or an error message for the page.

        Returns:
            ``{"ok": True, "status": {...}, "read_at": <epoch seconds>}`` or
            ``{"ok": False, "error": "<message>"}``.
        """
        try:
            campaign = self._provider.toolbox().campaign
            status = campaign_status(campaign, self._provider.save_path)
        except (RuntimeError, OSError, KeyError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}
        return {"ok": True, "status": status.to_dict(), "read_at": self._clock()}

    def alerts(self) -> dict[str, Any]:
        """What needs attention, most severe first. Slower than :meth:`status` (~1 s).

        Returns:
            ``{"ok": True, "alerts": [{"kind", "severity", "text"}, ...]}`` or
            ``{"ok": False, "error": "<message>"}``.
        """
        try:
            campaign = self._provider.toolbox().campaign
            alerts = campaign_alerts(campaign, reforms=self._imperial_reforms())
        except (RuntimeError, OSError, KeyError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}
        return {"ok": True, "alerts": [alert.to_dict() for alert in alerts]}

    def _imperial_reforms(self) -> ImperialReformLibrary | None:
        if self._reforms is None and self._game_dir is not None:
            self._reforms = ImperialReformLibrary.load(self._game_dir)
        return self._reforms

    def layout_mode(self) -> dict[str, Any]:
        """``two_screens`` (dock buttons) or ``overlay`` (floating icon), for the page.

        ``docked`` says whether the windows are docked on the second screen now (after
        the screen returns, the app docks again by itself).
        """
        docked = self._mode == "two_screens" and self._docker is not None and self._docker.docked
        return {"mode": self._mode, "docked": docked, "side": self._side}

    def dock(self) -> dict[str, Any]:
        """Dock the panel and Claude Desktop on the second screen.

        Returns:
            ``{"ok": True, "mode": "two_screens" | "overlay", "game_found": bool}`` or
            ``{"ok": False, "error": "<message>"}``.
        """
        try:
            return {"ok": True, **self._get_docker().dock()}
        except (DockError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def undock(self) -> dict[str, Any]:
        """Put the docked windows back where they were."""
        if self._docker is not None:
            self._docker.undock()
        return {"ok": True}

    def toggle_overlay(self) -> dict[str, Any]:
        """Open or close the overlay (one screen). Called by the floating icon.

        Returns:
            ``{"ok": True, "open": bool}`` or ``{"ok": False, "error": "<message>"}``.
        """
        panel = self._windows.get("panel")
        if panel is None:
            return {"ok": False, "error": "The panel window is not ready yet."}
        try:
            docker = self._get_docker()
            if self._overlay_open:
                panel.hide()
                docker.put_away()
                self._overlay_open = False
            else:
                panel.show()
                # A window created hidden is centred by pywebview when first shown, which
                # can land after our move; place it once visible, then once more.
                docker.wait_visible(WINDOW_TITLE)
                docker.dock(side=self._side)
                time.sleep(0.3)
                docker.dock(side=self._side)
                docker.raise_icon(ICON_TITLE)
                self._overlay_open = True
        except (DockError, OSError) as exc:
            panel.hide()
            self._overlay_open = False
            return {"ok": False, "error": str(exc)}
        icon = self._windows.get("icon")
        if icon is not None:  # keep the icon in step when the panel closed the overlay
            icon.set_open(self._overlay_open)
        return {"ok": True, "open": self._overlay_open}

    def set_overlay_side(self, side: str) -> dict[str, Any]:
        """Choose the side of the screen the overlay opens on, and remember it.

        The player picks it to keep the part of the game's interface they need in view;
        it does not follow the floating icon, which is moved out of the way instead. An
        open overlay moves at once.

        Returns:
            ``{"ok": True, "side": side}`` or ``{"ok": False, "error": "<message>"}``.
        """
        if side not in SIDES:
            return {"ok": False, "error": f"Unknown side '{side}'."}
        self._side = side
        save_overlay_side(side)
        if self._overlay_open:
            try:
                docker = self._get_docker()
                docker.dock(side=side)
                docker.raise_icon(ICON_TITLE)
            except (DockError, OSError) as exc:
                return {"ok": False, "error": str(exc)}
        return {"ok": True, "side": side}

    def quit(self) -> dict[str, Any]:
        """Close the app (the floating icon's "Close Chancellor" menu).

        The windows are destroyed on another thread: destroying the icon from inside its
        own pending call would wait on itself.
        """
        self._quitting = True
        self._stop_icon.set()
        threading.Thread(target=self._shut_down, name="quit", daemon=True).start()
        return {"ok": True}

    def _shut_down(self) -> None:
        time.sleep(0.05)  # let the page receive this call's answer first
        if self._docker is not None and self._docker.docked:
            self._docker.undock()
        for window in list(self._windows.values()):
            window.destroy()

    def _keep_icon_in_view(self) -> None:
        """Hide the floating icon while the game is not in front, or on two screens."""
        try:
            self._get_docker().keep_icon_in_view(
                ICON_TITLE,
                stop=self._stop_icon,
                keep_visible=lambda: self._overlay_open,
                allowed=lambda: self._mode == "overlay",
            )
        except (DockError, OSError):
            return

    def _set_screens(self, count: int) -> None:
        """Switch between docking (two screens or more) and the overlay (one screen).

        Called whenever the number of screens changes. When the second screen drops,
        docked windows go back where they were, the panel hides and the floating icon
        takes over; when it returns, the overlay closes, the panel shows again and, if
        it was docked before, docks again.
        """
        mode = "overlay" if count == 1 else "two_screens"
        if mode == self._mode:
            return
        panel = self._windows.get("panel")
        docker = self._docker
        if mode == "overlay":
            self._redock = docker is not None and docker.docked
            if docker is not None and docker.docked:
                docker.undock()
            if panel is not None:
                panel.hide()
            self._overlay_open = False
            icon = self._windows.get("icon")
            if icon is not None:
                icon.set_open(False)
            self._mode = mode
        else:
            if self._overlay_open:
                self.toggle_overlay()
            self._mode = mode
            if panel is not None:
                panel.show()
            if self._redock:
                self._redock = False
                self.dock()
        if panel is not None:
            panel.evaluate_js(LAYOUT_CHANGED_SCRIPT)

    def _watch_screens(self, interval: float = SCREEN_CHECK_SECONDS) -> None:
        """Follow screens appearing or dropping until the app quits."""
        docker = self._docker
        if docker is None:
            return
        while not self._stop_icon.wait(interval):
            try:
                count = docker.screens()
            except OSError:
                continue
            if count:
                self._set_screens(count)

    def _icon_moved(self) -> None:
        """Remember where the player left the icon, for the next session."""
        try:
            place = self._get_docker().icon_place(ICON_TITLE)
        except (DockError, OSError):
            return
        if place is not None:
            save_icon_place(place)

    def _attach(self, **windows: Any) -> None:
        """Give the API the pywebview windows it shows, hides and closes."""
        self._windows.update(windows)

    def _get_docker(self) -> Docker:
        if self._docker is None:
            self._docker = Docker(WINDOW_TITLE)
        return self._docker

    def quick_questions(self) -> dict[str, Any]:
        """The ready-made questions, for the panel's buttons."""
        return {"questions": [q.to_dict() for q in QUICK_QUESTIONS]}

    def ask(self, question_id: str) -> dict[str, Any]:
        """Copy a quick question and bring Claude Desktop to the front to paste it.

        In overlay mode the overlay is opened first, so Claude Desktop is on screen.

        Returns:
            ``{"ok": True, "focused": bool, "error"?: str}`` (copied; ``focused`` says
            whether Claude Desktop came forward) or ``{"ok": False, "error": str}``.
        """
        question = find_question(question_id)
        if question is None:
            return {"ok": False, "error": f"Unknown question '{question_id}'."}
        try:
            self._copy(question.prompt)
        except ClipboardError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            if self._mode == "overlay" and not self._overlay_open:
                opened = self.toggle_overlay()
                if not opened.get("ok"):
                    return {"ok": True, "focused": False, "error": opened.get("error")}
            self._get_docker().focus_chat()
        except (DockError, OSError) as exc:
            return {"ok": True, "focused": False, "error": str(exc)}
        return {"ok": True, "focused": True}

    def hotkey(self) -> dict[str, Any]:
        """The system-wide shortcut, if it could be registered, for the page."""
        if self._hotkey is None or not self._hotkey.registered:
            return {"registered": False}
        return {"registered": True, "keys": describe_hotkey(self._hotkey.text)}

    def _on_hotkey(self) -> None:
        """The shortcut: toggle the overlay (one screen) or bring Claude Desktop forward."""
        if self._mode == "overlay":
            self.toggle_overlay()
            return
        try:
            self._get_docker().focus_chat()
        except (DockError, OSError):
            return

    def chat_mode(self) -> dict[str, Any]:
        """The chat mode in use and the API budget, for the menu and the header badge.

        Claude Desktop unless the player switched the API chat on this session (D-020).
        """
        if self._chat is None:
            return {"mode": "claude_desktop", "api_available": False, "reason": "Not set up."}
        return self._chat.state()

    def set_chat_mode(self, mode: str) -> dict[str, Any]:
        """Switch the chat between ``claude_desktop`` and ``api`` (the page confirms first)."""
        if self._chat is None:
            return {"ok": False, "error": "The API chat is not set up."}
        return self._chat.set_mode(mode)

    def ask_api(self, question: str) -> dict[str, Any]:
        """Ask the paid API chat; the answer streams to the page as ``chat-*`` events."""
        if self._chat is None:
            return {"ok": False, "error": "The API chat is not set up."}
        return self._chat.ask(question, self._emit)

    def _emit(self, name: str, detail: dict[str, Any]) -> None:
        """Send an event to the page (from any thread)."""
        panel = self._windows.get("panel")
        if panel is not None:
            panel.evaluate_js(event_script(name, detail))


def run_panel(settings: Settings, load: Callable[[Path], Campaign]) -> None:
    """Open the panel and block until the app is closed.

    With two screens the panel opens as a normal window with dock buttons. With one, only
    a floating icon appears over the game; clicking it opens the panel and Claude Desktop
    as an overlay on that side of the screen (D-022). The icon exists in both cases and
    is only shown with one screen, so the app can switch while it runs.

    Args:
        settings: Save and game folders.
        load: Loads a campaign (with localisation) from a save path.

    Raises:
        ImportError: If pywebview is not installed.
    """
    import webview  # optional dependency: pip install -e ".[ui]"

    enable_dpi_awareness()  # before any window exists, so docking uses real pixels

    try:
        docker: Docker | None = Docker(WINDOW_TITLE)
        one_screen = docker.screens() == 1
    except DockError:
        docker, one_screen = None, False

    api = PanelApi(CampaignProvider(settings, load), game_dir=settings.game_dir)
    api._docker = docker
    api._mode = "overlay" if one_screen else "two_screens"
    api._side = load_overlay_side() or "right"
    api._chat = ApiChat(settings, api._provider.toolbox)
    panel = webview.create_window(
        WINDOW_TITLE,
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
        hidden=one_screen,
    )
    api._attach(panel=panel)
    if docker is not None:
        icon = FloatingIcon(
            ICON_TITLE,
            docker.icon_home(ICON_SIZE, load_icon_place()),
            on_click=api.toggle_overlay,
            on_quit=api.quit,
            on_moved=api._icon_moved,
        )
        api._attach(icon=icon)
    panel.events.closing += lambda: _on_closing(api)

    watcher = (
        SaveWatcher(settings.save_dir, lambda path: panel.evaluate_js(save_changed_script(path)))
        if settings.save_dir is not None
        else None
    )
    if watcher is not None:
        panel.events.closed += watcher.stop

    try:
        api._hotkey = GlobalHotkey(settings.hotkey or DEFAULT_HOTKEY, api._on_hotkey)
    except HotkeyError:
        api._hotkey = None
    if api._hotkey is not None:
        panel.events.closed += api._hotkey.stop

    def started() -> None:
        if api._hotkey is not None:
            api._hotkey.start()
        if watcher is not None:
            watcher.start()
        if "icon" in api._windows:
            api._windows["icon"].start(show=one_screen)
            threading.Thread(target=api._keep_icon_in_view, name="icon-view", daemon=True).start()
            threading.Thread(target=api._watch_screens, name="screens", daemon=True).start()

    webview.start(started)


def _on_closing(api: PanelApi) -> bool:
    """``closing`` handler for the panel's close button.

    In overlay mode it only closes the overlay (the icon's menu quits the app). On two
    screens it quits: the hidden icon and the threads stop, docked windows go back.

    Returns ``False`` to cancel the close.
    """
    if api._quitting:
        return True
    if api._mode == "overlay":
        if api._overlay_open:
            api.toggle_overlay()
        return False
    api._quitting = True
    api._stop_icon.set()
    icon = api._windows.get("icon")
    if icon is not None:
        icon.destroy()
    if api._docker is not None and api._docker.docked:
        api._docker.undock()
    return True


LAYOUT_CHANGED_SCRIPT = "window.dispatchEvent(new CustomEvent('layout-changed'))"


def event_script(name: str, detail: dict[str, Any]) -> str:
    """JavaScript that fires a ``CustomEvent`` with a JSON ``detail`` in the page."""
    return (
        f"window.dispatchEvent(new CustomEvent({json.dumps(name)}, "
        f"{{detail: {json.dumps(detail)}}}))"
    )


def save_changed_script(path: Path) -> str:
    """JavaScript that tells the page a new save is ready (the page then reloads)."""
    detail = json.dumps({"save": path.name})
    return f"window.dispatchEvent(new CustomEvent('save-changed', {{detail: {detail}}}))"
