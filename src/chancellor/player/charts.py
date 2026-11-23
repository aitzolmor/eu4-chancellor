"""Pointing the player at a chart of the panel's Charts tab (D-068).

The model answers in Claude Desktop (or the panel's API chat) while the charts live in
the panel, another process. The ``show_chart`` tool writes a small request file next to
the player's context; the panel watches it, opens its Charts tab and marks that chart.
The tool also returns the chart's numbers, so the model cites what the player sees.

The chart ids are the ones ``app/web/charts.js`` gives its figures; a test keeps the two
lists equal.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chancellor.player.journal import NUMBERS, TREND_ROWS, _fmt, _sample

REQUEST_FILE = "chart_request.json"


@dataclass(frozen=True)
class Chart:
    """One chart of the Charts tab.

    Attributes:
        id: The id the panel's figure carries (``data-chart``).
        title: Its caption.
        kind: ``own`` (the player's series), ``budget`` (categories) or ``compare``
            (the player against rivals or picked countries).
        keys: The journal series drawn (``own``, ``compare``) or the budget side.
    """

    id: str
    title: str
    kind: str
    keys: tuple[str, ...]


CHARTS: dict[str, Chart] = {
    chart.id: chart
    for chart in (
        Chart("treasury", "Treasury (ducats)", "own", ("treasury",)),
        Chart("income_expenses", "Income and expenses (a month)", "own", ("income", "expenses")),
        Chart("regiments", "Regiments", "own", ("regiments",)),
        Chart("manpower", "Manpower (thousands)", "own", ("manpower",)),
        Chart("development", "Development", "own", ("development",)),
        Chart("coalition_ae", "Countries at 50+ AE", "own", ("at_coalition_ae",)),
        Chart("income_by_source", "Income by source (a month)", "budget", ("income",)),
        Chart("recurring_expenses", "Recurring expenses (a month)", "budget", ("expenses",)),
        Chart("one_off_spending", "One-off spending (a month)", "budget", ("one_off",)),
        Chart("compare_development", "Development, against others", "compare", ("development",)),
        Chart("compare_regiments", "Regiments, against others", "compare", ("regiments",)),
        Chart("compare_income", "Monthly income, against others", "compare", ("income",)),
    )
}


def request_path(context_file: Path) -> Path:
    """Where chart requests go: beside the player's context file."""
    return context_file.parent / REQUEST_FILE


def write_request(path: Path, chart: str) -> dict[str, Any]:
    """Ask the panel to show a chart. Returns what was written."""
    request = {"chart": chart, "at": time.time_ns()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(request), encoding="utf-8")
    temporary.replace(path)  # the panel never reads half a file
    return request


def read_request(path: Path) -> dict[str, Any] | None:
    """The latest request, or ``None`` if there is none or it cannot be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("chart") not in CHARTS:
        return None
    return data


def render_chart(data: dict[str, Any], chart: Chart, shown: bool) -> str:
    """Markdown for ``show_chart``: what the panel did and the chart's numbers.

    Args:
        data: :meth:`chancellor.context.tools.Toolbox.trends` output.
        chart: The chart asked for.
        shown: Whether the request reached the panel's folder.
    """
    lines = [f"# Chart: {chart.title}", ""]
    lines.append(
        "Asked the Chancellor panel to open its Charts tab on this chart and mark it; if the "
        "panel is not running, the player can open it with `chancellor app`."
        if shown
        else "The panel could not be asked to show it (its folder is not writable)."
    )
    dates = data.get("dates") or []
    columns = _columns(data, chart)
    if len(dates) < 2 or not columns:
        lines += ["", "Not enough saves recorded yet for this chart."]
        return "\n".join(lines) + "\n"
    rows = _sample(len(dates), TREND_ROWS)
    digits = {key: d for key, _, d in NUMBERS}
    lines += [
        "",
        f"The numbers it draws ({len(dates)} saves, {dates[0]} to {dates[-1]}; {len(rows)} shown):",
        "",
        "| Date | " + " | ".join(label for label, _, _ in columns) + " |",
        "| --- |" + " --- |" * len(columns),
    ]
    for i in rows:
        cells = []
        for _, values, key in columns:
            value = values[i] if i < len(values) else None
            cells.append("-" if value is None else _fmt(value, digits.get(key, 1)))
        lines.append(f"| {dates[i]} | " + " | ".join(cells) + " |")
    events = [e for e in data.get("events") or [] if dates[0] <= e["date"] <= dates[-1]]
    if events:
        lines += ["", "Marked on its time axis:", ""]
        lines += [f"- {e['date']}: {e['text']}" for e in events[-8:]]
    lines += [
        "",
        f'_Refer the player to the chart "{chart.title}" in the panel\'s Charts tab and '
        "cite these numbers; the journal has one record per save read, so the spacing "
        "between dates varies._",
    ]
    return "\n".join(lines) + "\n"


def _columns(data: dict[str, Any], chart: Chart) -> list[tuple[str, list[Any], str]]:
    """``(label, values, journal key)`` for each line the chart draws."""
    series = data.get("series") or {}
    labels = data.get("labels") or {}
    if chart.kind == "own":
        return [(labels.get(k, k), series[k], k) for k in chart.keys if k in series]
    if chart.kind == "budget":
        budget = data.get("budget") or {}
        side = chart.keys[0]
        if side == "one_off":
            values = budget.get("one_off") or []
            return [("one-off spending", values, "")] if values else []
        return [(name, values, "") for name, values in (budget.get(side) or {}).items()]
    key = chart.keys[0]
    names = data.get("names") or {}
    player = next(iter(names), None)
    columns = [(names.get(player, "you"), series.get(key) or [], key)]
    for tag in data.get("compare") or []:
        if tag:
            columns.append((names.get(tag, tag), data["others"][tag].get(key) or [], key))
    return columns
