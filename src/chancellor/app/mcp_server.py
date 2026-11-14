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

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chancellor.config import Settings
from chancellor.context.campaign import Campaign, CountryLookupError
from chancellor.context.tools import TOOL_DEFINITIONS, Toolbox, ToolInputError
from chancellor.save.loader import find_current_save

SERVER_NAME = "eu4-chancellor"

INSTRUCTIONS = """\
Tools for Europa Universalis IV (game version 1.37). They read the player's latest save \
file and the game's own files, so answers can rest on the real state of the campaign.

- Call them whenever a question depends on the campaign: the player's country, another \
country, a possible war, the world, missions, formable nations or where to expand. \
Several independent lookups can be made in parallel.
- Countries can be named by tag (BUR) or by name in the player's game language (Borgoña).
- Every call reads the newest save, so after the player saves, look things up again.
- The tools do not know war score or casus belli. Truces are known, but their end dates \
are estimates. Requirements marked [?] could not be checked automatically.
- Use the computed mechanics instead of rules of thumb: the country briefing says what \
monarch power buys (technology, ideas, stability, generals, development) and the war check \
estimates the aggressive expansion of a conquest. Never recommend buying what the country \
cannot afford or does not need.
- For how a mechanic works or for strategy, use search_wiki with English game terms and cite \
the page; the save and the computed numbers take precedence over the wiki.
- Give concrete, prioritised advice with the numbers and names behind it, then the risks. \
Skip advice every player already follows.
"""

_DESCRIPTIONS = {tool["name"]: tool["description"] for tool in TOOL_DEFINITIONS}


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
                else Toolbox(campaign, self.settings.game_dir)
            )
            self._loaded = _Loaded(path, mtime, toolbox)
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

    @server.tool(description=_DESCRIPTIONS["get_expansion_targets"], annotations=read_only)
    def get_expansion_targets(country: str | None = None) -> str:
        return call("get_expansion_targets", country=country)

    @server.tool(description=_DESCRIPTIONS["search_wiki"], annotations=read_only)
    def search_wiki(query: str, max_results: int | None = None) -> str:
        return call("search_wiki", query=query, max_results=max_results)

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
