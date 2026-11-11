"""Command-line entry point, installed as the ``chancellor`` command."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chancellor import __version__
from chancellor.app.clipboard import ClipboardError, copy_to_clipboard
from chancellor.config import Settings, load_settings
from chancellor.context.summarizer import summarize_save
from chancellor.game.localisation import Localisation, detect_language
from chancellor.save.loader import SaveFormatError, find_current_save, load_save


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="chancellor",
        description="AI assistant for Europa Universalis IV.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser(
        "summary",
        help="Print a briefing of the current campaign.",
        description="Print a Markdown briefing of the current campaign, ready for an LLM.",
    )
    summary.add_argument(
        "--save", type=Path, help="Save file to use (default: the current campaign)."
    )
    summary.add_argument(
        "--copy", action="store_true", help="Also copy the briefing to the clipboard."
    )
    summary.add_argument("--output", type=Path, help="Also write the briefing to this file.")
    summary.add_argument(
        "--language", help="Name language, e.g. english or spanish (default: game setting)."
    )

    sub.add_parser("chat", help="Open the chat window (Phase 2, not implemented yet).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    if args.command == "summary":
        return _summary(args, load_settings())
    print(f"'{args.command}' is not implemented yet. See docs/ROADMAP.md.", file=sys.stderr)
    return 1


def _summary(args: argparse.Namespace, settings: Settings) -> int:
    save_path: Path | None = args.save
    if save_path is None:
        if settings.save_dir is None:
            return _fail("No save given and EU4_SAVE_DIR is not set (see .env.example).")
        try:
            save_path = find_current_save(settings.save_dir)
        except FileNotFoundError as exc:
            return _fail(str(exc))

    try:
        raw = load_save(save_path)
    except (OSError, SaveFormatError) as exc:
        return _fail(str(exc))

    loc = Localisation()
    if settings.game_dir is not None:
        language = args.language or settings.language
        if language is None:
            user_dir = settings.save_dir.parent if settings.save_dir else save_path.parent.parent
            language = detect_language(user_dir)
        loc = Localisation.load(settings.game_dir, language)

    briefing = summarize_save(raw, loc)

    _write_stdout(briefing)
    if args.output:
        args.output.write_text(briefing, encoding="utf-8")
    if args.copy:
        try:
            copy_to_clipboard(briefing)
        except ClipboardError as exc:
            return _fail(str(exc))
        print(f"Briefing for {save_path.name} copied to the clipboard.", file=sys.stderr)
    return 0


def _write_stdout(text: str) -> None:
    """Write UTF-8 text even on consoles with a legacy code page."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(text)


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
