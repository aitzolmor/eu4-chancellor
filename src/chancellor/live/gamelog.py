"""Read what the probe mod wrote to the game's ``logs/game.log`` (D-044).

The game writes its log as Windows-1252 text, one line per entry, prefixed with the
source file (``[effectimplementation.cpp:123]: ...``). The mod's lines carry
``CHANCELLOR|kind|field|...``. The log starts empty each time the game starts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MARKER = re.compile(r"CHANCELLOR\|(.*)$")


@dataclass
class ProbeReport:
    """What one game session's log says about the probe's questions.

    Attributes:
        lines: Every mod line, as its fields, oldest first.
        heartbeats: ``(year, month, country)`` for each monthly pulse that ran.
        treasury: The last treasury the mod logged, as written.
        direct: The last ``trigger_value:war_score`` the mod logged, as written.
        ladder: Enemy → the last war score the ladder found against it, as written.
    """

    lines: list[list[str]] = field(default_factory=list)
    heartbeats: list[tuple[str, str, str]] = field(default_factory=list)
    treasury: str | None = None
    direct: str | None = None
    ladder: dict[str, str] = field(default_factory=dict)


def game_log_path(save_dir: Path) -> Path:
    """``logs/game.log`` in the game's user folder (next to ``save games``)."""
    return save_dir.parent / "logs" / "game.log"


def read_probe(path: Path) -> ProbeReport:
    """Collect the probe mod's lines from a game log.

    Raises:
        FileNotFoundError: If there is no log (the game has not run).
    """
    report = ProbeReport()
    text = path.read_bytes().decode("cp1252", errors="replace")
    for line in text.splitlines():
        match = MARKER.search(line)
        if not match:
            continue
        fields = match.group(1).strip().split("|")
        report.lines.append(fields)
        kind, rest = fields[0], fields[1:]
        if kind == "heartbeat" and len(rest) >= 3:
            report.heartbeats.append((rest[0], rest[1], rest[2]))
        elif kind == "treasury" and rest:
            report.treasury = rest[0]
        elif kind == "direct" and rest:
            report.direct = rest[0]
        elif kind == "ladder" and len(rest) >= 2:
            report.ladder[rest[0]] = rest[1]
    return report


def render_probe(report: ProbeReport, path: Path) -> str:
    """A plain answer to each of the probe's questions."""
    if not report.lines:
        return (
            f"No Chancellor lines in {path}.\n"
            "Either the mod is not enabled in the launcher's playset, or the game has not "
            "passed a month since it started, or on_monthly_pulse did not run the event."
        )
    first, last = report.heartbeats[:1], report.heartbeats[-1:]
    lines = [
        f"Chancellor lines in {path}: {len(report.lines)}",
        "",
        f"1. Monthly pulse: {len(report.heartbeats)} heartbeats"
        + (
            f", from {first[0][0]}.{first[0][1]} to {last[0][0]}.{last[0][1]} ({last[0][2]})"
            if report.heartbeats
            else ""
        ),
        f"2. Variable in a log line (treasury): {report.treasury!r}",
        f"3a. War score, direct (trigger_value:war_score): {report.direct!r}",
        "3b. War score, ladder (war_score_against every 5): "
        + (", ".join(f"{who} {score}" for who, score in report.ladder.items()) or "no war"),
        "",
        "Last lines:",
        *("  " + "|".join(fields) for fields in report.lines[-8:]),
    ]
    return "\n".join(lines) + "\n"
