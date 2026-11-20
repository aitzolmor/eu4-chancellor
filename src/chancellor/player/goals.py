"""Goal progress: a recorded goal tied to measures read from each save (D-061).

The player's goals are their own words ("next war: Gelre; then expand through the Low
Countries"). To show how far along they are, the model attaches measures to a goal, the
way it turns "tell me when" into a watch's conditions (D-041), from a closed list:

* ``mission``: a mission of the tree: done when completed; otherwise its requirements
  met, or whether it is available at all;
* ``formable``: a decision (usually forming a nation): its requirements met;
* ``provinces``: provinces held in an area, region or superregion, with the country's
  non-tributary subjects or not, against a number or the whole of it;
* ``country``: another country becoming the player's ``subject``, or ``gone`` (annexed
  or destroyed);
* ``metric``: any watch condition (:mod:`chancellor.player.watches`): development,
  income, war odds against a country, ...

Every measure is something the other tools already compute, so a goal's progress can be
checked against the mission tree, the decisions or a briefing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.player.watches import (
    Condition,
    WatchError,
    check,
    describe,
    show,
    validate_condition,
)
from chancellor.player.watches import Watch as _Watch

KINDS = ("mission", "formable", "provinces", "country", "metric")
COUNTRY_STATES = ("subject", "gone")
_NON_SOVEREIGN = {"tributary_state"}


class GoalError(ValueError):
    """A measure the goals cannot track (unknown kind, missing key, bad value)."""


@dataclass
class Measure:
    """One measure of a goal, as stored.

    Attributes:
        kind: One of :data:`KINDS`.
        key: A mission or decision key, a geography name, or a country (tag or name).
        count: For ``provinces``: how many are needed; 0 means all of them.
        subjects: For ``provinces``: whether the country's subjects' provinces count.
        state: For ``country``: ``subject`` or ``gone``.
        condition: For ``metric``: the watch condition, as a plain dict.
    """

    kind: str
    key: str = ""
    count: int = 0
    subjects: bool = True
    state: str = ""
    condition: dict[str, Any] = field(default_factory=dict)


@dataclass
class Progress:
    """A measure on the current save.

    Attributes:
        measure: The measure.
        text: What it stands at, in a short line.
        done: Whether it is reached (``None``: could not be read).
        share: How far, from 0 to 1, when it can be counted.
    """

    measure: Measure
    text: str
    done: bool | None
    share: float | None = None


def validate(raw: Any) -> Measure:
    """A measure from a tool call (countries still as given).

    Raises:
        GoalError: If the kind is unknown or a required field is missing or wrong.
    """
    if not isinstance(raw, dict):
        raise GoalError("Each measure is an object with a kind.")
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise GoalError(f"Unknown kind '{kind}'; use one of: {', '.join(KINDS)}.")
    key = str(raw.get("key") or "").strip()
    if kind == "metric":
        try:
            condition = validate_condition(raw.get("condition"))
        except WatchError as exc:
            raise GoalError(str(exc)) from exc
        return Measure("metric", condition=_condition_dict(condition))
    if not key:
        raise GoalError(f"A '{kind}' measure needs a key.")
    if kind == "provinces":
        count = raw.get("count", 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise GoalError("`count` is a whole number of provinces (0 for all of them).")
        return Measure("provinces", key, count=count, subjects=bool(raw.get("subjects", True)))
    if kind == "country":
        state = str(raw.get("state") or "").strip().lower()
        if state not in COUNTRY_STATES:
            raise GoalError(f"A country measure's state is one of: {', '.join(COUNTRY_STATES)}.")
        return Measure("country", key, state=state)
    return Measure(kind, key)


def to_dict(measure: Measure) -> dict[str, Any]:
    """Plain values for JSON, without the fields its kind does not use."""
    if measure.kind == "metric":
        return {"kind": "metric", "condition": measure.condition}
    data: dict[str, Any] = {"kind": measure.kind, "key": measure.key}
    if measure.kind == "provinces":
        data |= {"count": measure.count, "subjects": measure.subjects}
    if measure.kind == "country":
        data["state"] = measure.state
    return data


def from_dict(raw: dict[str, Any]) -> Measure | None:
    """A stored measure, or ``None`` if it no longer validates."""
    try:
        return validate(raw)
    except GoalError:
        return None


def progress(
    campaign: Campaign,
    measure: Measure,
    *,
    tag: str | None = None,
    missions: dict[str, Any] | None = None,
    decisions: dict[str, Any] | None = None,
    geography: dict[str, frozenset[int]] | None = None,
) -> Progress:
    """Where a measure stands on this save.

    Args:
        campaign: The loaded save.
        measure: The measure.
        tag: The country the goal is about; the player by default.
        missions: Mission key → its state in the tree (``MissionState``).
        decisions: Decision key → its checklist (``DecisionCheck``).
        geography: Area, region and superregion names → province ids.
    """
    tag = tag or campaign.player
    if measure.kind == "mission":
        return _mission(measure, (missions or {}).get(measure.key))
    if measure.kind == "formable":
        return _decision(measure, (decisions or {}).get(measure.key))
    if measure.kind == "provinces":
        return _provinces(campaign, measure, tag, geography or {})
    if measure.kind == "country":
        return _country(campaign, measure, tag)
    return _metric(campaign, measure)


def render(progress_list: list[Progress]) -> str:
    """One line for a goal's measures: "3 of 4 reached: ...; ..."."""
    reached = sum(1 for p in progress_list if p.done)
    parts = "; ".join(("✓ " if p.done else "") + p.text for p in progress_list)
    return f"{reached} of {len(progress_list)} reached: {parts}"


