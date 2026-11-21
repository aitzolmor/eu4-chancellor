"""Other models and MCP clients: LM Studio's config, and asking a model the evals (D-062)."""

import json
from pathlib import Path
from typing import Any

from chancellor.app.mcp_server import SERVER_NAME, write_client_config
from chancellor.config import Settings
from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.evals import Case, EvalSet, render_model_results, run_model_eval
from chancellor.game.localisation import Localisation
from chancellor.llm.local import Answer, ask, openai_tools
from chancellor.save.parser import parse


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        save_dir=tmp_path / "save games",
        game_dir=tmp_path / "game",
        api_key=None,
        language="spanish",
    )


def test_lm_studio_config_keeps_other_servers(tmp_path: Path):
    path = tmp_path / ".lmstudio" / "mcp.json"
    assert write_client_config(path, _settings(tmp_path), "python") is None  # no file before
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    backup = write_client_config(path, _settings(tmp_path), "python")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"other", SERVER_NAME}
    assert data["mcpServers"][SERVER_NAME]["args"] == ["-m", "chancellor.app.cli", "mcp"]
    assert data["mcpServers"][SERVER_NAME]["env"]["EU4_LANGUAGE"] == "spanish"
    assert backup is not None and "other" in backup.read_text(encoding="utf-8")


class FakeTools:
    definitions = [
        {"name": "get_trade", "description": "Trade.", "input_schema": {"type": "object"}}
    ]

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, name: str, args: dict[str, Any]) -> str:
        self.calls.append((name, args))
        return "Home node Venice: 65% of its trade power. " + "x" * 50


def test_ask_runs_the_tools_until_the_model_answers():
    replies = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "1",
                                    "function": {
                                        "name": "get_trade",
                                        "arguments": '{"country": "player"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "You hold 65% at Venice."}}]},
        ]
    )
    sent: list[dict[str, Any]] = []

    def post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        sent.append(payload)
        return next(replies)

    tools = FakeTools()
    answer = ask("Trade?", tools, "qwen3-4b", system="Be brief.", post=post, max_tool_chars=40)
    assert answer.text == "You hold 65% at Venice." and answer.tools == ["get_trade"]
    assert answer.cut  # the result was longer than 40 characters
    assert tools.calls == [("get_trade", {"country": "player"})]
    assert sent[0]["tools"] == openai_tools(FakeTools.definitions)
    assert sent[1]["messages"][-1]["content"].endswith("[Cut to fit the model's context.]")


def test_a_model_run_is_scored_on_tool_and_facts():
    evalset = EvalSet(
        "s",
        "save.eu4",
        "HAB",
        "1535.8.2",
        [
            Case("trade", "Trade?", "get_trade", answer=["65"]),
            Case("budget", "Money?", "get_budget", answer=["35.1"]),
        ],
    )
    answers = {
        "Trade?": Answer("You have 65 %", ["get_trade"], 10.0),
        "Money?": Answer("Army costs 35,1 a month", ["get_trade"], 20.0),
    }
    results = run_model_eval(evalset, lambda q: answers[q])
    assert [(r.right_tool, r.missing) for r in results] == [(True, []), (False, [])]
    report = render_model_results(evalset, "qwen3-4b", results)
    assert report.startswith("# Eval s with qwen3-4b: right tool 1 of 2, full answer 1 of 2")
    assert "    - expected get_budget" in report
    assert len(run_model_eval(evalset, lambda q: answers[q], ids=["trade"])) == 1


def test_player_words_mean_the_player(tmp_path: Path):
    campaign = Campaign(
        {"player": "HAB", "date": "1535.8.2"},
        parse("countries={ HAB={ } POL={ } }"),
        Localisation({"HAB": "Austria"}),
    )
    toolbox = Toolbox(campaign, None, tmp_path / "context.json")
    for word in ("player", "Me", "my  country", "ROOT"):
        assert toolbox.run("get_budget", {"country": word}).startswith("# Budget of Austria")
