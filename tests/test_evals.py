"""The evaluation set's runner, and the set itself when its save is here (D-058)."""

from pathlib import Path
from typing import Any

import pytest

from chancellor.config import load_settings
from chancellor.evals import (
    Case,
    EvalSet,
    check,
    eval_files,
    load_eval,
    open_save,
    render_results,
    run_eval,
)

SET = """
[save]
file = "Austria1535_08_02.eu4"
player = "HAB"
date = "1535.8.2"

[[case]]
id = "ready"
question = "What can I complete?"
tool = "get_missions"
contains = ["hab_milan"]
absent = ["ERROR"]
matches = ['^- \\[ \\] \\*\\*Ducado']

[[case]]
id = "budget"
question = "Where does my money go?"
tool = "get_budget"
args = { country = "HAB" }
contains = ["Army maintenance"]
"""


class FakeTools:
    """Answers each tool with fixed text and counts the calls."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, name: str, args: dict[str, Any]) -> str:
        self.calls.append((name, args))
        if name not in self.answers:
            raise KeyError(name)
        return self.answers[name]


def _set(tmp_path: Path, text: str = SET) -> EvalSet:
    path = tmp_path / "campaign.toml"
    path.write_text(text, encoding="utf-8")
    return load_eval(path)


def test_a_set_is_read_from_toml(tmp_path: Path):
    evalset = _set(tmp_path)
    assert (evalset.name, evalset.save, evalset.player, evalset.date) == (
        "campaign",
        "Austria1535_08_02.eu4",
        "HAB",
        "1535.8.2",
    )
    assert [c.id for c in evalset.cases] == ["ready", "budget"]
    assert evalset.cases[1].args == {"country": "HAB"}
    with pytest.raises(ValueError, match="repeat"):
        _set(tmp_path, SET.replace('id = "budget"', 'id = "ready"'))
    with pytest.raises(ValueError, match="lacks tool"):
        _set(tmp_path, '[[case]]\nid = "x"\nquestion = "y"\n')


def test_checks_name_what_is_wrong():
    case = Case("c", "q", "t", contains=["a", "b"], absent=["x"], matches=[r"^\d+$"])
    assert check(case, "a\nb\n42") == []
    assert check(case, "a x") == [
        "missing: 'b'",
        "should not say: 'x'",
        "no match for: '^\\\\d+$'",
    ]


def test_each_tool_runs_once_and_a_crash_fails_its_case(tmp_path: Path):
    evalset = _set(tmp_path)
    evalset.cases.append(Case("again", "q", "get_missions", contains=["hab_milan"]))
    evalset.cases.append(Case("broken", "q", "get_wars"))
    tools = FakeTools({"get_missions": "- [ ] **Ducado (`hab_milan`)**", "get_budget": "Rent"})
    results = run_eval(evalset, tools)
    assert [r.passed for r in results] == [True, False, True, False]
    assert [name for name, _ in tools.calls] == ["get_missions", "get_budget", "get_wars"]
    assert results[3].failures[0].startswith("ERROR KeyError")
    report = render_results(evalset, results)
    assert report.startswith("# Eval campaign: 2 of 4 passed")
    assert (
        "- FAIL budget (get_budget): Where does my money go?\n    - missing: 'Army maintenance'"
        in (report)
    )


def test_without_the_save_nothing_runs(tmp_path: Path):
    evalset = _set(tmp_path)
    assert open_save(evalset, None, None, "english", tmp_path) is None
    assert open_save(evalset, tmp_path, None, "english", tmp_path) is None


@pytest.fixture(scope="module")
def real_save(tmp_path_factory):
    """The first set's save, opened once for this module, or ``None`` when it is absent.

    It uses the real game-data cache (the tests' own is empty), which makes it much faster.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("CHANCELLOR_CACHE_DIR", raising=False)
        patch.delenv("CHANCELLOR_CONFIG", raising=False)
        settings = load_settings()  # the local .env or the user's config
        files = eval_files()
        if not files:
            yield None, None, settings
            return
        evalset = load_eval(files[0])
        work = tmp_path_factory.mktemp("eval")
        runner = open_save(
            evalset, settings.save_dir, settings.game_dir, settings.language or "spanish", work
        )
        yield evalset, runner, settings


def test_the_evaluation_set(real_save, monkeypatch):
    """Run the committed set against its save, where that save exists (the developer's PC)."""
    monkeypatch.delenv("CHANCELLOR_CACHE_DIR")  # the real game-data cache: much faster
    evalset, runner, _ = real_save
    if runner is None:
        pytest.skip("the evaluation save is not on this machine")
    results = run_eval(evalset, runner)
    failed = [r for r in results if not r.passed]
    assert not failed, render_results(evalset, results)


# --- any country, not just the one being played (the user's requirement) ---------------

ODD = ("Traceback", " None", "{}", "Series not found")
TOOLS = (
    "get_country_briefing",
    "get_missions",
    "get_decisions",
    "get_budget",
    "get_expansion_targets",
    "get_wars",
    "get_trade",
    "get_recommendations",
)


def _as_player(campaign, tag: str):
    """The same save as if ``tag`` were the player."""
    from chancellor.context.campaign import Campaign

    return Campaign({**campaign.meta, "player": tag}, campaign.gamestate, campaign.loc)


@pytest.mark.parametrize("tag", ["TUR", "BOH", "HUN"])
def test_the_tools_answer_for_any_player_without_game_files(tag: str, tmp_path: Path):
    from chancellor.context.campaign import Campaign
    from chancellor.context.tools import Toolbox
    from chancellor.save.loader import load_save

    fixture = Path(__file__).parent / "fixtures" / "mini_save.txt"
    campaign = _as_player(Campaign.from_raw(load_save(fixture)), tag)
    toolbox = Toolbox(campaign, None, tmp_path / "context.json")
    for name, args in (
        ("get_country_briefing", {}),
        ("get_budget", {}),
        ("get_wars", {}),
        ("get_world_overview", {}),
        ("check_war", {"target": "HAB"}),
        ("get_recommendations", {}),
    ):
        text = toolbox.run(name, args)
        assert text.startswith("# "), (name, text[:80])
        assert not [odd for odd in ODD if odd in text], (name, tag)
    assert f"({tag})" in toolbox.run("get_country_briefing", {})


@pytest.mark.parametrize("tag", ["ASK", "IRO", "C00", "MNG"])
def test_every_tool_works_for_other_kinds_of_country(
    tag: str, real_save, tmp_path: Path, monkeypatch
):
    """On the real save where it exists: Japan, a native tribe, a colonial nation, China."""
    monkeypatch.delenv("CHANCELLOR_CACHE_DIR")
    _, runner, _ = real_save
    if runner is None:
        pytest.skip("the evaluation save is not on this machine")
    campaign = _as_player(runner.campaign, tag)  # type: ignore[attr-defined]
    toolbox = runner.with_campaign(campaign)  # type: ignore[attr-defined]
    toolbox.context_file = tmp_path / "context.json"
    for name in TOOLS:
        text = toolbox.run(name, {})
        assert text.startswith("# "), (name, text[:80])
        assert not [odd for odd in ODD if odd in text], (name, tag)
