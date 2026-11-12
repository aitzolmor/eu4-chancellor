"""Turn game script (triggers and effects) into short, readable lines.

Mission conditions and rewards are written in Clausewitz script. Copying them raw into a
prompt wastes tokens on noise (hidden effects, AI weights, highlight rules) and leaves
province ids and tags unreadable. :func:`describe` keeps the meaning and drops the rest:

* tags become ``Name (TAG)``, province ids ``Name (#id)``, areas and regions their
  localised name;
* tooltips are replaced by their localised text;
* ``if`` / ``else`` and ``complex_dynamic_effect`` branches become labelled sub-lists;
* hidden effects, AI weights and highlighting rules are skipped.

The output keeps script keys such as ``owns_core_province`` as they are: they are
precise, and the LLM reading the briefing knows them.
"""

from __future__ import annotations

import re
from typing import Any

from chancellor.context.campaign import DYNAMIC_TAG, Campaign
from chancellor.save.parser import Repeated, parse

_SKIPPED_KEYS = {
    "hidden_effect",
    "ai_weight",
    "provinces_to_highlight",
    "not_in_mission_preview_mode",
    "potential_on_load",
    "hidden_trigger",
}
_SEPARATORS = {"SEPERATOR_TOOLTIP", "SEPARATOR_TOOLTIP"}
_TAG = re.compile(r"^[A-Z]{3}$")
_GEOGRAPHY = re.compile(r"_(area|region|superregion|continent)$")
_FORMATTING = re.compile(r"§.|£\w+£?")
_GET_NAME = re.compile(r"\[(\w{3})\.Get\w*Name\w*\]")
_OTHER_PLACEHOLDERS = re.compile(r"\[[^\]]*\]")
_MODIFIER_EFFECTS = {
    "add_country_modifier",
    "add_province_modifier",
    "add_permanent_province_modifier",
    "add_ruler_modifier",
    "add_trade_modifier",
}
_BRANCH = re.compile(r"^(first|second|third|fourth|fifth)_(custom_tooltip|limit|effect)$")
_PROVINCE_KEYS = {
    "owns",
    "owns_core_province",
    "owns_or_non_sovereign_subject_of",
    "owns_or_subject_of",
    "controls",
    "province_id",
    "capital",
    "add_core",
    "add_claim",
    "add_permanent_claim",
}
_PROVINCE_SCOPED = {"area", "region", "superregion", "province_id"}


def describe(script: dict[str, Any], campaign: Campaign, max_lines: int = 12) -> list[str]:
    """Describe a trigger or effect block as indented Markdown list lines.

    Args:
        script: Parsed trigger or effect.
        campaign: Supplies names (localisation and save).
        max_lines: Truncate after this many lines; a final ``…`` line marks the cut.

    Returns:
        Lines such as ``"- owns_core_province: Praga (#266)"`` (two spaces per level).
    """
    lines = _block(script, campaign, 0)
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], "- …"]
    return lines


def clean_text(text: str, campaign: Campaign) -> str:
    """Strip colour codes and resolve ``[TAG.GetName]`` in localised text."""
    text = _GET_NAME.sub(lambda m: campaign.name(m.group(1)), text)
    text = _OTHER_PLACEHOLDERS.sub("", text)
    text = _FORMATTING.sub("", text).replace("§!", "")
    text = text.replace("\\n", " ").replace("\n", " ")
    return " ".join(text.split())


# --- internals -------------------------------------------------------------------------


def _block(script: dict[str, Any], campaign: Campaign, depth: int) -> list[str]:
    lines: list[str] = []
    branches: dict[str, dict[str, Any]] = {}
    for key, value in script.items():
        if key in _SKIPPED_KEYS:
            continue
        values = list(value) if isinstance(value, Repeated) else [value]
        for item in values:
            match = _BRANCH.match(key)
            if match:  # complex_dynamic_effect = { first_limit=... first_effect=... }
                branches.setdefault(match.group(1), {})[match.group(2)] = item
                continue
            lines.extend(_entry(key, item, campaign, depth))
    for parts in branches.values():
        lines.extend(_branch(parts, campaign, depth))
    return lines


