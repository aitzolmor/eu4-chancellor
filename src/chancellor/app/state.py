"""Small pieces of the desktop app's state kept between sessions.

Where the floating icon was left, and the side of the screen the overlay opens on.

Stored as JSON next to the game-data cache, not inside it, so ``chancellor
clear-cache`` does not forget them. A missing or unreadable file means "nothing saved":
the app never fails to start because of it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from chancellor.app.layout import IconPlace

_FILE = "state.json"


def state_dir() -> Path:
    """Folder holding the app's state (``CHANCELLOR_STATE_DIR`` overrides it)."""
    override = os.environ.get("CHANCELLOR_STATE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "eu4-chancellor"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "eu4-chancellor"
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "eu4-chancellor"


def load_icon_place() -> IconPlace | None:
    """Where the floating icon was left, if that was saved and is readable."""
    data = _read().get("icon")
    if not isinstance(data, dict):
        return None
    try:
        return IconPlace(
            monitor=str(data["monitor"]),
            primary=bool(data.get("primary", False)),
            x=float(data["x"]),
            y=float(data["y"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_icon_place(place: IconPlace) -> None:
    """Remember where the floating icon is. Failing to write is not an error."""
    _write("icon", {"monitor": place.monitor, "primary": place.primary, "x": place.x, "y": place.y})


def load_overlay_side() -> str | None:
    """The side the player chose for the overlay (``left`` or ``right``), if saved."""
    side = _read().get("overlay_side")
    return side if side in ("left", "right") else None


def save_overlay_side(side: str) -> None:
    """Remember the overlay side. Failing to write is not an error."""
    _write("overlay_side", side)


def _write(key: str, value: Any) -> None:
    data = _read()
    data[key] = value
    folder = state_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f"{_FILE}.tmp"
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(folder / _FILE)
    except OSError:
        return


def _read() -> dict[str, Any]:
    try:
        data = json.loads((state_dir() / _FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
