"""Always-on-top chat window shown next to the game (Phase 2)."""

from __future__ import annotations

from chancellor.config import Settings


def run_chat_window(settings: Settings) -> None:
    """Open the chat window and block until it is closed.

    The window stays on top of the game, toggles with a global hotkey, and shows
    which save (file and in-game date) the current answers are based on.

    Args:
        settings: Resolved settings.
    """
    raise NotImplementedError
