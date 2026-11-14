"""Command-line entry point, installed as the ``chancellor`` command."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chancellor import __version__
from chancellor.app.clipboard import ClipboardError, copy_to_clipboard
from chancellor.config import Settings, load_settings
from chancellor.context.ae import render_ae_section
from chancellor.context.campaign import Campaign, CountryLookupError
from chancellor.context.decisions import check_decisions, render_decisions
from chancellor.context.missions import mission_tree, render_missions
from chancellor.context.summarizer import summarize
from chancellor.context.targets import find_targets, render_targets
from chancellor.context.war_check import check_war, render_war_check
from chancellor.context.world import render_world, world_overview
from chancellor.game.ae_rules import AeRules
from chancellor.game.cache import cache_dir, clear_cache
from chancellor.game.decisions import DecisionLibrary
from chancellor.game.imperial_reforms import ImperialReformLibrary
from chancellor.game.localisation import Localisation, detect_language
from chancellor.game.missions import MissionLibrary
from chancellor.game.modifiers import ModifierLibrary
from chancellor.game.power_rules import PowerRules
from chancellor.game.rules import GameRules
from chancellor.save.loader import SaveFormatError, find_current_save, load_save


class CliError(Exception):
    """An error to report to the user as ``error: <message>`` with exit code 1."""


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="chancellor",
        description="AI assistant for Europa Universalis IV.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # Options shared by every command that reads a save and prints Markdown.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--save", type=Path, help="Save file to use (default: the current campaign)."
    )
    common.add_argument(
        "--copy", action="store_true", help="Also copy the output to the clipboard."
    )
    common.add_argument("--output", type=Path, help="Also write the output to this file.")
    common.add_argument(
        "--language", help="Name language, e.g. english or spanish (default: game setting)."
    )

    sub.add_parser(
        "summary",
        parents=[common],
        help="Print a briefing of your own country.",
        description="Print a Markdown briefing of the current campaign, ready for an LLM.",
    )
    country = sub.add_parser(
        "country",
        parents=[common],
        help="Print a briefing of any country.",
        description=(
            "Print a Markdown briefing of any country, including its relation to the player. "
            "Accepts a tag (BUR) or a name in the game's language (Borgoña, borgona, Borg)."
        ),
    )
    country.add_argument("name", nargs="+", help="Country tag or name.")

    war = sub.add_parser(
        "war-check",
        parents=[common],
        help="Who would fight if you declared war on a country.",
        description=(
            "List who would defend the target (allies, subjects, overlord, guarantors, the "
            "Emperor, coalitions) and who would join you, with the strength of each side."
        ),
    )
    war.add_argument("target", nargs="+", help="Target country tag or name.")
    war.add_argument(
        "--attacker", help="Attacking country tag or name (default: you). Quote names with spaces."
    )

    world = sub.add_parser(
        "world",
        parents=[common],
        help="Overview of the world: great powers, rankings, alliances and wars.",
        description=(
            "Print the big picture: great powers, the largest countries, the alliance "
            "networks of the major powers, ongoing wars, personal unions and the HRE."
        ),
    )
    world.add_argument("--top", type=int, default=10, help="Countries per ranking (default 10).")

    missions = sub.add_parser(
        "missions",
        parents=[common],
        help="Mission tree of a country with progress, requirements and rewards.",
        description=(
            "Show a country's mission tree (default: yours) from the game files, marking "
            "what is completed, available now and locked, with requirements and rewards."
        ),
    )
    missions.add_argument("name", nargs="*", help="Country tag or name (default: you).")
    missions.add_argument(
        "--brief", action="store_true", help="Only titles and status, no requirements/rewards."
    )

    decisions = sub.add_parser(
        "decisions",
        parents=[common],
        help="Formable nations and decisions a country can take, with a checklist.",
        description=(
            "List the formable nations and decisions a country (default: you) can see, "
            "each with its requirements marked met, not met or unchecked."
        ),
    )
    decisions.add_argument("name", nargs="*", help="Country tag or name (default: you).")
    decisions.add_argument("--formables", action="store_true", help="Only formable nations.")

    targets = sub.add_parser(
        "targets",
        parents=[common],
        help="Where to expand: wanted provinces by owner, with war odds.",
        description=(
            "Cross the provinces wanted by available missions, visible formable nations, "
            "claims and cores with who holds them now and a war check against each owner."
        ),
    )
    targets.add_argument("name", nargs="*", help="Country tag or name (default: you).")
    targets.add_argument("--top", type=int, default=15, help="War targets to list (default 15).")

    sub.add_parser(
        "mcp",
        help="Run the MCP server so Claude Desktop can use the Chancellor's tools.",
        description=(
            "Serve the queries over the Model Context Protocol (stdio). Claude Desktop "
            "starts this command itself; see `chancellor mcp-config`."
        ),
    )
    sub.add_parser(
        "mcp-config",
        help="Print the Claude Desktop configuration for the MCP server.",
        description=(
            "Print the JSON to merge into Claude Desktop's claude_desktop_config.json, "
            "with this installation's Python and your save and game folders."
        ),
    )

    sub.add_parser(
        "app",
        help="Open the Chancellor panel, a desktop window to keep beside the game.",
        description=(
            "Open the desktop panel with your campaign at a glance. Needs the optional "
            'UI dependency: pip install -e ".[ui]".'
        ),
    )

    sub.add_parser(
        "clear-cache",
        help="Delete cached game data (it is rebuilt automatically when needed).",
    )

    chat = sub.add_parser(
        "chat",
        help="Chat with the Chancellor about your campaign (needs an Anthropic API key).",
        description=(
            "Ask questions in plain language; Claude looks up your save and the game files "
            "with the same queries as the other commands. Reloads automatically when you save."
        ),
    )
    chat.add_argument("--save", type=Path, help="Save file to use (default: the current one).")
    chat.add_argument("--language", help="Name language (default: game setting).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    _use_utf8()
    if args.command == "clear-cache":
        removed = clear_cache()
        print(f"Removed {removed} cached file(s) from {cache_dir()}.", file=sys.stderr)
        return 0
    try:
        if args.command == "summary":
            settings = load_settings()
            campaign, save_path = _load_campaign(args, settings)
            briefing = summarize(
                campaign, reforms=_imperial_reforms(settings), power_rules=_power_rules(settings)
            )
            return _emit(args, briefing, f"Briefing for {save_path.name}")
        if args.command == "country":
            settings = load_settings()
            campaign, save_path = _load_campaign(args, settings)
            tag = campaign.resolve_country(" ".join(args.name))
            briefing = summarize(
                campaign,
                tag,
                reforms=_imperial_reforms(settings),
                power_rules=_power_rules(settings),
            )
            return _emit(args, briefing, f"Briefing of {campaign.label(tag)}")
        if args.command == "war-check":
            settings = load_settings()
            campaign, _ = _load_campaign(args, settings)
            target = campaign.resolve_country(" ".join(args.target))
            attacker = campaign.resolve_country(args.attacker) if args.attacker else None
            text = render_war_check(campaign, check_war(campaign, target, attacker))
            if settings.game_dir is not None:
                ae_rules = AeRules.load(settings.game_dir)
                rules = GameRules.load(settings.game_dir)
                text += "\n" + render_ae_section(campaign, ae_rules, rules, target, attacker)
            return _emit(args, text, f"War check against {campaign.label(target)}")
        if args.command == "world":
            campaign, save_path = _load_campaign(args, load_settings())
            overview = world_overview(campaign, top=max(1, args.top))
            return _emit(args, render_world(campaign, overview), "World overview")
        if args.command == "missions":
            settings = load_settings()
            if settings.game_dir is None:
                raise CliError("Missions are read from the game files; set EU4_GAME_DIR.")
            campaign, _ = _load_campaign(args, settings)
            tag = campaign.resolve_country(" ".join(args.name)) if args.name else campaign.player
            tree = mission_tree(campaign, MissionLibrary.load(settings.game_dir), tag)
            modifiers = ModifierLibrary.load(settings.game_dir)
            text = render_missions(campaign, tree, brief=args.brief, modifiers=modifiers)
            return _emit(args, text, f"Missions of {campaign.label(tag)}")
        if args.command == "decisions":
            settings = load_settings()
            if settings.game_dir is None:
                raise CliError("Decisions are read from the game files; set EU4_GAME_DIR.")
            campaign, _ = _load_campaign(args, settings)
            tag = campaign.resolve_country(" ".join(args.name)) if args.name else campaign.player
            checks = check_decisions(
                campaign,
                GameRules.load(settings.game_dir),
                DecisionLibrary.load(settings.game_dir),
                tag,
                missions=MissionLibrary.load(settings.game_dir),
                formables_only=args.formables,
            )
            modifiers = ModifierLibrary.load(settings.game_dir)
            text = render_decisions(campaign, tag, checks, modifiers)
            return _emit(args, text, f"Decisions of {campaign.label(tag)}")
        if args.command == "mcp":
            from chancellor.app.mcp_server import CampaignProvider, build_server

            settings = load_settings()

            def load_path(path: Path) -> Campaign:
                options = argparse.Namespace(save=path, language=None)
                return _load_campaign(options, settings)[0]

            build_server(CampaignProvider(settings, load_path)).run("stdio")
            return 0
        if args.command == "app":
            settings = load_settings()

            def load_panel_save(path: Path) -> Campaign:
                options = argparse.Namespace(save=path, language=None)
                return _load_campaign(options, settings)[0]

            try:
                from chancellor.app.ui import run_panel

                run_panel(settings, load_panel_save)
            except ImportError as exc:
                raise CliError(
                    f'The panel needs pywebview ({exc}). Install it with: pip install -e ".[ui]"'
                ) from exc
            return 0
        if args.command == "mcp-config":
            from chancellor.app.mcp_server import desktop_config_json

            _write_stdout(desktop_config_json(load_settings()) + "\n")
            return 0
        if args.command == "chat":
            settings = load_settings()

            def load(current: Settings) -> tuple[Campaign, Path]:
                campaign, path = _load_campaign(args, current)
                args.save = None  # after the first load, always follow the newest save
                return campaign, path

            from chancellor.app.chat import run_chat  # deferred: the SDK is slow to import

            return run_chat(settings, load)
        if args.command == "targets":
            settings = load_settings()
            if settings.game_dir is None:
                raise CliError("Targets need the game files; set EU4_GAME_DIR.")
            campaign, _ = _load_campaign(args, settings)
            tag = campaign.resolve_country(" ".join(args.name)) if args.name else campaign.player
            report = find_targets(
                campaign,
                GameRules.load(settings.game_dir),
                MissionLibrary.load(settings.game_dir),
                DecisionLibrary.load(settings.game_dir),
                tag,
            )
            text = render_targets(campaign, report, top=max(1, args.top))
            return _emit(args, text, f"Expansion targets of {campaign.label(tag)}")
    except ValueError as exc:  # e.g. a country attacking itself
        return _fail(str(exc))
    except (CliError, CountryLookupError) as exc:
        return _fail(str(exc))
    print(f"'{args.command}' is not implemented yet. See docs/ROADMAP.md.", file=sys.stderr)
    return 1


def _imperial_reforms(settings: Settings) -> ImperialReformLibrary | None:
    """Imperial reforms for briefings, or ``None`` without the game files."""
    return ImperialReformLibrary.load(settings.game_dir) if settings.game_dir else None


def _power_rules(settings: Settings) -> PowerRules | None:
    """Monarch power cost rules for briefings, or ``None`` without the game files."""
    return PowerRules.load(settings.game_dir) if settings.game_dir else None


def _load_campaign(args: argparse.Namespace, settings: Settings) -> tuple[Campaign, Path]:
    """Load the requested (or current) save together with localisation."""
    save_path: Path | None = args.save
    if save_path is None:
        if settings.save_dir is None:
            raise CliError("No save given and EU4_SAVE_DIR is not set (see .env.example).")
        try:
            save_path = find_current_save(settings.save_dir)
        except FileNotFoundError as exc:
            raise CliError(str(exc)) from exc

    try:
        raw = load_save(save_path)
    except (OSError, SaveFormatError) as exc:
        raise CliError(str(exc)) from exc

    loc = Localisation()
    if settings.game_dir is not None:
        language = args.language or settings.language
        if language is None:
            user_dir = settings.save_dir.parent if settings.save_dir else save_path.parent.parent
            language = detect_language(user_dir)
        loc = Localisation.load(settings.game_dir, language)

    return Campaign.from_raw(raw, loc), save_path


def _emit(args: argparse.Namespace, text: str, what: str) -> int:
    """Print the output and honour ``--output`` and ``--copy``."""
    _write_stdout(text)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    if args.copy:
        try:
            copy_to_clipboard(text)
        except ClipboardError as exc:
            return _fail(str(exc))
        print(f"{what} copied to the clipboard.", file=sys.stderr)
    return 0


def _write_stdout(text: str) -> None:
    """Write text to stdout (UTF-8, see :func:`_use_utf8`)."""
    sys.stdout.write(text)


def _use_utf8() -> None:
    """Make stdout and stderr UTF-8, even on consoles with a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