def _entry(key: str, value: Any, campaign: Campaign, depth: int) -> list[str]:
    pad = "  " * depth
    if key == "custom_tooltip":
        if isinstance(value, str) and value not in _SEPARATORS:
            return [f"{pad}- {_localised(value, campaign)}"]
        return []
    if key == "custom_trigger_tooltip" and isinstance(value, dict):
        tooltip = value.get("tooltip")
        if isinstance(tooltip, str):
            return [f"{pad}- {_localised(tooltip, campaign)}"]
        return _block({k: v for k, v in value.items() if k != "tooltip"}, campaign, depth)
    if key == "tooltip" and isinstance(value, dict):
        return _block(value, campaign, depth)
    if key in ("if", "else_if") and isinstance(value, dict):
        condition = _inline(value.get("limit"), campaign)
        body = {k: v for k, v in value.items() if k != "limit"}
        label = "If" if key == "if" else "Else if"
        return [f"{pad}- {label} {condition}:", *_block(body, campaign, depth + 1)]
    if key == "else" and isinstance(value, dict):
        return [f"{pad}- Otherwise:", *_block(value, campaign, depth + 1)]
    if key in _MODIFIER_EFFECTS and isinstance(value, dict) and "name" in value:
        return [f"{pad}- {key}: {_modifier(value, campaign)}"]
    if key == "complex_dynamic_effect" and isinstance(value, dict):
        return _block(value, campaign, depth)
    if isinstance(value, str) and _looks_like_script(value):
        return _block(parse(value), campaign, depth)
    if isinstance(value, dict):
        children = _block(value, campaign, depth + 1)
        if not children:
            return [f"{pad}- {_key(key, campaign)}"]
        if len(children) == 1 and len(children[0]) < 70:  # keep short scopes on one line
            return [f"{pad}- {_key(key, campaign)}: {children[0].strip()[2:]}"]
        return [f"{pad}- {_key(key, campaign)}:", *children]
    if isinstance(value, list):
        shown = ", ".join(_value(key, v, campaign) for v in value)
        return [f"{pad}- {_key(key, campaign)}: {shown}"]
    return [f"{pad}- {_key(key, campaign)}: {_value(key, value, campaign)}"]


def _branch(parts: dict[str, Any], campaign: Campaign, depth: int) -> list[str]:
    pad = "  " * depth
    tooltip = parts.get("custom_tooltip")
    if isinstance(tooltip, str):
        title = _localised(tooltip, campaign).rstrip(":")
    else:
        title = f"If {_inline(_as_script(parts.get('limit')), campaign)}"
    effect = _as_script(parts.get("effect"))
    return [f"{pad}- {title}:", *_block(effect, campaign, depth + 1)]


def _modifier(block: dict[str, Any], campaign: Campaign) -> str:
    """``Corona de Bohemia (hab_union_with_bohemia, 15 years)``."""
    name = str(block["name"])
    title = clean_text(campaign.loc.get(name, ""), campaign)
    duration = block.get("duration")
    if isinstance(duration, int) and duration > 0:
        years = duration / 365
        span = f"{years:g} years" if years >= 1 else f"{duration} days"
    elif duration == -1:
        span = "permanent"
    else:
        span = ""
    details = ", ".join(filter(None, [name if title else "", span]))
    shown = title or name
    return f"{shown} ({details})" if details else shown


def _inline(limit: Any, campaign: Campaign) -> str:
    """A condition on one line, e.g. ``(senior_union_with: Bohemia (BOH))``."""
    if not isinstance(limit, dict):
        return "(condition)"
    parts = [line.strip()[2:] for line in _block(limit, campaign, 0)]
    return "(" + "; ".join(parts) + ")" if parts else "(condition)"


def _as_script(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and _looks_like_script(value):
        return parse(value)
    return {}


def _looks_like_script(text: str) -> bool:
    return "=" in text and ("\n" in text or "{" in text)


def _key(key: str, campaign: Campaign) -> str:
    if _is_tag(key):
        return campaign.label(key)
    if key.lstrip("-").isdigit():
        return _province(key, campaign)
    if _GEOGRAPHY.search(key):
        return campaign.loc.get(key, key)
    return key


def _value(key: str, value: Any, campaign: Campaign) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, int) and key in _PROVINCE_KEYS:
        return _province(value, campaign)
    if isinstance(value, str):
        if _is_tag(value):
            return campaign.label(value)
        if key in _PROVINCE_SCOPED or _GEOGRAPHY.search(value):
            return campaign.loc.get(value, value)
    return str(value)


def _province(province_id: int | str, campaign: Campaign) -> str:
    number = str(province_id).lstrip("-")
    return f"{campaign.loc.province(number)} (#{number})"


def _localised(key: str, campaign: Campaign) -> str:
    text = campaign.loc.get(key, "")
    return clean_text(text, campaign) if text else key.replace("_", " ")


def _is_tag(text: str) -> bool:
    return bool(_TAG.match(text) or DYNAMIC_TAG.match(text)) and text not in {"AND", "NOT"}
