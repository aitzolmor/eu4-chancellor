"""The Chancellor's desktop panel: a pywebview window beside the game (D-021, UI_DESIGN).

The page under ``app/web/`` is plain HTML, CSS and JavaScript. It calls the methods of
:class:`PanelApi` through pywebview's ``js_api`` bridge; each call returns plain JSON
values, so the class is testable without a window. pywebview is an optional dependency
(``pip install -e ".[ui]"``) and is imported only when the window opens.

Build order step 1: the header (country, date, save) and the key numbers. The chat runs
in Claude Desktop; the paid API mode arrives later and only behind the player's own
switch (D-020).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chancellor.app.mcp_server import CampaignProvider
from chancellor.config import Settings
from chancellor.context.campaign import Campaign
from chancellor.context.status import campaign_status

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

    def __init__(self, provider: CampaignProvider, clock: Callable[[], float] = time.time):
        """Create the API.

        Args:
            provider: Loads the newest save and reloads it when it changes.
            clock: Seconds since the epoch; replaceable in tests.
        """
        self._provider = provider
        self._clock = clock

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

    api = PanelApi(CampaignProvider(settings, load))
    webview.create_window(
        WINDOW_TITLE,
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
    )
    webview.start()
