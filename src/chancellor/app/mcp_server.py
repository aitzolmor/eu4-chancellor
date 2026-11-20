"""MCP server: the Chancellor's tools inside Claude Desktop (``chancellor mcp``).

The Model Context Protocol lets Claude Desktop start a local program and call its tools.
This server exposes the same queries as the CLI and the API chat (D-009, D-016), so a
player with a Claude subscription can use them in Claude Desktop with no API key and no
per-question billing.

Each call reads the newest save: the server remembers which file and modification time it
loaded and reloads only when the game has written a newer one. Game data (localisation,
missions, decisions, ...) is loaded once and reused across reloads.

The server talks over stdio, so nothing in this process may print to stdout.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from chancellor.config import Settings
from chancellor.context.campaign import Campaign, CountryLookupError
from chancellor.context.tools import TOOL_DEFINITIONS, Toolbox, ToolInputError
from chancellor.player.context import context_path
from chancellor.save.loader import find_current_save

SERVER_NAME = "eu4-chancellor"

INSTRUCTIONS = """\
Tools for Europa Universalis IV (game version 1.37). They read the player's latest save \
file and the game's own files, so answers can rest on the real state of the campaign.

- At the start of a conversation, read the player's context (get_player_context): their \
goals, wants and limits and decisions from earlier chats. Follow it. When the player states \
a goal, a preference or limit, or a decision, or one is reached, dropped or changed, record \
it with update_player_context and tell them; record only what the player says, never your \
own suggestions. Measure each goal with track_goal (its missions, provinces, countries or \
numbers) and say what you measure. When they ask to be told when something happens, set \
a watch with create_watch and say which thresholds you chose. For what happened recently in \
the campaign, read get_campaign_journal; for how the numbers moved over time, \
get_trends. For trade, get_trade; for a war in progress, get_wars; for income and \
expenses, get_budget. For what to do next, get_recommendations, then weigh its options \
with the player's goals.
- Call them whenever a question depends on the campaign: the player's country, another \
country, a possible war, the world, missions, formable nations or where to expand. \
Several independent lookups can be made in parallel.
- Countries can be named by tag (BUR) or by name in the player's game language (Borgoña).
- Every call reads the newest save, so after the player saves, look things up again.
- The tools do not know casus belli, or the live war score (get_wars gives the score \
at the game's last quarterly check). Truces are known, but their end dates are estimates. \
Requirements marked [?] could not be checked automatically.
- Use the computed mechanics instead of rules of thumb: the country briefing says what \
monarch power buys (technology, ideas, stability, generals, development) and the war check \
estimates the aggressive expansion of a conquest. Never recommend buying what the country \
cannot afford or does not need.
- For how a mechanic works or for strategy, use search_wiki with English game terms and cite \
the page: before advising on idea groups, an expansion plan, subjects, coalitions or the \
Empire, look up how experienced players handle it. The save and the computed numbers take \
precedence over the wiki.
- Give concrete, prioritised advice with the numbers and names behind it, then the risks. \
Skip advice every player already follows.
"""

_DESCRIPTIONS = {tool["name"]: tool["description"] for tool in TOOL_DEFINITIONS}


# Typed so the client sees the fields of a condition: a plain list[dict] left Claude
# Desktop guessing the shape, and its first call failed (D-041). typing_extensions'
# TypedDict, because pydantic needs it on Python 3.11. The docstring reaches the model.
class WatchCondition(TypedDict):
    """One condition of a watch.

    A metric from the tool description, an operator (>= or <= for numbers, is for
    true/false), a value, and the countries (names or tags; the player when left out).
    """

    metric: str
    op: Literal[">=", "<=", "is"]
    value: float | bool
    country: NotRequired[str]
    other: NotRequired[str]


class GoalMeasure(TypedDict):
    """One measure of a goal (D-061): a kind and the fields that kind uses."""

    kind: Literal["mission", "formable", "provinces", "country", "metric"]
    key: NotRequired[str]
    count: NotRequired[int]
    subjects: NotRequired[bool]
    state: NotRequired[Literal["subject", "gone"]]
    condition: NotRequired[WatchCondition]


@dataclass
class _Loaded:
    path: Path
    mtime: float
    toolbox: Toolbox


class CampaignProvider:
    """Hands out a toolbox bound to the newest save, reloading only when it changes."""

    def __init__(self, settings: Settings, load: Callable[[Path], Campaign]) -> None:
        """Create a provider.

        Args:
            settings: Paths to the save folder and game installation.
            load: Loads a campaign (with localisation) from a save path.
        """
        self.settings = settings
        self._load = load
        self._loaded: _Loaded | None = None

    def toolbox(self) -> Toolbox:
        """The toolbox for the current save.

        Raises:
            RuntimeError: If no save folder is configured or it holds no saves.
        """
        if self.settings.save_dir is None:
            raise RuntimeError("EU4_SAVE_DIR is not set; configure it for the MCP server.")
        try:
            path = find_current_save(self.settings.save_dir)
        except FileNotFoundError as exc:
            raise RuntimeError(str(exc)) from exc
        mtime = path.stat().st_mtime
        current = self._loaded
        if current is None or current.path != path or current.mtime != mtime:
            campaign = self._load(path)
            toolbox = (
                current.toolbox.with_campaign(campaign)
                if current
                else Toolbox(campaign, self.settings.game_dir, context_path(self.settings.save_dir))
            )
            self._loaded = _Loaded(path, mtime, toolbox)
            # Each new save read goes into the campaign journal (D-043); a failure there
            # must never stop the tools.
            with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                toolbox.remember_save()
        return self._loaded.toolbox

    @property
    def save_path(self) -> Path | None:
        """The save currently loaded, if any."""
        return self._loaded.path if self._loaded else None


def build_server(provider: CampaignProvider) -> Any:
    """Create the MCP server with one tool per query.

    Args:
        provider: Supplies the toolbox for the newest save.

    Returns:
        An ``mcp.server.mcpserver.MCPServer`` ready to ``run()``.
    """
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS)
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

    def call(name: str, **arguments: Any) -> str:
        args = {key: value for key, value in arguments.items() if value is not None}
        try:
            return provider.toolbox().run(name, args)
        except (CountryLookupError, ToolInputError, RuntimeError) as exc:
            # ToolError reaches Claude with its message; other exceptions are masked.
            raise ToolError(str(exc)) from exc

    @server.tool(description=_DESCRIPTIONS["get_country_briefing"], annotations=read_only)
    def get_country_briefing(country: str | None = None) -> str:
        return call("get_country_briefing", country=country)

    @server.tool(description=_DESCRIPTIONS["check_war"], annotations=read_only)
    def check_war(target: str, attacker: str | None = None) -> str:
        return call("check_war", target=target, attacker=attacker)

    @server.tool(description=_DESCRIPTIONS["get_world_overview"], annotations=read_only)
    def get_world_overview() -> str:
        return call("get_world_overview")

    @server.tool(description=_DESCRIPTIONS["get_missions"], annotations=read_only)
    def get_missions(country: str | None = None, brief: bool = False) -> str:
        return call("get_missions", country=country, brief=brief)

    @server.tool(description=_DESCRIPTIONS["get_decisions"], annotations=read_only)
    def get_decisions(country: str | None = None, formables_only: bool = False) -> str:
        return call("get_decisions", country=country, formables_only=formables_only)

    @server.tool(description=_DESCRIPTIONS["get_recommendations"], annotations=read_only)
    def get_recommendations(country: str | None = None) -> str:
        return call("get_recommendations", country=country)

    @server.tool(description=_DESCRIPTIONS["get_expansion_targets"], annotations=read_only)
    def get_expansion_targets(country: str | None = None) -> str:
        return call("get_expansion_targets", country=country)

    @server.tool(description=_DESCRIPTIONS["search_wiki"], annotations=read_only)
    def search_wiki(query: str, max_results: int | None = None) -> str:
        return call("search_wiki", query=query, max_results=max_results)

    @server.tool(description=_DESCRIPTIONS["get_player_context"], annotations=read_only)
    def get_player_context() -> str:
        return call("get_player_context")

    @server.tool(description=_DESCRIPTIONS["get_campaign_journal"], annotations=read_only)
    def get_campaign_journal(saves: int | None = None) -> str:
        return call("get_campaign_journal", saves=saves)

    @server.tool(description=_DESCRIPTIONS["get_trends"], annotations=read_only)
    def get_trends(countries: list[str] | None = None) -> str:
        return call("get_trends", countries=countries)

    @server.tool(description=_DESCRIPTIONS["get_wars"], annotations=read_only)
    def get_wars(country: str | None = None) -> str:
        return call("get_wars", country=country)

    @server.tool(description=_DESCRIPTIONS["get_budget"], annotations=read_only)
    def get_budget(country: str | None = None) -> str:
        return call("get_budget", country=country)

    @server.tool(description=_DESCRIPTIONS["get_trade"], annotations=read_only)
    def get_trade(country: str | None = None) -> str:
        return call("get_trade", country=country)

    @server.tool(
        description=_DESCRIPTIONS["update_player_context"],
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
    )
    def update_player_context(
        action: str, kind: str | None = None, text: str | None = None, entry: int | None = None
    ) -> str:
        return call("update_player_context", action=action, kind=kind, text=text, entry=entry)

    @server.tool(
        description=_DESCRIPTIONS["create_watch"],
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
    )
    def create_watch(description: str, conditions: list[WatchCondition]) -> str:
        return call(
            "create_watch", description=description, conditions=[dict(c) for c in conditions]
        )

    @server.tool(
        description=_DESCRIPTIONS["track_goal"],
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    def track_goal(goal: int, measures: list[GoalMeasure]) -> str:
        return call("track_goal", goal=goal, measures=[dict(m) for m in measures])

    @server.tool(
        description=(
            "Which save the tools are reading: file name, in-game date and the player's "
            "country. Use it to confirm the data is current."
        ),
        annotations=read_only,
    )
    def get_save_status() -> str:
        campaign = provider.toolbox().campaign
        return (
            f"Save: {provider.save_path.name if provider.save_path else '?'}\n"
            f"Date: {campaign.date}\n"
            f"Player: {campaign.label(campaign.player)}"
        )

    return server


def desktop_config(settings: Settings, executable: str | None = None) -> dict[str, Any]:
    """The ``mcpServers`` entry for Claude Desktop's ``claude_desktop_config.json``.

    Claude Desktop starts the server from its own working directory, where the project's
    ``.env`` is not found, so the paths are passed as environment variables.
    """
    env = {}
    if settings.save_dir:
        env["EU4_SAVE_DIR"] = str(settings.save_dir)
    if settings.game_dir:
        env["EU4_GAME_DIR"] = str(settings.game_dir)
    if settings.language:
        env["EU4_LANGUAGE"] = settings.language
    return {
        "mcpServers": {
            SERVER_NAME: {
                "command": executable or sys.executable,
                "args": ["-m", "chancellor.app.cli", "mcp"],
                "env": env,
            }
        }
    }


def desktop_config_json(settings: Settings, executable: str | None = None) -> str:
    """:func:`desktop_config` as pretty-printed JSON."""
    return json.dumps(desktop_config(settings, executable), indent=2, ensure_ascii=False)
