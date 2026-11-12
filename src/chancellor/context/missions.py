"""A country's mission tree with its progress (Phase 3).

Combines the save (which series a country has, which missions it completed) with the game
files (what each mission requires and rewards). Missions are classified as completed,
available (all prerequisites done) or locked, so the assistant can say what to work on
next and what the tree leads to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from chancellor.context.campaign import Campaign, as_list
from chancellor.context.script import clean_text, describe
from chancellor.game.missions import Mission, MissionLibrary

Status = Literal["completed", "available", "locked"]


@dataclass
class MissionState:
    """A mission and where the country stands on it.

    Attributes:
        mission: The mission definition.
        title: Localised title.
        status: Completed, available (prerequisites done) or locked.
        missing: Prerequisites not completed yet (only for locked missions).
    """

    mission: Mission
    title: str
    status: Status
    missing: list[str]


@dataclass
class MissionColumn:
    """One slot of the tree: the series assigned to it and their missions, top to bottom."""

    slot: int
    series: list[str]
    missions: list[MissionState]


@dataclass
class MissionTree:
    """A country's whole mission tree.

    Attributes:
        tag: Country tag.
        columns: Slots from left to right.
        unknown_series: Series named in the save but missing from the game files
            (e.g. from a mod that is no longer installed).
    """

    tag: str
    columns: list[MissionColumn]
    unknown_series: list[str]

    def count(self, status: Status) -> int:
        """Number of missions with the given status."""
        return sum(1 for c in self.columns for m in c.missions if m.status == status)

    @property
    def total(self) -> int:
        """Number of missions in the tree."""
        return sum(len(c.missions) for c in self.columns)


def mission_tree(campaign: Campaign, library: MissionLibrary, tag: str) -> MissionTree:
    """Build a country's mission tree with completion status.

    Args:
        campaign: The loaded save.
        library: Missions from the game files.
        tag: Country tag.

    Returns:
        The tree. It has no columns if the save records no missions for the country.

    Raises:
        KeyError: If the country is not in the save.
    """
    country = campaign.country(tag)
    if country is None:
        raise KeyError(f"{tag} is not in the save")
    completed = {str(m) for m in as_list(country.get("completed_missions"))}
    slots = (country.get("country_missions") or {}).get("mission_slot", [])

    columns = []
    unknown: list[str] = []
    for index, slot in enumerate(_slot_lists(slots), start=1):
        missions: list[Mission] = []
        for name in slot:
            series = library.series(name)
            if series is None:
                unknown.append(name)
                continue
            missions.extend(series.missions)
        missions.sort(key=lambda m: (m.position is None, m.position or 0))
        states = [_state(campaign, m, completed) for m in missions]
        columns.append(MissionColumn(slot=index, series=list(slot), missions=states))
    return MissionTree(tag=tag, columns=columns, unknown_series=unknown)


def render_missions(campaign: Campaign, tree: MissionTree, brief: bool = False) -> str:
    """Render a mission tree as Markdown.

    Completed missions take one line each. Available missions show their requirements
    and rewards; locked ones show what unlocks them and their rewards. With ``brief``,
    only titles and status are shown.
    """
    lines = [
        f"# Missions: {campaign.label(tree.tag)}, {campaign.date}",
        "",
    ]
    if not tree.columns:
        lines.append("The save records no mission tree for this country.")
        return "\n".join(lines) + "\n"

    lines += [
        f"{tree.count('completed')} of {tree.total} missions completed, "
        f"{tree.count('available')} available now, {tree.count('locked')} locked.",
        "",
        "Legend: [x] completed, [ ] available now (all prerequisites done), "
        "[-] locked (prerequisites missing).",
    ]
    titles = {m.mission.name: m.title for c in tree.columns for m in c.missions}

    for column in tree.columns:
        lines += ["", f"## Column {column.slot}", ""]
        if not column.missions:
            lines.append("No missions.")
            continue
        for state in column.missions:
            lines += _render_state(campaign, state, titles, brief)

    if tree.unknown_series:
        lines += [
            "",
            "Series not found in the game files (mods?): " + ", ".join(tree.unknown_series),
        ]
    return "\n".join(lines) + "\n"


# --- helpers ---------------------------------------------------------------------------


def _slot_lists(slots: object) -> list[list[str]]:
    """``mission_slot`` is repeated once per column; each holds one or more series."""
    result = []
    for slot in as_list(slots):
        result.append([str(s) for s in as_list(slot)])
    return result


def _state(campaign: Campaign, mission: Mission, completed: set[str]) -> MissionState:
    title = clean_text(campaign.loc.get(f"{mission.name}_title", ""), campaign)
    if mission.name in completed:
        status: Status = "completed"
        missing: list[str] = []
    else:
        missing = [r for r in mission.required if r not in completed]
        status = "locked" if missing else "available"
    return MissionState(
        mission=mission,
        title=title or mission.name.replace("_", " "),
        status=status,
        missing=missing,
    )


def _render_state(
    campaign: Campaign, state: MissionState, titles: dict[str, str], brief: bool
) -> list[str]:
    mark = {"completed": "[x]", "available": "[ ]", "locked": "[-]"}[state.status]
    name = f"{state.title} (`{state.mission.name}`)"
    if state.status == "completed":
        return [f"- {mark} {name}"]
    if state.status == "locked":
        after = ", ".join(titles.get(r, r) for r in state.missing)
        header = f"- {mark} {name}, after: {after}"
    else:
        header = f"- {mark} **{name}**, available now"
    if brief:
        return [header]

    lines = [header]
    if state.status == "available" and state.mission.trigger:
        lines.append("  - Requires:")
        lines += ["    " + line for line in describe(state.mission.trigger, campaign)]
    if state.mission.effect:
        lines.append("  - Rewards:")
        limit = 12 if state.status == "available" else 6
        lines += ["    " + line for line in describe(state.mission.effect, campaign, limit)]
    return lines
