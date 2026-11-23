"""Act: prepare one action for Claude Desktop's computer use, then check it in the save.

The third rung of the vision's ladder (Advise, Guide, Act; D-069). The clicking is done by
Claude Desktop's own computer use, at no API cost; the Chancellor does what a screenshot
cannot:

* **before**, :func:`prepare` checks the action against the save (is the mission still
  open and complete, is there power or money enough), gives the steps in the game's own
  words (:mod:`chancellor.context.guide`), marks the click that cannot be undone, and
  records what the save should show afterwards;
* **after**, :func:`verify` reads the newest save and says whether that happened.

Only actions that are one click sequence and that the save can confirm are supported.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.context.guide import steps as guide_steps
from chancellor.context.guide import ui
from chancellor.save.parser import get_all

ACTIONS_FILE = "actions.json"
KEPT = 20  # actions remembered

# Kinds of recommendation (D-056) that can be carried out and checked in the save.
SUPPORTED = (
    "complete_mission",
    "form_nation",
    "buy_technology",
    "buy_idea",
    "raise_stability",
    "repay_loan",
    "core_province",
    "declare_war",
)

RULES = (
    "Act only because the player asked for this action in this chat, and do one action.",
    "Pause the game first (Space) and keep it paused; take a screenshot before every "
    "click and check it matches the step.",
    "Stay inside the Europa Universalis IV window: never click the launcher, Steam, "
    "Windows dialogs or other programs, never open the console, never change settings.",
    "Before the step marked CONFIRM, stop and ask the player in the chat; click it only "
    "after they say yes.",
    "If the screen differs from the step (another window, a different button, a "
    "warning), stop and describe what you see instead of improvising.",
    "When done, ask the player to save the game (or wait for the autosave), then call "
    "verify_action.",
    "If clicks have no effect in the game, EU4 is probably running as administrator: "
    "Windows ignores clicks from programs that are not. Tell the player to start Claude "
    "Desktop as administrator too, or EU4 without it.",
)


class ActionError(ValueError):
    """The action cannot be prepared (unsupported, or the save rules it out)."""


@dataclass
class Action:
    """A prepared action and what the save should show once it is done.

    Attributes:
        id: Number, unique in the file.
        kind: The recommendation kind (``buy_technology``, ...).
        target: Its target (a mission key, ``adm``, a province id, a tag...).
        title: The action in one line.
        tag: The country acting.
        prepared_on: The save date it was prepared against.
        before: The values the check compares with.
        status: ``prepared``, ``done`` or ``not_done``.
        checked_on: The save date of the last check, if any.
    """

    id: int
    kind: str
    target: str | None
    title: str
    tag: str
    prepared_on: str
    before: dict[str, Any] = field(default_factory=dict)
    status: str = "prepared"
    checked_on: str | None = None


@dataclass
class Prepared:
    """What :func:`prepare` found: the action, the checks and the steps."""

    action: Action
    checks: list[tuple[bool, str]]
    steps: list[str]

    @property
    def possible(self) -> bool:
        """Whether every check passed (only then is the action recorded)."""
        return all(ok for ok, _ in self.checks)


def actions_path(context_file: Path) -> Path:
    """Where prepared actions are kept: beside the player's context file."""
    return context_file.parent / ACTIONS_FILE


