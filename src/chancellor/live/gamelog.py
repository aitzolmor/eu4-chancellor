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
DATE = re.compile(r"\[(\d{3,4}\.\d{1,2}\.\d{1,2})\]")  # "EVENT [1534.07.22]:CHANCELLOR|..."


@dataclass
class ProbeReport:
    """What one game session's log says about the probe's questions.

    Attributes:
        lines: Every mod line, as its fields, oldest first.
        heartbeats: ``(year, month, country)`` for each monthly pulse that ran.
        treasury: The last treasury the mod logged, as written.
        direct: The last ``trigger_value:war_score`` the mod logged, as written.
        ladder: Enemy → the last war score the ladder found against it, as written.
        cb_targets: Tag → name of each country the last month's casus belli check covered.
        casus_belli: Tag → the casus belli types the last month's check found against it.
        subjects: Tag → name of each subject the last month's check covered.
        subject_cb: Subject tag → target tag → the casus belli types that subject has.
        target_names: Tag → name of every target seen in the last month.
        last_date: The game date of the last mod line (``1534.07.22``), when the log
            line carries one.
    """

    lines: list[list[str]] = field(default_factory=list)
    heartbeats: list[tuple[str, str, str]] = field(default_factory=list)
    treasury: str | None = None
    direct: str | None = None
    ladder: dict[str, str] = field(default_factory=dict)
    cb_targets: dict[str, str] = field(default_factory=dict)
    casus_belli: dict[str, list[str]] = field(default_factory=dict)
    subjects: dict[str, str] = field(default_factory=dict)
    subject_cb: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    target_names: dict[str, str] = field(default_factory=dict)
    last_date: str | None = None


def game_log_path(save_dir: Path) -> Path:
    """``logs/game.log`` in the game's user folder (next to ``save games``)."""
    return save_dir.parent / "logs" / "game.log"


def game_log_for(save_dir: Path | None) -> Path | None:
    """:func:`game_log_path`, or ``None`` when the save folder is unknown."""
    return game_log_path(save_dir) if save_dir is not None else None


def read_probe(path: Path) -> ProbeReport:
    """Collect the probe mod's lines from a game log.

    Raises:
        FileNotFoundError: If there is no log (the game has not run).
    """
    report = ProbeReport()
    subject: str | None = None  # the subject whose subcb lines follow
    text = path.read_bytes().decode("cp1252", errors="replace")
    for line in text.splitlines():
        match = MARKER.search(line)
        if not match:
            continue
        fields = match.group(1).strip().split("|")
        report.lines.append(fields)
        kind, rest = fields[0], fields[1:]
        if date := DATE.search(line[: match.start()]):
            report.last_date = date.group(1)
        if kind == "heartbeat" and len(rest) >= 3:
            report.heartbeats.append((rest[0], rest[1], rest[2]))
            # Keep only the latest month.
            report.cb_targets, report.casus_belli = {}, {}
            report.subjects, report.subject_cb, report.target_names = {}, {}, {}
            report.ladder, report.direct = {}, None  # the war score too (D-063)
            subject = None
        elif kind == "cbtarget" and len(rest) >= 2:
            report.cb_targets[rest[0]] = rest[1]
            report.target_names[rest[0]] = rest[1]
        elif kind == "subject" and len(rest) >= 2:
            subject = rest[0]
            report.subjects[subject] = rest[1]
        elif kind == "subcb" and len(rest) >= 3 and subject:
            report.target_names[rest[0]] = rest[1]
            report.subject_cb.setdefault(subject, {}).setdefault(rest[0], []).append(rest[2])
        elif kind == "cb" and len(rest) >= 2:
            report.casus_belli.setdefault(rest[0], []).append(rest[1])
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
        (
            f"4. Casus belli (has_casus_belli), last month: {len(report.cb_targets)} countries "
            f"checked, {len(report.casus_belli)} with at least one"
            if report.cb_targets
            else "4. Casus belli: no check ran (an older mod; run `chancellor probe install`)"
        ),
        *(
            f"   - {report.cb_targets.get(tag, tag)} ({tag}): {', '.join(types)}"
            for tag, types in report.casus_belli.items()
        ),
        *(
            [f"   - none found against: {', '.join(sorted(report.cb_targets))}"]
            if report.cb_targets and not report.casus_belli
            else []
        ),
        *(
            [
                f"5. Subjects' casus belli, last month: {len(report.subjects)} subjects, "
                f"{len(report.subject_cb)} with at least one"
            ]
            if report.subjects
            else []
        ),
        *(
            f"   - {report.subjects.get(sub, sub)} ({sub}) against "
            f"{report.target_names.get(tag, tag)} ({tag}): {', '.join(types)}"
            for sub, targets in report.subject_cb.items()
            for tag, types in targets.items()
        ),
        "",
        "Last lines:",
        *("  " + "|".join(fields) for fields in report.lines[-8:]),
    ]
    return "\n".join(lines) + "\n"
