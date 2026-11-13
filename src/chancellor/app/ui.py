"""The Chancellor's desktop panel: a pywebview window beside the game (D-021, UI_DESIGN).

The page under ``app/web/`` is plain HTML, CSS and JavaScript. It calls the methods of
:class:`PanelApi` through pywebview's ``js_api`` bridge; each call returns plain JSON
values, so the class is testable without a window. pywebview is an optional dependency
(``pip install -e ".[ui]"``) and is imported only when the window opens.

Build order steps 1-3: the header (country, date, save), alerts and the key numbers,
refreshed
when the game writes a new save (:class:`chancellor.watcher.SaveWatcher` fires a
``save-changed`` event in the page). The chat runs in Claude Desktop; the paid API mode
arrives later and only behind the player's own switch (D-020).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chancellor.app.mcp_server import CampaignProvider
from chancellor.config import Settings
from chancellor.context.alerts import campaign_alerts
from chancellor.context.campaign import Campaign
from chancellor.context.status import campaign_status
from chancellor.game.imperial_reforms import ImperialReformLibrary
from chancellor.watcher import SaveWatcher

WEB_DIR = Path(__file__).parent / "web"
WINDOW_TITLE = "Chancellor"
# Logical pixels; the main screen at 150% scaling is about 1493×933 (UI_DESIGN).
WINDOW_SIZE = (440, 860)
MIN_SIZE = (360, 560)
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

    def chat_mode(self) -> dict[str, Any]:
        """The chat mode in use. Always Claude Desktop until the API tab exists (D-020)."""
        return {"mode": "claude_desktop", "api_available": False}


def run_panel(settings: Settings, load: Callable[[Path], Campaign]) -> None:
    """Open the panel window and block until it is closed.

    Args:
        settings: Save and game folders.
        load: Loads a campaign (with localisation) from a save path.

    Raises:
        ImportError: If pywebview is not installed.
    """
    import webview  # optional dependency: pip install -e ".[ui]"

    api = PanelApi(CampaignProvider(settings, load), game_dir=settings.game_dir)
    window = webview.create_window(
        WINDOW_TITLE,
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
    )
    watcher = (
        SaveWatcher(settings.save_dir, lambda path: window.evaluate_js(save_changed_script(path)))
        if settings.save_dir is not None
        else None
    )
    if watcher is not None:
        window.events.closed += watcher.stop
    webview.start(watcher.start if watcher is not None else None)


def save_changed_script(path: Path) -> str:
    """JavaScript that tells the page a new save is ready (the page then reloads)."""
    detail = json.dumps({"save": path.name})
    return f"window.dispatchEvent(new CustomEvent('save-changed', {{detail: {detail}}}))"
