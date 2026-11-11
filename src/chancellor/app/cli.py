"""Command-line entry point, installed as the ``chancellor`` command."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chancellor import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="chancellor",
        description="AI assistant for Europa Universalis IV.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser("summary", help="Summarize the latest save (Phase 1).")
    summary.add_argument("--save", type=Path, help="Specific save file to use.")
    summary.add_argument("--copy", action="store_true", help="Copy the summary to the clipboard.")

    sub.add_parser("chat", help="Open the chat window (Phase 2).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    print(f"'{args.command}' is not implemented yet. See docs/ROADMAP.md.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