class ActionStore:
    """The prepared actions, newest last, in a small JSON file."""

    def __init__(self, path: Path) -> None:
        """Bind the store to its file (created on the first write)."""
        self.path = path

    def all(self) -> list[Action]:
        """Every remembered action (an unreadable file counts as empty)."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [Action(**item) for item in raw if isinstance(item, dict)]

    def add(self, action: Action) -> Action:
        """Remember a new action, giving it the next id."""
        actions = self.all()
        action.id = max((a.id for a in actions), default=0) + 1
        self._write([*actions, action][-KEPT:])
        return action

    def update(self, action: Action) -> None:
        """Store a changed action."""
        self._write([action if a.id == action.id else a for a in self.all()])

    def _write(self, actions: list[Action]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps([asdict(a) for a in actions], indent=1), encoding="utf-8")
        temporary.replace(self.path)


def prepare(
    campaign: Campaign,
    kind: str,
    target: str | None,
    *,
    ready_missions: list[str] | None = None,
    ready_formables: list[str] | None = None,
    forms: str | None = None,
    tech_cost: int | None = None,
    idea_cost: int | None = None,
    stability_cost: int | None = None,
    core_cost: int | None = None,
) -> Prepared:
    """Check an action against the save and work out how to confirm it later.

    Args:
        campaign: The loaded save; the player acts.
        kind: One of :data:`SUPPORTED`.
        target: The recommendation's target.
        ready_missions: Missions whose requirements are all met (for ``complete_mission``).
        ready_formables: Formable decisions whose requirements are met (``form_nation``).
        forms: The tag the formable decision creates.
        tech_cost: Cost of the next technology of ``target``'s category.
        idea_cost: Cost of the next idea.
        stability_cost: Cost of one point of stability.
        core_cost: Cost of coring the target province.

    Raises:
        ActionError: If the kind is not supported or a required target is missing.
    """
    if kind not in SUPPORTED:
        raise ActionError(
            f"{kind!r} cannot be carried out automatically; supported: {', '.join(SUPPORTED)}. "
            "Give the player the steps from get_recommendations instead."
        )
    tag = campaign.player
    country = campaign.country(tag) or {}
    powers = [int(p) for p in as_list(country.get("powers")) if isinstance(p, int | float)]
    adm = powers[0] if len(powers) == 3 else None
    checks: list[tuple[bool, str]] = []
    before: dict[str, Any] = {}

    def need(value: Any, name: str) -> str:
        if value is None:
            raise ActionError(f"{kind} needs a target: {name}.")
        return str(value)

    if kind == "complete_mission":
        mission = need(target, "the mission key")
        done = mission in as_list(country.get("completed_missions"))
        checks.append((not done, "the mission is not completed yet"))
        if ready_missions is not None:
            checks.append((mission in ready_missions, "every requirement of the mission is met"))
        before["missions"] = len(as_list(country.get("completed_missions")))
        title = f"Complete the mission {mission}"
    elif kind == "form_nation":
        decision = need(target, "the decision key")
        if ready_formables is not None:
            checks.append((decision in ready_formables, "every requirement is met"))
        before["forms"] = forms
        title = f"Form {campaign.name(forms) if forms else decision}"
    elif kind == "buy_technology":
        category = need(target, "adm, dip or mil")
        if category not in ("adm", "dip", "mil"):
            raise ActionError("buy_technology takes adm, dip or mil.")
        level = int((country.get("technology") or {}).get(f"{category}_tech", 0) or 0)
        points = powers[("adm", "dip", "mil").index(category)] if len(powers) == 3 else None
        if tech_cost is not None and points is not None:
            checks.append((points >= tech_cost, f"{points} points for a cost of about {tech_cost}"))
        before["level"] = level
        title = f"Buy {ui(campaign, category)} {level + 1}"
    elif kind == "buy_idea":
        taken = _ideas(country)
        if idea_cost is not None and len(powers) == 3:
            checks.append(
                (
                    max(powers) >= idea_cost,
                    f"an idea costs {idea_cost} points of its group's category; the most "
                    f"held in one category is {max(powers)}",
                )
            )
        before["ideas"] = taken
        title = "Buy the next idea"
    elif kind == "raise_stability":
        stability = float(country.get("stability") or 0.0)
        checks.append((stability < 3, f"stability is {stability:+.0f} (the most is +3)"))
        if stability_cost is not None and adm is not None:
            checks.append((adm >= stability_cost, f"{adm} adm points for {stability_cost}"))
        before["stability"] = stability
        title = "Raise stability by one"
    elif kind == "repay_loan":
        loans = [loan for loan in get_all(country, "loan") if isinstance(loan, dict)]
        treasury = float(country.get("treasury") or 0.0)
        smallest = min((float(loan.get("amount", 0) or 0) for loan in loans), default=None)
        checks.append((bool(loans), f"{len(loans)} loans"))
        if smallest is not None:
            checks.append(
                (treasury >= smallest, f"{treasury:.0f} ducats for a {smallest:.0f} loan")
            )
        before["loans"] = len(loans)
        title = "Repay a loan"
    elif kind == "core_province":
        province = need(target, "the province id")
        data = campaign.province(province) or {}
        checks.append((data.get("owner") == tag, "the province is yours"))
        checks.append((tag not in as_list(data.get("cores")), "it is not a core yet"))
        if core_cost is not None and adm is not None:
            checks.append((adm >= core_cost, f"{adm} adm points for {core_cost}"))
        before |= {"province": int(province), "adm": adm, "cost": core_cost}
        title = f"Core {data.get('name') or campaign.loc.province(province)}"
    else:  # declare_war
        enemy = need(target, "the country tag")
        checks.append((campaign.exists(enemy), f"{campaign.name(enemy)} exists"))
        checks.append((not _at_war(campaign, tag, enemy), "you are not already at war with it"))
        truce = campaign.truce(tag, enemy)
        checks.append((truce is None, "no truce with it" if truce is None else "a truce holds"))
        title = f"Declare war on {campaign.name(enemy)}"

    action = Action(0, kind, target, title, tag, campaign.date, before)
    steps = guide_steps(campaign, kind, target)
    return Prepared(action, checks, steps)


def verify(campaign: Campaign, action: Action) -> tuple[bool | None, str]:
    """Whether the newest save shows the action done.

    Returns:
        ``(True, why)`` done, ``(False, why)`` not done in this save, ``(None, why)`` when
        the save is not newer than the one the action was prepared against.
    """
    if _date_key(campaign.date) <= _date_key(action.prepared_on):
        return None, (
            f"The newest save ({campaign.date}) is not later than the one the action was "
            f"prepared against ({action.prepared_on}): ask the player to save the game"
        )
    tag = campaign.player
    country = campaign.country(tag) or {}
    before = action.before
    if action.kind == "complete_mission":
        done = action.target in as_list(country.get("completed_missions"))
        return done, "the mission is completed" if done else "the mission is not completed"
    if action.kind == "form_nation":
        done = bool(before.get("forms")) and tag == before.get("forms")
        return done, f"the player's country is now {campaign.label(tag)}"
    if action.kind == "buy_technology":
        level = int((country.get("technology") or {}).get(f"{action.target}_tech", 0) or 0)
        done = level > int(before.get("level", 0))
        return done, f"{action.target} technology {before.get('level')} → {level}"
    if action.kind == "buy_idea":
        taken = _ideas(country)
        return taken > int(before.get("ideas", 0)), f"ideas taken {before.get('ideas')} → {taken}"
    if action.kind == "raise_stability":
        stability = float(country.get("stability") or 0.0)
        done = stability > float(before.get("stability", 0.0))
        return done, f"stability {before.get('stability'):+.0f} → {stability:+.0f}"
    if action.kind == "repay_loan":
        loans = sum(1 for loan in get_all(country, "loan") if isinstance(loan, dict))
        return loans < int(before.get("loans", 0)), f"loans {before.get('loans')} → {loans}"
    if action.kind == "core_province":
        data = campaign.province(int(before.get("province", 0))) or {}
        if tag in as_list(data.get("cores")):
            return True, "the province is a core"
        # Coring takes months; spent power is the sign it started.
        powers = [int(p) for p in as_list(country.get("powers")) if isinstance(p, int | float)]
        adm, cost = (powers[0] if len(powers) == 3 else None), before.get("cost")
        started = before.get("adm")
        if adm is not None and started is not None and cost and started - adm >= cost * 0.9:
            return True, f"adm power fell {started} → {adm}: coring has started"
        return False, "no core, and no adm power spent on it"
    done = _at_war(campaign, tag, str(action.target))
    return done, "at war with it" if done else "not at war with it"


def render_prepared(campaign: Campaign, prepared: Prepared) -> str:
    """Markdown for ``prepare_action``: checks, numbered steps and the rules."""
    action = prepared.action
    heading = f"Action #{action.id}" if prepared.possible else "Not possible now"
    lines = [f"# {heading}: {action.title}", ""]
    for ok, text in prepared.checks:
        lines.append(f"- [{'x' if ok else ' '}] {text}")
    if not prepared.possible:
        lines += [
            "",
            "**Do not carry it out**: the save rules it out (unchecked above). Tell the player "
            f"why; the save is from {campaign.date}, so it may have changed since. Nothing "
            "was recorded to verify.",
        ]
        return "\n".join(lines) + "\n"
    lines += ["", "## Steps in the game", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(_with_pause(prepared.steps), 1)]
    lines += ["", "## Rules for acting", ""]
    lines += [f"- {rule}" for rule in RULES]
    lines += [
        "",
        f"_Prepared against the save of {campaign.date}. After the player saves, "
        f"verify_action (id {action.id}) reads the new save and says whether it is done._",
    ]
    return "\n".join(lines) + "\n"


def render_verified(campaign: Campaign, action: Action, result: tuple[bool | None, str]) -> str:
    """Markdown for ``verify_action``."""
    done, why = result
    verdict = {True: "Done", False: "Not done", None: "Cannot tell yet"}[done]
    return (
        f"# Action #{action.id}: {action.title}\n\n"
        f"**{verdict}** (save of {campaign.date}): {why}.\n"
    )


def _with_pause(steps: list[str]) -> list[str]:
    """Pause first; the last step is the one that spends, declares or claims: confirm it."""
    if not steps:
        return ["Pause the game (Space)."]
    return ["Pause the game (Space).", *steps[:-1], f"CONFIRM with the player, then {steps[-1]}"]


def _ideas(country: dict[str, Any]) -> int:
    """Ideas taken in every group, national ideas included: buying one raises the sum."""
    groups = country.get("active_idea_groups") or {}
    return sum(int(v) for v in groups.values() if isinstance(v, int))


def _at_war(campaign: Campaign, tag: str, enemy: str) -> bool:
    for war in campaign.wars_of(tag):
        sides = [as_list(war.get("attackers")), as_list(war.get("defenders"))]
        for mine, theirs in (sides, sides[::-1]):
            if tag in mine and enemy in theirs:
                return True
    return False


def _date_key(date: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in date.split("."))
    except ValueError:
        return (0,)
