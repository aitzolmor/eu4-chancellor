"""The query functions, exposed to the chat agent as tools (D-009).

Every CLI command has a tool here that calls the same code and returns the same Markdown,
so what the player sees with ``chancellor war-check`` is exactly what the assistant reads.
The tool list is static and ordered, which keeps the request prefix stable for prompt
caching.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from chancellor.context.campaign import Campaign, CountryLookupError
from chancellor.context.decisions import check_decisions, render_decisions
from chancellor.context.missions import mission_tree, render_missions
from chancellor.context.summarizer import summarize
from chancellor.context.targets import find_targets, render_targets
from chancellor.context.war_check import check_war, render_war_check
from chancellor.context.world import render_world, world_overview
from chancellor.game.decisions import DecisionLibrary
from chancellor.game.missions import MissionLibrary
from chancellor.game.modifiers import ModifierLibrary
from chancellor.game.rules import GameRules


class ToolInputError(ValueError):
    """The model called a tool with arguments that do not match its schema."""


_COUNTRY = {
    "type": "string",
    "description": "Country tag (e.g. 'BUR') or name in the game's language (e.g. 'Borgoña').",
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_country_briefing",
        "description": (
            "Briefing of one country from the current save: ruler, stability, economy, "
            "military, territory and overextension, technology, ideas and monarch power, "
            "estates, diplomacy, aggressive expansion held against it (who is near or in a "
            "coalition), its place in the Holy Roman Empire, wars and the countries around "
            "it. For any country other than the player's it also shows "
            "the relation to the player and a strength comparison. Omit `country` for the "
            "player's own country."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"country": _COUNTRY},
            "additionalProperties": False,
        },
    },
    {
        "name": "check_war",
        "description": (
            "Who would fight if `attacker` (default: the player) declared war on `target` "
            "today: the target's allies, subjects, overlord, guarantors, the Holy Roman "
            "Emperor and coalitions, the attacker's allies and subjects, each marked "
            "certain/likely/possible, with regiments and manpower per side, and any truce "
            "(declaring war would break it; end date estimated) and any ally of the attacker "
            "bound to defend the target. Ignores casus belli."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"target": _COUNTRY, "attacker": _COUNTRY},
            "required": ["target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_world_overview",
        "description": (
            "The wider world: great powers, largest countries by development and army, "
            "the alliance networks of the major powers, ongoing wars by size, personal "
            "unions and the Holy Roman Empire."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_missions",
        "description": (
            "A country's mission tree from the game files with progress from the save: "
            "completed, available now (prerequisites done) or locked, with requirements and "
            "rewards (including the bonuses of granted modifiers). Set `brief` for titles "
            "and status only. Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": _COUNTRY,
                "brief": {"type": "boolean", "description": "Titles and status only."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_decisions",
        "description": (
            "Formable nations and decisions a country can see, each with a requirement "
            "checklist: met, not met, or not checkable automatically. Set `formables_only` "
            "to list only nations it can form. Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": _COUNTRY,
                "formables_only": {"type": "boolean", "description": "Only formable nations."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_expansion_targets",
        "description": (
            "Where a country should expand: provinces wanted by its available missions, "
            "visible formable nations, claims and cores, grouped by who holds them, with a "
            "war check against each owner (favourable, even and hard targets; owners under a "
            "truce or defended by your own allies last; provinces held by subjects or "
            "allies listed apart). Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"country": _COUNTRY},
            "additionalProperties": False,
        },
    },
]


@dataclass
class _Field:
    kind: type
    required: bool = False


_SCHEMAS: dict[str, dict[str, _Field]] = {
    "get_country_briefing": {"country": _Field(str)},
    "check_war": {"target": _Field(str, required=True), "attacker": _Field(str)},
    "get_world_overview": {},
    "get_missions": {"country": _Field(str), "brief": _Field(bool)},
    "get_decisions": {"country": _Field(str), "formables_only": _Field(bool)},
    "get_expansion_targets": {"country": _Field(str)},
}


# Game data the toolbox loads lazily; shared when the save changes (see with_campaign).
_GAME_DATA = ("_missions", "_decisions", "_rules", "_modifiers")


class Toolbox:
    """Runs tools against one loaded save; game data is loaded on first use."""

    def __init__(self, campaign: Campaign, game_dir: Path | None) -> None:
        """Bind the tools to a campaign and, optionally, the game installation."""
        self.campaign = campaign
        self.game_dir = game_dir

    @property
    def definitions(self) -> list[dict[str, Any]]:
        """Tool definitions for the Messages API (stable order for prompt caching)."""
        return TOOL_DEFINITIONS

    def with_campaign(self, campaign: Campaign) -> Toolbox:
        """A toolbox for another save that reuses the game data already loaded here."""
        other = Toolbox(campaign, self.game_dir)
        for name in _GAME_DATA:
            if name in self.__dict__:  # cached_property values live in the instance dict
                other.__dict__[name] = self.__dict__[name]
        return other

    def run(self, name: str, arguments: Any) -> str:
        """Run a tool and return its Markdown output.

        Raises:
            ToolInputError: If the arguments do not match the tool's schema.
            CountryLookupError: If a country name matches nothing or several countries.
            KeyError: If the tool does not exist.
        """
        args = validate(name, arguments)
        handler: Callable[[dict[str, Any]], str] = getattr(self, f"_{name}")
        return handler(args)

    # --- handlers -----------------------------------------------------------------------

    def _get_country_briefing(self, args: dict[str, Any]) -> str:
        return summarize(self.campaign, self._tag(args.get("country")))

    def _check_war(self, args: dict[str, Any]) -> str:
        target = self._tag(args["target"])
        attacker = self._tag(args.get("attacker"))
        return render_war_check(self.campaign, check_war(self.campaign, target, attacker))

    def _get_world_overview(self, args: dict[str, Any]) -> str:
        return render_world(self.campaign, world_overview(self.campaign))

    def _get_missions(self, args: dict[str, Any]) -> str:
        tree = mission_tree(self.campaign, self._missions, self._tag(args.get("country")))
        brief = bool(args.get("brief"))
        return render_missions(self.campaign, tree, brief=brief, modifiers=self._modifiers)

    def _get_decisions(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        checks = check_decisions(
            self.campaign,
            self._rules,
            self._decisions,
            tag,
            missions=self._missions,
            formables_only=bool(args.get("formables_only")),
        )
        return render_decisions(self.campaign, tag, checks, self._modifiers)

    def _get_expansion_targets(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        report = find_targets(self.campaign, self._rules, self._missions, self._decisions, tag)
        return render_targets(self.campaign, report)

    # --- helpers ------------------------------------------------------------------------

    def _tag(self, country: str | None) -> str:
        return self.campaign.resolve_country(country) if country else self.campaign.player

    def _game_dir(self) -> Path:
        if self.game_dir is None:
            raise ToolInputError("This tool needs the game files, and EU4_GAME_DIR is not set.")
        return self.game_dir

    @cached_property
    def _missions(self) -> MissionLibrary:
        return MissionLibrary.load(self._game_dir())

    @cached_property
    def _decisions(self) -> DecisionLibrary:
        return DecisionLibrary.load(self._game_dir())

    @cached_property
    def _rules(self) -> GameRules:
        return GameRules.load(self._game_dir())

    @cached_property
    def _modifiers(self) -> ModifierLibrary:
        return ModifierLibrary.load(self._game_dir())


def validate(name: str, arguments: Any) -> dict[str, Any]:
    """Check tool arguments against the tool's schema.

    Tool inputs arrive as model output (and, with streamed inputs, may be truncated), so
    they are validated before anything runs.

    Raises:
        KeyError: Unknown tool.
        ToolInputError: Wrong shape, unknown or missing fields, or wrong types.
    """
    schema = _SCHEMAS[name]
    if not isinstance(arguments, dict):
        raise ToolInputError(f"{name} expects an object of arguments")
    unknown = set(arguments) - set(schema)
    if unknown:
        raise ToolInputError(f"{name} got unknown arguments: {', '.join(sorted(unknown))}")
    for field, spec in schema.items():
        if field not in arguments:
            if spec.required:
                raise ToolInputError(f"{name} needs `{field}`")
            continue
        value = arguments[field]
        if not isinstance(value, spec.kind) or (spec.kind is str and not value.strip()):
            raise ToolInputError(f"{name}: `{field}` must be a {spec.kind.__name__}")
    return arguments


__all__ = ["TOOL_DEFINITIONS", "CountryLookupError", "ToolInputError", "Toolbox", "validate"]