# --- kinds -----------------------------------------------------------------------------


def _mission(measure: Measure, state: Any) -> Progress:
    if state is None:
        return Progress(measure, f"mission {measure.key}: not in the country's tree", None)
    name = f"«{state.title}»"
    if state.status == "completed":
        return Progress(measure, f"{name} completed", True, 1.0)
    if state.status == "locked":
        return Progress(measure, f"{name} locked (earlier missions first)", False, 0.0)
    met, total = state.count(True), len(state.requirements)
    if state.completable is True:
        return Progress(measure, f"{name} can be completed now", False, 1.0)
    if not total:
        return Progress(measure, f"{name} available", False, None)
    return Progress(measure, f"{name}: {met} of {total} requirements met", False, met / total)


def _decision(measure: Measure, check: Any) -> Progress:
    if check is None:
        return Progress(measure, f"decision {measure.key}: not available to the country", None)
    met, total = check.count(True), len(check.requirements)
    name = f"«{check.title}»"
    if check.can_take is True:
        return Progress(measure, f"{name} can be taken now", True, 1.0)
    share = met / total if total else None
    return Progress(measure, f"{name}: {met} of {total} requirements met", False, share)


def _provinces(
    campaign: Campaign, measure: Measure, tag: str, geography: dict[str, frozenset[int]]
) -> Progress:
    provinces = geography.get(measure.key)
    name = campaign.loc.get(measure.key, measure.key.replace("_", " "))
    if not provinces:
        return Progress(measure, f"{name}: not an area, region or superregion", None)
    holders = {tag}
    if measure.subjects:
        holders |= {
            str(s)
            for s in as_list((campaign.country(tag) or {}).get("subjects"))
            if campaign.subject_type(tag, str(s)) not in _NON_SOVEREIGN
        }
    owners = campaign.province_owners
    held = sum(1 for p in provinces if owners.get(p) in holders)
    owned = [p for p in provinces if p in owners]  # wasteland and sea are never held
    needed = measure.count or len(owned)
    who = " with subjects" if measure.subjects else ""
    return Progress(
        measure,
        f"{name}: {held} of {needed} provinces{who}",
        held >= needed,
        min(held / needed, 1.0) if needed else None,
    )


def _country(campaign: Campaign, measure: Measure, tag: str) -> Progress:
    other = measure.key  # stored as a tag, so a country that is gone is still named
    name = campaign.name(other)
    if measure.state == "gone":
        gone = not campaign.exists(other)
        return Progress(measure, f"{name} {'is gone' if gone else 'still exists'}", gone)
    subject = (campaign.country(other) or {}).get("overlord") == tag
    return Progress(measure, f"{name} {'is' if subject else 'is not'} your subject", subject)


def _metric(campaign: Campaign, measure: Measure) -> Progress:
    condition = Condition(**measure.condition)
    (reading,) = check(campaign, _Watch(0, "", [condition]))
    return Progress(
        measure,
        f"{describe(condition, campaign)} (now {show(reading.value)})",
        reading.met if reading.value is not None else None,
    )


def _condition_dict(condition: Condition) -> dict[str, Any]:
    return {
        "metric": condition.metric,
        "op": condition.op,
        "value": condition.value,
        "country": condition.country,
        "other": condition.other,
    }
