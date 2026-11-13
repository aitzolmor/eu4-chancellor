"""The Chancellor's desktop panel: a pywebview window beside the game (D-021, UI_DESIGN).

The page under ``app/web/`` is plain HTML, CSS and JavaScript. It calls the methods of
:class:`PanelApi` through pywebview's ``js_api`` bridge; each call returns plain JSON
values, so the class is testable without a window. pywebview is an optional dependency
(``pip install -e ".[ui]"``) and is imported only when the window opens.

Build order steps 1-4: the header (country, date, save), alerts and the key numbers,
refreshed when the game writes a new save (:class:`chancellor.watcher.SaveWatcher` fires
a ``save-changed`` event in the page), and arranging the panel and Claude Desktop around
the game (:mod:`chancellor.app.layout`, D-022): docked on the second screen when there
are two, or behind a floating icon that opens them as an overlay when there is one. The
chat runs in Claude Desktop; the paid API mode arrives later and only behind the
player's own switch (D-020).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chancellor.app.layout import Docker, DockError, enable_dpi_awareness
from chancellor.app.mcp_server import CampaignProvider
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
    ) -> None:
        """Create the API.

        Args:
            provider: Loads the newest save and reloads it when it changes.
            clock: Seconds since the epoch; replaceable in tests.
            game_dir: The game installation, for alerts that need game data (the next
                imperial reform). Without it those alerts are skipped.
        """
        self._provider = provider
        self._clock = clock
        self._game_dir = game_dir
        self._reforms: ImperialReformLibrary | None = None
        self._docker: Docker | None = None
        self._windows: dict[str, Any] = {}
        self._overlay_open = False
        self._quitting = False
        self._stop_icon = threading.Event()

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
        """``two_screens`` (dock buttons) or ``overlay`` (floating icon), for the page."""
        return {"mode": "overlay" if "icon" in self._windows else "two_screens"}

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
                side = docker.icon_side(ICON_TITLE)
                panel.show()
                # A window created hidden is centred by pywebview when first shown, which
                # can land after our move; place it once visible, then once more.
                docker.wait_visible(WINDOW_TITLE)
                docker.dock(side=side)
                time.sleep(0.3)
                docker.dock(side=side)
                docker.raise_icon(ICON_TITLE)
                self._overlay_open = True
        except (DockError, OSError) as exc:
            panel.hide()
            self._overlay_open = False
            return {"ok": False, "error": str(exc)}
        icon = self._windows.get("icon")
        if icon is not None:  # keep the icon in step when the panel closed the overlay
            icon.evaluate_js(f"window.setOpen && window.setOpen({json.dumps(self._overlay_open)})")
        return {"ok": True, "open": self._overlay_open}

    def quit(self) -> dict[str, Any]:
        """Close the app (the floating icon's close button).

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

    def icon_down(self) -> dict[str, Any]:
        """The page saw the button go down on the floating icon: start following."""
        try:
            self._get_docker().begin_drag(ICON_TITLE)
        except (DockError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def icon_up(self) -> dict[str, Any]:
        """The page saw the button go up: end the drag, or open or close on a click."""
        try:
            dragged = self._get_docker().end_drag()
        except (DockError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        if dragged:
            return {"ok": True, "dragged": True, "open": self._overlay_open}
        return self.toggle_overlay()

    def _keep_icon_in_view(self) -> None:
        """Hide the floating icon while the game is not in front (see layout)."""
        try:
            self._get_docker().keep_icon_in_view(
                ICON_TITLE, stop=self._stop_icon, keep_visible=lambda: self._overlay_open
            )
        except (DockError, OSError):
            return

    def _attach(self, **windows: Any) -> None:
        """Give the API the pywebview windows it shows, hides and closes."""
        self._windows.update(windows)

    def _get_docker(self) -> Docker:
        if self._docker is None:
            self._docker = Docker(WINDOW_TITLE)
        return self._docker

    def chat_mode(self) -> dict[str, Any]:
        """The chat mode in use. Always Claude Desktop until the API tab exists (D-020)."""
        return {"mode": "claude_desktop", "api_available": False}


def run_panel(settings: Settings, load: Callable[[Path], Campaign]) -> None:
    """Open the panel and block until the app is closed.

    With two screens the panel opens as a normal window with dock buttons. With one, only
    a floating icon appears over the game; clicking it opens the panel and Claude Desktop
    as an overlay on that side of the screen (D-022).

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
    if one_screen:
        icon = webview.create_window(
            ICON_TITLE,
            url=str(WEB_DIR / "icon.html"),
            js_api=api,
            width=ICON_SIZE,
            height=ICON_SIZE,
            min_size=(ICON_SIZE, ICON_SIZE),  # pywebview's default minimum is 200×100
            resizable=False,
            frameless=True,
            easy_drag=False,  # dragged by PanelApi.icon_down / icon_up instead
            on_top=True,
            transparent=True,
            shadow=False,
            focus=False,  # clicking the icon must not take the focus from the game
            background_color=BACKGROUND,
        )
        api._attach(icon=icon)
        # Closing the panel in overlay mode only puts it away; the icon quits the app.
        panel.events.closing += lambda: _put_away_instead(api)
        if docker is not None:  # the window exists (and can be found) once it has loaded
            icon.events.loaded += lambda: docker.place_icon(ICON_TITLE, ICON_SIZE)

    watcher = (
        SaveWatcher(settings.save_dir, lambda path: panel.evaluate_js(save_changed_script(path)))
        if settings.save_dir is not None
        else None
    )
    if watcher is not None:
        panel.events.closed += watcher.stop

    def started() -> None:
        if watcher is not None:
            watcher.start()
        if one_screen:
            threading.Thread(target=api._keep_icon_in_view, name="icon-view", daemon=True).start()

    webview.start(started)


def _put_away_instead(api: PanelApi) -> bool:
    """``closing`` handler: in overlay mode the panel's close button closes the overlay.

    Returns ``False`` to cancel the close, except while the app is quitting.
    """
    if api._quitting:
        return True
    if api._overlay_open:
        api.toggle_overlay()
    return False


def save_changed_script(path: Path) -> str:
    """JavaScript that tells the page a new save is ready (the page then reloads)."""
    detail = json.dumps({"save": path.name})
    return f"window.dispatchEvent(new CustomEvent('save-changed', {{detail: {detail}}}))"
