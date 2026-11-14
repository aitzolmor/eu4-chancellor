"""Decisions and formable nations a country can see, with a requirement checklist.

Each decision's ``potential`` decides whether it is listed; its ``allow`` conditions
become a checklist marked met, not met or unknown (see :mod:`chancellor.context.conditions`
for what can be checked). Formable nations come first, because they are the backbone of
most long-term plans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign
from chancellor.context.conditions import Evaluator, Truth
from chancellor.context.script import clean_text, describe
from chancellor.game.decisions import Decision, DecisionLibrary
from chancellor.game.missions import MissionLibrary
from chancellor.game.modifiers import ModifierLibrary
from chancellor.game.rules import GameRules

# Lines per requirement in the checklist. A requirement that is not met (or not
# checkable) keeps every line: cutting it hid Austria-Hungary's only failing condition,
# an if/else on administrative technology.
_MET_LINES = 4
_UNMET_LINES = 40


@dataclass
class Requirement:
    """One top-level ``allow`` condition and whether it is met."""

    met: Truth
    lines: list[str]


@dataclass
class DecisionCheck:
    """A decision visible to a country and how close it is to taking it.

    Attributes:
        decision: The decision definition.
        title: Localised title.
        visible: ``True`` if the country certainly sees it, ``None`` if its visibility
            could not be fully checked.
        requirements: The ``allow`` checklist.
    """

    decision: Decision
    title: str
    visible: Truth
    requirements: list[Requirement] = field(default_factory=list)

    def count(self, met: Truth) -> int:
        """Number of requirements with the given state."""
        return sum(1 for r in self.requirements if r.met is met)

    @property
    def can_take(self) -> Truth:
        """Whether every requirement is met (``None`` if some are unknown)."""
        if self.count(False):
            return False
        return None if self.count(None) else True


def check_decisions(
    campaign: Campaign,
    rules: GameRules,
    library: DecisionLibrary,
    tag: str,
    missions: MissionLibrary | None = None,
    formables_only: bool = False,
) -> list[DecisionCheck]:
    """Decisions the country can see, each with its requirement checklist.

    Decisions whose visibility is certain are always included. Those whose visibility is
    unknown are included only if they are formable nations or major decisions, to keep
    estate and parliament actions with unsupported conditions out of the list.

    Args:
        campaign: The loaded save.
        rules: Game data used by the condition evaluator.
        library: Decisions from the game files.
        tag: Country tag.
        missions: Mission definitions, used for ``has_mission`` conditions.
        formables_only: Only list decisions that form a new nation.

    Returns:
        Formable nations first, then other decisions, closest to completion first.
    """
    evaluator = Evaluator(campaign, rules, tag, missions)
    checks = []
    for decision in library.decisions:
        if formables_only and not decision.forms:
            continue
        if decision.forms == tag:
            continue
        visible = evaluator.country(decision.potential)
        if visible is False:
            continue
        if visible is None and not (decision.forms or decision.major):
            continue
        requirements = [
            Requirement(
                met,
                describe(
                    value if key == "if" else {key: value},
                    campaign,
                    # Met requirements stay short; the ones to work on are shown whole.
                    _MET_LINES if met else _UNMET_LINES,
                    country=tag,
                ),
            )
            for met, key, value in evaluator.explain(decision.allow)
        ]
        title = clean_text(campaign.loc.get(f"{decision.name}_title", ""), campaign)
        checks.append(
            DecisionCheck(
                decision=decision,
                title=title or decision.name.replace("_", " "),
                visible=visible,
                requirements=requirements,
            )
        )

    def order(check: DecisionCheck) -> tuple[Any, ...]:
        total = len(check.requirements) or 1
        return (check.decision.forms is None, -check.count(True) / total, check.title)

    return sorted(checks, key=order)


def render_decisions(
    campaign: Campaign,
    tag: str,
    checks: list[DecisionCheck],
    modifiers: ModifierLibrary | None = None,
) -> str:
    """Render decision checks as Markdown."""
    lines = [f"# Decisions: {campaign.label(tag)}, {campaign.date}", ""]
    if not checks:
        lines.append("No decisions are available to this country right now.")
        return "\n".join(lines) + "\n"
    lines += [
        "Legend: [x] requirement met, [ ] not met, [?] could not be checked automatically "
        "(verify in game).",
    ]
    formables = [c for c in checks if c.decision.forms]
    others = [c for c in checks if not c.decision.forms]
    for heading, group in (("Formable nations", formables), ("Other decisions", others)):
        if not group:
            continue
        lines += ["", f"## {heading}", ""]
        for check in group:
            lines += _render_check(campaign, check, modifiers)
    lines += [
        "",
        "_Visibility marked 'may apply' could not be fully checked. Unchecked requirements "
        "are usually estate, parliament or map conditions._",
    ]
    return "\n".join(lines) + "\n"


def _render_check(
    campaign: Campaign, check: DecisionCheck, modifiers: ModifierLibrary | None
) -> list[str]:
    met, unmet, unknown = check.count(True), check.count(False), check.count(None)
    status = {True: "can be taken now", False: "not yet", None: "possibly"}[check.can_take]
    forms = f", forms {campaign.label(check.decision.forms)}" if check.decision.forms else ""
    maybe = " (may apply)" if check.visible is None else ""
    lines = [
        f"### {check.title}{forms}{maybe}",
        "",
        f"`{check.decision.name}`: {status}; {met} met, {unmet} not met"
        + (f", {unknown} unchecked" if unknown else "")
        + ".",
        "",
    ]
    mark = {True: "[x]", False: "[ ]", None: "[?]"}
    for requirement in check.requirements:
        if not requirement.lines:
            continue
        first, *rest = requirement.lines
        lines.append(f"- {mark[requirement.met]} {first[2:]}")
        lines += ["  " + line for line in rest]
    effect = describe(check.decision.effect, campaign, max_lines=6, modifiers=modifiers)
    if effect:
        lines += ["- Effect:", *("  " + line for line in effect)]
    lines.append("")
    return lines
