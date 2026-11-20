"""A country's mission tree with its progress (Phase 3).

Combines the save (which series a country has, which missions it completed) with the game
files (what each mission requires and rewards). Missions are classified as completed,
available (all prerequisites done) or locked, so the assistant can say what to work on
next and what the tree leads to.

With the game rules, each available mission's ``trigger`` is also evaluated against the
save (D-054), with the same three-valued evaluator as the decisions: every requirement
is met, not met or could not be checked, so the tree tells which missions can be
completed now and what the others still lack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from chancellor.context.campaign import Campaign, as_list
from chancellor.context.conditions import Evaluator, Truth
from chancellor.context.decisions import Requirement
from chancellor.context.script import clean_text, describe
from chancellor.game.missions import Mission, MissionLibrary
from chancellor.game.modifiers import ModifierLibrary
from chancellor.game.rules import GameRules

# Lines per requirement: met ones short, the ones still to do whole (as for decisions).
_MET_LINES = 4
_UNMET_LINES = 30

Status = Literal["completed", "available", "locked"]


@dataclass
class MissionState:
    """A mission and where the country stands on it.

    Attributes:
        mission: The mission definition.
        title: Localised title.
        status: Completed, available (prerequisites done) or locked.
        missing: Prerequisites not completed yet (only for locked missions).
        requirements: The trigger's checklist, for available missions when the game
            rules were given; empty otherwise.
    """

    mission: Mission
    title: str
    status: Status
    missing: list[str]
    requirements: list[Requirement] = field(default_factory=list)

    def count(self, met: Truth) -> int:
        """Number of requirements with the given state."""
        return sum(1 for r in self.requirements if r.met is met)

    @property
    def completable(self) -> Truth:
        """Whether an available mission can be completed now.

        ``None`` when its trigger was not checked, or some requirement could not be.
        """
        if self.status != "available" or not self.requirements:
            return None
        if self.count(False):
            return False
        return None if self.count(None) else True


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

    def available(self) -> list[MissionState]:
        """Available missions, left to right."""
        return [m for c in self.columns for m in c.missions if m.status == "available"]

    @property
    def total(self) -> int:
        """Number of missions in the tree."""
        return sum(len(c.missions) for c in self.columns)


def mission_tree(
    campaign: Campaign, library: MissionLibrary, tag: str, rules: GameRules | None = None
) -> MissionTree:
    """Build a country's mission tree with completion status.

    Args:
        campaign: The loaded save.
        library: Missions from the game files.
        tag: Country tag.
        rules: Game data for the condition evaluator; with it, each available mission's
            requirements are checked against the save.

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

    evaluator = Evaluator(campaign, rules, tag, library) if rules is not None else None
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
        states = [_state(campaign, m, completed, evaluator, tag) for m in missions]
        columns.append(MissionColumn(slot=index, series=list(slot), missions=states))
    return MissionTree(tag=tag, columns=columns, unknown_series=unknown)


def render_missions(
    campaign: Campaign,
    tree: MissionTree,
    brief: bool = False,
    modifiers: ModifierLibrary | None = None,
) -> str:
    """Render a mission tree as Markdown.

    Completed missions take one line each. Available missions show their requirements
    and rewards; locked ones show what unlocks them and their rewards. With ``brief``,
    only titles and status are shown. With ``modifiers``, granted modifiers list their
    bonuses.
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
        *_summary(tree),
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
            lines += _render_state(campaign, state, titles, brief, modifiers)

    if tree.unknown_series:
        lines += [
            "",
            "Series not found in the game files (mods?): " + ", ".join(tree.unknown_series),
        ]
    return "\n".join(lines) + "\n"


# --- helpers ---------------------------------------------------------------------------


def _summary(tree: MissionTree) -> list[str]:
    """Which available missions can be completed now, and which are one step away."""
    checked = [m for m in tree.available() if m.requirements]
    if not checked:
        return []
    ready = [m.title for m in checked if m.completable is True]
    close = [m.title for m in checked if m.count(False) == 1]
    maybe = [m.title for m in checked if m.completable is None]
    lines = ["", "Can be completed now: " + (", ".join(ready) if ready else "none") + "."]
    if close:
        lines.append("One requirement away: " + ", ".join(close) + ".")
    if maybe:
        lines.append(
            "Possibly (some requirements could not be checked, marked [?]): "
            + ", ".join(maybe)
            + "."
        )
    return lines


def _slot_lists(slots: object) -> list[list[str]]:
    """``mission_slot`` is repeated once per column; each holds one or more series."""
    result = []
    for slot in as_list(slots):
        result.append([str(s) for s in as_list(slot)])
    return result


def _state(
    campaign: Campaign,
    mission: Mission,
    completed: set[str],
    evaluator: Evaluator | None = None,
    tag: str | None = None,
) -> MissionState:
    title = clean_text(campaign.loc.get(f"{mission.name}_title", ""), campaign)
    if mission.name in completed:
        status: Status = "completed"
        missing: list[str] = []
    else:
        missing = [r for r in mission.required if r not in completed]
        status = "locked" if missing else "available"
    requirements = []
    if status == "available" and evaluator is not None and mission.trigger:
        requirements = [
            Requirement(
                met,
                describe(
                    value if key == "if" else {key: value},
                    campaign,
                    _MET_LINES if met else _UNMET_LINES,
                    country=tag,
                ),
            )
            for met, key, value in evaluator.explain(mission.trigger)
        ]
    return MissionState(
        mission=mission,
        title=title or mission.name.replace("_", " "),
        status=status,
        missing=missing,
        requirements=requirements,
    )


def _render_state(
    campaign: Campaign,
    state: MissionState,
    titles: dict[str, str],
    brief: bool,
    modifiers: ModifierLibrary | None,
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
    if state.requirements:
        met, unmet, unknown = state.count(True), state.count(False), state.count(None)
        verdict = {True: "can be completed now", False: "not yet", None: "possibly"}[
            state.completable
        ]
        lines.append(
            f"  - Requires ({verdict}; {met} met, {unmet} not met"
            + (f", {unknown} unchecked" if unknown else "")
            + "):"
        )
        mark = {True: "[x]", False: "[ ]", None: "[?]"}
        for requirement in state.requirements:
            if not requirement.lines:
                continue
            first, *rest = requirement.lines
            lines.append(f"    - {mark[requirement.met]} {first[2:]}")
            lines += ["      " + line for line in rest]
    elif state.status == "available" and state.mission.trigger:
        lines.append("  - Requires:")
        lines += [
            "    " + line for line in describe(state.mission.trigger, campaign, 12, modifiers)
        ]
    if state.mission.effect:
        lines.append("  - Rewards:")
        limit = 12 if state.status == "available" else 6
        lines += [
            "    " + line for line in describe(state.mission.effect, campaign, limit, modifiers)
        ]
    return lines
