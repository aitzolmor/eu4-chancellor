"""Query functions exposed to the LLM as tools (Phase 3).

Each function takes the parsed gamestate plus simple arguments and returns a small,
JSON-serialisable dict, so the model can decide what to look up on its own.
"""

from __future__ import annotations

from typing import Any


def get_country(save: dict[str, Any], tag: str) -> dict[str, Any]:
    """Return key statistics for a country (economy, military, diplomacy)."""
    raise NotImplementedError


def get_province(save: dict[str, Any], province_id: int) -> dict[str, Any]:
    """Return owner, development, buildings and modifiers of a province."""
    raise NotImplementedError


def get_war(save: dict[str, Any], name: str) -> dict[str, Any]:
    """Return participants, war goal and war score of an active war."""
    raise NotImplementedError


def compare_armies(save: dict[str, Any], tag_a: str, tag_b: str) -> dict[str, Any]:
    """Compare land and naval strength of two countries, including allies."""
    raise NotImplementedError
