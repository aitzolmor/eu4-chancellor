"""Build a compact, LLM-friendly briefing of the player's situation (Phase 1)."""

from __future__ import annotations

from typing import Any


def summarize(save: dict[str, Any], player_tag: str) -> str:
    """Produce a briefing of the player's country and its surroundings.

    Covers economy, military, stability and legitimacy, active wars, allies, rivals,
    subjects and neighbours with their relative strength.

    Args:
        save: Parsed gamestate.
        player_tag: The player's country tag, e.g. ``"CAS"``.

    Returns:
        Plain-text briefing, a few hundred lines at most.
    """
    raise NotImplementedError
