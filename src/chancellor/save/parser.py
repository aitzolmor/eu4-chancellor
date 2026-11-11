"""Parse Clausewitz-format text (the syntax used by Paradox save and data files).

Grammar summary:

* ``key=value`` and ``key={ ... }`` pairs.
* Bare-value lists such as ``{ 1 2 3 }``.
* Keys may repeat; every occurrence must be preserved.
"""

from __future__ import annotations

from typing import Any

ClausewitzValue = str | int | float | list[Any] | dict[str, Any]


def parse(text: str) -> dict[str, Any]:
    """Parse a Clausewitz document into nested Python structures.

    Repeated keys are collected into a list in the order they appear.

    Args:
        text: Document text, without the ``EU4txt`` magic header.

    Returns:
        A mapping of top-level keys to parsed values.
    """
    raise NotImplementedError
