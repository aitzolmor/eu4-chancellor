"""A country's mission tree with its progress (Phase 3).

Combines the save (which series a country has, which missions it completed) with the game
files (what each mission requires and rewards). Missions are classified as completed,
available (all prerequisites done) or locked, so the assistant can say what to work on
next and what the tree leads to.

With the game rules, each available mission's ``trigger`` is also evaluated against the
save (D-054), with the same three-valued evaluator as the decisions: every requirement
is met, not met or could not be checked, so the tree tells which missions can be
completed now and what the others still lack.

A reward can depend on a condition too ("if Poland has less than 300 development, a
casus belli to restore the union"), so a mission is sometimes better claimed later. The
conditions inside a reward, including those inside the scripted effects it calls, are
evaluated the same way and shown with the current value against the threshold (D-057).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from chancellor.context.campaign import Campaign, as_list
from chancellor.context.conditions import Evaluator, Truth, all_of
from chancellor.context.decisions import Requirement
from chancellor.context.script import clean_text, describe
from chancellor.game.missions import Mission, MissionLibrary
from chancellor.game.modifiers import ModifierLibrary
from chancellor.game.rules import GameRules
from chancellor.save.parser import parse

# Lines per requirement: met ones short, the ones still to do whole (as for decisions).
_MET_LINES = 4
_UNMET_LINES = 30
_ORDINALS = ("first", "second", "third", "fourth", "fifth")
# Numeric triggers whose current value is shown beside a reward condition's threshold.
_SHOWN_NUMBERS = {
    "total_own_and_non_tributary_subject_development": "development with its subjects",
    "total_development": "development",
    "num_of_cities": "provinces",
}


@dataclass
class RewardCondition:
    """A part of a mission's reward that only applies under a condition (D-057).

    Attributes:
        met: Whether the condition holds now (``None``: could not be checked).
        condition: The condition, described.
        reward: What it gives when it holds, described.
        now: Current values against the condition's thresholds ("Polonia: development
            with its subjects 695, needs less than 300").
    """

    met: Truth
    condition: list[str]
    reward: list[str]
    now: list[str] = field(default_factory=list)


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
    reward_conditions: list[RewardCondition] = field(default_factory=list)

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
    effects = rules.scripted_effects if rules is not None else {}
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
        states = [_state(campaign, m, completed, evaluator, tag, effects) for m in missions]
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
    effects: dict[str, dict] | None = None,
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
    conditions = []
    if status == "available" and evaluator is not None and tag is not None:
        conditions = reward_conditions(campaign, mission.effect, evaluator, tag, effects or {})
    return MissionState(
        mission=mission,
        title=title or mission.name.replace("_", " "),
        status=status,
        missing=missing,
        requirements=requirements,
        reward_conditions=conditions,
    )


def reward_conditions(
    campaign: Campaign,
    effect: dict,
    evaluator: Evaluator,
    tag: str,
    effects: dict[str, dict],
) -> list[RewardCondition]:
    """The conditional parts of a reward, innermost condition first.

    Walks ``if``/``else_if`` blocks, ``complex_dynamic_effect`` branches, hidden effects
    and the scripted effects the reward calls. A branch that only wraps further branches
    is not listed itself: the inner ones hold the conditions that decide (the Austrian
    Poland mission shows "less than 400" but grants the casus belli below 300). Branches
    about a country that does not exist are left out, and so are conditions without a
    number the player can move (a DLC, the age, the religion): only a threshold with its
    current value says whether waiting could change the reward.
    """
    found: list[RewardCondition] = []

    def walk(block: object, outer: list[dict], depth: int) -> bool:
        """Collect branches in ``block``; returns whether it held any."""
        if not isinstance(block, dict) or depth > 6:
            return False
        held = False
        for key, value in block.items():
            items = value if isinstance(value, list) else [value]
            for item in items:
                if key in ("if", "else_if") and isinstance(item, dict):
                    limit = item.get("limit")
                    body = {k: v for k, v in item.items() if k != "limit"}
                    if isinstance(limit, dict):
                        held = True
                        if not walk(body, [*outer, limit], depth + 1):
                            add([*outer, limit], body)
                elif key == "complex_dynamic_effect" and isinstance(item, dict):
                    for ordinal in _ORDINALS:
                        limit = _script(item.get(f"{ordinal}_limit"))
                        body = _script(item.get(f"{ordinal}_effect"))
                        if limit:
                            held = True
                            if not walk(body, [*outer, limit], depth + 1):
                                add([*outer, limit], body)
                elif key == "hidden_effect":
                    held = walk(item, outer, depth + 1) or held
                elif item is True and key in effects:
                    held = walk(effects[key], outer, depth + 1) or held
        return held

    def add(limits: list[dict], body: dict) -> None:
        inner = limits[-1]
        gone = [t for t in _items(inner.get("exists")) if isinstance(t, str)]
        if any(not campaign.exists(t) for t in gone):
            return
        now = _now(campaign, inner, evaluator, tag)
        if not now:
            return
        found.append(
            RewardCondition(
                met=all_of(evaluator.country(limit, tag) for limit in limits),
                condition=describe(inner, campaign, 6, country=tag),
                reward=describe(body, campaign, 6, country=tag),
                now=now,
            )
        )

    walk(effect, [], 0)
    return found


def one_line(lines: list[str], limit: int = 160) -> str:
    """Described script on one line: "add_casus_belli: type: X; target: Y"."""
    parts = [line.strip().removeprefix("- ").rstrip(":") for line in lines if line.strip()]
    if not parts:
        return ""
    text = parts[0] + (": " + "; ".join(parts[1:]) if len(parts) > 1 else "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _script(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and "=" in value:
        parsed = parse(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else [value]


def _now(campaign: Campaign, limit: dict, evaluator: Evaluator, tag: str) -> list[str]:
    """Current values of the numeric triggers in a condition, with their thresholds."""
    lines: list[str] = []

    def walk(block: object, scope: str, negated: bool) -> None:
        if not isinstance(block, dict):
            return
        for key, value in block.items():
            for item in _items(value):
                if key in _SHOWN_NUMBERS and isinstance(item, int | float):
                    current = evaluator.number(key, scope)
                    if current is not None:
                        need = f"less than {item:g}" if negated else f"{item:g} or more"
                        lines.append(
                            f"{campaign.name(scope)}: {_SHOWN_NUMBERS[key]} {current:.0f}, "
                            f"needs {need}"
                        )
                elif key == "NOT":
                    walk(item, scope, not negated)
                elif len(key) == 3 and key.isupper() and isinstance(item, dict):
                    walk(item, key, negated)
                elif isinstance(item, dict):
                    walk(item, scope, negated)

    walk(limit, tag, False)
    return lines


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
    if state.reward_conditions:
        lines.append("  - The reward depends on conditions (it may pay to claim it later):")
        mark = {True: "[x]", False: "[ ]", None: "[?]"}
        for condition in state.reward_conditions:
            first, *rest = condition.condition or ["- (condition)"]
            lines.append(f"    - {mark[condition.met]} If {first[2:]}")
            lines += ["      " + line for line in rest]
            lines += [f"      - Now: {value}" for value in condition.now]
            lines.append("      - Then: " + one_line(condition.reward))
    if state.mission.effect:
        lines.append("  - Rewards:")
        limit = 12 if state.status == "available" else 6
        lines += [
            "    " + line for line in describe(state.mission.effect, campaign, limit, modifiers)
        ]
    return lines
