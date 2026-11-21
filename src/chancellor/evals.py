"""An evaluation set: real questions, the tool that answers each, and what it must say (D-058).

Each case is a question the player asked or would ask, the tool the model should call
for it, and checks on that tool's output: text it must contain, text it must not, and
patterns it must match. The checks use keys, tags and numbers (``hab_milan``, ``(POL)``,
``695``), not localised names, so they hold whatever the game's language.

Cases are tied to one save of the player's campaign, named in the file. Saves are never
committed (CLAUDE.md), so the set runs where that save exists: on the developer's
machine, by ``chancellor eval`` or ``pytest``; elsewhere it is skipped. The facts in a set
were checked against the game when it was written, so a failure means a tool changed what
it says about a save that did not change.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"


class Runner(Protocol):
    """What runs a tool: :class:`chancellor.context.tools.Toolbox` in practice."""

    def run(self, name: str, args: dict[str, Any]) -> str: ...  # noqa: D102


@dataclass
class Case:
    """One question and what the answer must hold.

    Attributes:
        id: Short name, unique in its set.
        question: The question, as the player would ask it.
        tool: The tool that answers it.
        args: The tool's input.
        contains: Text the output must contain.
        absent: Text the output must not contain.
        matches: Regular expressions the output must match (multi-line).
        answer: Facts a model's answer should mention (numbers, keys), for
            :func:`run_model_eval` (D-062).
        why: Where the expected facts come from (the game screen, a past bug).
    """

    id: str
    question: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    contains: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)
    answer: list[str] = field(default_factory=list)
    why: str = ""


@dataclass
class EvalSet:
    """Cases tied to one save.

    Attributes:
        name: The set's name (its file name).
        save: The save's file name in the player's save folder.
        player: The player's tag on it.
        date: Its in-game date.
        cases: The questions.
    """

    name: str
    save: str
    player: str
    date: str
    cases: list[Case]


@dataclass
class Result:
    """How one case went."""

    case: Case
    failures: list[str]

    @property
    def passed(self) -> bool:
        """Whether every check held."""
        return not self.failures


def load_eval(path: Path) -> EvalSet:
    """Read a set from a TOML file.

    Raises:
        ValueError: If a case is missing a field or two cases share an id.
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    save = data.get("save") or {}
    cases = []
    for raw in data.get("case", []):
        missing = [k for k in ("id", "question", "tool") if k not in raw]
        if missing:
            raise ValueError(f"{path.name}: a case lacks {', '.join(missing)}")
        cases.append(
            Case(
                id=raw["id"],
                question=raw["question"],
                tool=raw["tool"],
                args=dict(raw.get("args", {})),
                contains=list(raw.get("contains", [])),
                absent=list(raw.get("absent", [])),
                matches=list(raw.get("matches", [])),
                answer=list(raw.get("answer", [])),
                why=raw.get("why", ""),
            )
        )
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: case ids repeat")
    return EvalSet(
        path.stem, save.get("file", ""), save.get("player", ""), save.get("date", ""), cases
    )


def eval_files(folder: Path = EVALS_DIR) -> list[Path]:
    """The sets in a folder, by name."""
    return sorted(folder.glob("*.toml")) if folder.is_dir() else []


def check(case: Case, output: str) -> list[str]:
    """What a tool's output gets wrong for a case (empty when it passes)."""
    failures = [f"missing: {text!r}" for text in case.contains if text not in output]
    failures += [f"should not say: {text!r}" for text in case.absent if text in output]
    failures += [
        f"no match for: {pattern!r}"
        for pattern in case.matches
        if not re.search(pattern, output, re.MULTILINE)
    ]
    return failures


def run_eval(evalset: EvalSet, runner: Runner) -> list[Result]:
    """Run every case, calling each tool once per distinct input."""
    outputs: dict[tuple[str, str], str] = {}
    results = []
    for case in evalset.cases:
        key = (case.tool, repr(sorted(case.args.items())))
        if key not in outputs:
            try:
                outputs[key] = runner.run(case.tool, case.args)
            except Exception as exc:  # noqa: BLE001 - a crashing tool is a failed case
                outputs[key] = f"ERROR {exc.__class__.__name__}: {exc}"
        output = outputs[key]
        failures = [output] if output.startswith("ERROR ") else check(case, output)
        results.append(Result(case, failures))
    return results


