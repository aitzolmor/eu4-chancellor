"""Turn game script (triggers and effects) into short, readable lines.

Mission conditions and rewards are written in Clausewitz script. Copying them raw into a
prompt wastes tokens on noise (hidden effects, AI weights, highlight rules) and leaves
province ids and tags unreadable. :func:`describe` keeps the meaning and drops the rest:

* tags become ``Name (TAG)``, province ids ``Name (#id)``, areas and regions their
  localised name;
* tooltips are replaced by their localised text;
* ``if`` / ``else`` and ``complex_dynamic_effect`` branches become labelled sub-lists;
* hidden effects, AI weights and highlighting rules are skipped.

The most common triggers are written in words (``Junior partner in a personal union
with this country``, ``Administrative technology 15 or more``), because raw keys read
poorly in checklists. Every other script key is kept as it is: it is precise, and the
LLM reading the output knows it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from chancellor.context.campaign import DYNAMIC_TAG, Campaign
from chancellor.game.localisation import Localisation
from chancellor.game.modifiers import ModifierLibrary, format_effect
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
_TRIGGERED_MODIFIER_EFFECTS = {"add_province_triggered_modifier", "add_triggered_modifier"}
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

# Common triggers described in words. Anything not listed keeps its script key, which is
# precise and known to the LLM; these are the ones players and the model meet most often
# in checklists, where raw keys such as `junior_union_with: ROOT` read poorly.
_YES_NO_PHRASES = {
    "is_at_war": ("At war", "Not at war"),
    "is_free_or_tributary_trigger": ("Independent or a tributary", "Not independent"),
    "is_nomad": ("A nomad horde", "Not a nomad horde"),
    "is_emperor": ("Holy Roman Emperor", "Not the Holy Roman Emperor"),
    "is_elector": ("An elector of the Empire", "Not an elector of the Empire"),
    "is_part_of_hre": ("Inside the Holy Roman Empire", "Outside the Holy Roman Empire"),
    "is_subject": ("A subject", "Not a subject"),
    "is_lesser_in_union": ("Junior partner in a personal union", "Not a junior partner"),
    "is_colonial_nation": ("A colonial nation", "Not a colonial nation"),
    "is_bankrupt": ("Bankrupt", "Not bankrupt"),
    "has_regency": ("Under a regency", "No regency"),
    "is_state": ("A state", "Not a state"),
    "exists": ("Exists", "Does not exist"),
    "ai": ("Run by the AI", "Played by a human"),
}
_VALUE_PHRASES = {
    "adm_tech": "Administrative technology {v} or more",
    "dip_tech": "Diplomatic technology {v} or more",
    "mil_tech": "Military technology {v} or more",
    "num_of_cities": "{v} or more cities",
    "total_development": "Total development {v} or more",
    "stability": "Stability {v} or more",
    "legitimacy": "Legitimacy {v} or more",
    "legitimacy_equivalent": "Legitimacy (or equivalent) {v} or more",
    "prestige": "Prestige {v} or more",
    "army_tradition": "Army tradition {v} or more",
    "is_year": "Year {v} or later",
    "owns": "Owns {v}",
    "owns_core_province": "Owns {v} as a core",
    "controls": "Controls {v}",
    "owns_or_non_sovereign_subject_of": "{v} held by this country or a non-sovereign subject",
    "owned_by": "Owned by {v}",
    "controlled_by": "Controlled by {v}",
    "is_core": "A core of {v}",
    "country_or_non_sovereign_subject_holds": "Held by {v} or its non-sovereign subjects",
    "country_or_subject_holds": "Held by {v} or its subjects",
    "junior_union_with": "Junior partner in a personal union with {v}",
    "senior_union_with": "Senior partner in a personal union over {v}",
    "tag": "Is {v}",
    "exists": "{v} exists",
    "mission_completed": "Mission completed: {v}",
    "has_country_flag": "Has country flag {v}",
    "has_global_flag": "Global flag {v} is set",
    "religion": "Religion: {v}",
    "religion_group": "Religion group: {v}",
    "culture_group": "Culture group: {v}",
    "primary_culture": "Primary culture: {v}",
    "accepted_culture": "Accepts the {v} culture",
    "government": "Government: {v}",
    "has_reform": "Has the government reform {v}",
    "has_dlc": "Has the {v} DLC",
    "crown_land_share": "Crown land {v}% or more",
    "has_estate": "Has the {v} estate",
}
# Values localised by their own key (religions, cultures, governments, reforms).
_LOCALISED_VALUES = {
    "religion",
    "religion_group",
    "culture_group",
    "primary_culture",
    "accepted_culture",
    "government",
    "has_reform",
    "has_estate",
}
_BLOCK_PHRASES = {
    "NOT": "Not",
    "OR": "One of",
    "AND": "All of",
    "num_of_owned_provinces_with": "Owned provinces",
    "num_of_provinces_owned_or_owned_by_non_sovereign_subjects_with": (
        "Provinces held by this country or its non-sovereign subjects"
    ),
}
_SCOPE_WORDS = {"ROOT": "this country (ROOT)", "root": "this country (ROOT)"}


def describe(
    script: dict[str, Any],
    campaign: Campaign,
    max_lines: int = 12,
    modifiers: ModifierLibrary | None = None,
    country: str | None = None,
) -> list[str]:
    """Describe a trigger or effect block as indented Markdown list lines.

    Args:
        script: Parsed trigger or effect.
        campaign: Supplies names (localisation and save).
        max_lines: Truncate after this many lines; a final ``…`` line marks the cut.
        modifiers: Modifier definitions; when given, granted modifiers list their bonuses.
        country: The country the script is read for. Missions that belong to another
            country are then named with their owner, since titles repeat across
            countries ("Imperio multicultural" is both Austrian and Hungarian).

    Returns:
        Lines such as ``"- owns_core_province: Praga (#266)"`` (two spaces per level).
    """
    lines = _block(script, _Ctx(campaign, modifiers, country), 0)
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], "- …"]
    return lines


def clean_text(text: str, campaign: Campaign | _Ctx) -> str:
    """Strip colour codes and resolve ``[TAG.GetName]`` in localised text."""
    text = _GET_NAME.sub(lambda m: campaign.name(m.group(1)), text)
    text = _OTHER_PLACEHOLDERS.sub("", text)
    text = _FORMATTING.sub("", text).replace("§!", "")
    text = text.replace("\\n", " ").replace("\n", " ")
    return " ".join(text.split())


# --- internals -------------------------------------------------------------------------


@dataclass
class _Ctx:
    """What the describers need: names from the campaign and modifier definitions."""

    campaign: Campaign
    modifiers: ModifierLibrary | None
    country: str | None = None

    @property
    def loc(self) -> Localisation:
        return self.campaign.loc

    def name(self, tag: str) -> str:
        return self.campaign.name(tag)

    def label(self, tag: str) -> str:
        return self.campaign.label(tag)


def _block(script: dict[str, Any], campaign: _Ctx, depth: int) -> list[str]:
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


def _entry(key: str, value: Any, campaign: _Ctx, depth: int) -> list[str]:
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
    if key in _TRIGGERED_MODIFIER_EFFECTS and isinstance(value, str):
        return [f"{pad}- {key}: {_modifier({'name': value}, campaign)}"]
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
    phrase = _phrase(key, value, campaign)
    if phrase:
        return [f"{pad}- {phrase}"]
    return [f"{pad}- {_key(key, campaign)}: {_value(key, value, campaign)}"]


def _phrase(key: str, value: Any, campaign: _Ctx) -> str | None:
    """A common trigger in words, e.g. ``Junior partner in a personal union with ...``."""
    if isinstance(value, bool) and key in _YES_NO_PHRASES:
        yes, no = _YES_NO_PHRASES[key]
        return yes if value else no
    template = _VALUE_PHRASES.get(key)
    if template is None or isinstance(value, bool):
        return None
    if key == "mission_completed" and isinstance(value, str):
        title = campaign.loc.get(f"{value}_title", "")
        shown = clean_text(title, campaign) if title else value
        owner = _mission_owner(value, campaign)
        if owner:
            shown += f" (a mission of {campaign.label(owner)}, `{value}`)"
    elif key in _LOCALISED_VALUES and isinstance(value, str):
        shown = campaign.loc.get(value, value.replace("_", " "))
    else:
        shown = _value(key, value, campaign)
    return template.format(v=shown)


def _mission_owner(mission: str, campaign: _Ctx) -> str | None:
    """The country a mission belongs to, when it is not the one being read for.

    Country missions are keyed by the lower-case tag (``hun_a_multicultural_empire``).
    Only prefixes that are a country in the save count, so generic missions stay
    unnamed, and nothing is said without a ``country`` to compare with.
    """
    if campaign.country is None:
        return None
    prefix = mission.split("_", 1)[0].upper()
    if len(prefix) != 3 or prefix == campaign.country.upper():
        return None
    return prefix if prefix in campaign.campaign.country_blocks else None


def _branch(parts: dict[str, Any], campaign: _Ctx, depth: int) -> list[str]:
    pad = "  " * depth
    tooltip = parts.get("custom_tooltip")
    if isinstance(tooltip, str):
        title = _localised(tooltip, campaign).rstrip(":")
    else:
        title = f"If {_inline(_as_script(parts.get('limit')), campaign)}"
    effect = _as_script(parts.get("effect"))
    return [f"{pad}- {title}:", *_block(effect, campaign, depth + 1)]


def _modifier(block: dict[str, Any], campaign: _Ctx) -> str:
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
    text = f"{shown} ({details})" if details else shown
    effects = campaign.modifiers.effects(name) if campaign.modifiers else []
    if effects:
        text += ": " + ", ".join(format_effect(s, v, campaign.loc) for s, v in effects)
    return text


def _inline(limit: Any, campaign: _Ctx) -> str:
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


def _key(key: str, campaign: _Ctx) -> str:
    if key in _BLOCK_PHRASES:
        return _BLOCK_PHRASES[key]
    if _is_tag(key):
        return campaign.label(key)
    if key.lstrip("-").isdigit():
        return _province(key, campaign)
    if _GEOGRAPHY.search(key):
        return campaign.loc.get(key, key)
    return key


def _value(key: str, value: Any, campaign: _Ctx) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, int) and key in _PROVINCE_KEYS:
        return _province(value, campaign)
    if isinstance(value, str):
        if value in _SCOPE_WORDS:
            return _SCOPE_WORDS[value]
        if _is_tag(value):
            return campaign.label(value)
        if key in _PROVINCE_SCOPED or _GEOGRAPHY.search(value):
            return campaign.loc.get(value, value)
    return str(value)


def _province(province_id: int | str, campaign: _Ctx) -> str:
    number = str(province_id).lstrip("-")
    return f"{campaign.loc.province(number)} (#{number})"


def _localised(key: str, campaign: _Ctx) -> str:
    text = campaign.loc.get(key, "")
    return clean_text(text, campaign) if text else key.replace("_", " ")


def _is_tag(text: str) -> bool:
    return bool(_TAG.match(text) or DYNAMIC_TAG.match(text)) and text not in {"AND", "NOT"}