def render_results(evalset: EvalSet, results: list[Result]) -> str:
    """A short report: one line per case, the failures under it."""
    passed = sum(1 for r in results if r.passed)
    lines = [
        f"# Eval {evalset.name}: {passed} of {len(results)} passed "
        f"({evalset.save}, {evalset.player} {evalset.date})",
        "",
    ]
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        lines.append(f"- {mark} {result.case.id} ({result.case.tool}): {result.case.question}")
        lines += [f"    - {failure}" for failure in result.failures]
    return "\n".join(lines) + "\n"


@dataclass
class ModelResult:
    """How a model answered one case (D-062).

    Attributes:
        case: The case.
        tools: The tools the model called.
        answer: Its answer.
        seconds: How long it took.
        cut: Whether a tool result was shortened to fit its context.
        error: What failed, if anything.
    """

    case: Case
    tools: list[str]
    answer: str
    seconds: float
    cut: bool = False
    error: str = ""

    @property
    def right_tool(self) -> bool:
        """Whether it called the tool the case is about."""
        return self.case.tool in self.tools

    @property
    def missing(self) -> list[str]:
        """Facts the answer should mention but does not (decimal commas allowed)."""
        text = self.answer.replace(",", ".")
        return [fact for fact in self.case.answer if fact.replace(",", ".") not in text]


def run_model_eval(
    evalset: EvalSet,
    ask: Any,
    ids: list[str] | None = None,
    progress: Any = None,
) -> list[ModelResult]:
    """Ask a model each case's question (or those in ``ids``) and record what it did.

    Args:
        evalset: The set.
        ask: ``question -> chancellor.llm.local.Answer``.
        ids: Case ids to ask; all by default.
        progress: Called with each result as it comes, for a long run.
    """
    results = []
    for case in evalset.cases:
        if ids and case.id not in ids:
            continue
        reply = ask(case.question)
        result = ModelResult(case, reply.tools, reply.text, reply.seconds, reply.cut, reply.error)
        results.append(result)
        if progress:
            progress(result)
    return results


def render_model_results(evalset: EvalSet, model: str, results: list[ModelResult]) -> str:
    """A report of a model's run: right tool, facts mentioned, time, per case."""
    right = sum(1 for r in results if r.right_tool)
    complete = sum(1 for r in results if r.right_tool and not r.missing and not r.error)
    total = sum(r.seconds for r in results)
    lines = [
        f"# Eval {evalset.name} with {model}: right tool {right} of {len(results)}, "
        f"full answer {complete} of {len(results)}, {total / 60:.1f} minutes",
        "",
    ]
    for r in results:
        mark = "PASS" if r.right_tool and not r.missing and not r.error else "FAIL"
        tools = ", ".join(r.tools) or "no tool"
        lines.append(f"- {mark} {r.case.id} ({r.seconds:.0f} s): called {tools}")
        if not r.right_tool:
            lines.append(f"    - expected {r.case.tool}")
        if r.missing:
            lines.append(f"    - answer lacks: {', '.join(r.missing)}")
        if r.cut:
            lines.append("    - a tool result was cut to fit the context")
        if r.error:
            lines.append(f"    - error: {r.error}")
        preview = " ".join(r.answer.split())[:240]
        if preview:
            lines.append(f"    - answer: {preview}")
    return "\n".join(lines) + "\n"


def open_save(
    evalset: EvalSet,
    save_dir: Path | None,
    game_dir: Path | None,
    language: str,
    work_dir: Path,
) -> Runner | None:
    """Tools bound to a set's save, or ``None`` when the save is not on this machine.

    The tools get an empty player context in ``work_dir``, so the answers depend on the
    save alone, not on goals recorded since.
    """
    from chancellor.context.campaign import Campaign  # deferred: heavy imports
    from chancellor.context.tools import Toolbox
    from chancellor.game.localisation import Localisation
    from chancellor.save.loader import load_save

    if save_dir is None or not evalset.save or not (save_dir / evalset.save).is_file():
        return None
    loc = Localisation.load(game_dir, language) if game_dir is not None else Localisation()
    campaign = Campaign.from_raw(load_save(save_dir / evalset.save), loc)
    return Toolbox(campaign, game_dir, work_dir / "player_context.json")
