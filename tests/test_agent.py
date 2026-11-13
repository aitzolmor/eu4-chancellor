"""The chat agent and its tools, with a fake Anthropic client (no network, no cost)."""

import io
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from chancellor.app.chat import ChatSession, run_chat
from chancellor.config import Settings
from chancellor.context.campaign import Campaign
from chancellor.context.tools import TOOL_DEFINITIONS, Toolbox, ToolInputError, validate
from chancellor.game.localisation import Localisation
from chancellor.llm.client import MAX_TOOL_ROUNDS, SYSTEM_PROMPT, ChancellorAgent
from chancellor.save.loader import load_save

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"


# --- fakes -----------------------------------------------------------------------------


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(name, arguments, block_id="tu_1"):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=arguments)


def message(*blocks, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=10, cache_read_input_tokens=4, output_tokens=3)
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage)


class FakeStream:
    def __init__(self, final, error=None):
        self.final = final
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        if self.error:
            raise self.error
        for block in self.final.content:
            if block.type == "text":
                yield SimpleNamespace(type="text", text=block.text)

    def get_final_message(self):
        return self.final


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.script.pop(0)
        return item if isinstance(item, FakeStream) else FakeStream(item)


def fake_client(*script):
    messages = FakeMessages(script)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


@pytest.fixture
def campaign(tmp_path: Path) -> Campaign:
    path = tmp_path / "mini.eu4"
    shutil.copy(FIXTURE, path)
    names = {"HAB": "Austria", "TUR": "Otomanos", "BOH": "Bohemia"}
    return Campaign.from_raw(load_save(path), Localisation(names))


def make_agent(campaign, *script, effort="high"):
    client, messages = fake_client(*script)
    agent = ChancellorAgent(client, Toolbox(campaign, None), "claude-opus-5-5", effort)
    return agent, messages


# --- the agent loop ---------------------------------------------------------------------


def test_plain_answer_streams_and_sends_the_right_request(campaign):
    agent, api = make_agent(campaign, message(text("Hola, "), text("canciller.")))
    streamed = []

    result = agent.ask("¿Cómo voy?", on_text=streamed.append)

    assert result.text == "Hola, canciller."
    assert "".join(streamed) == "Hola, canciller."
    request = api.calls[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["system"] == SYSTEM_PROMPT
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"] == {"effort": "high"}
    assert request["cache_control"] == {"type": "ephemeral"}
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert [t["name"] for t in request["tools"]] == [t["name"] for t in TOOL_DEFINITIONS]
    assert all(t["eager_input_streaming"] for t in request["tools"])
    assert request["messages"] == [{"role": "user", "content": "¿Cómo voy?"}]


def test_tool_loop_runs_tools_and_returns_results(campaign):
    agent, api = make_agent(
        campaign,
        message(tool_use("get_country_briefing", {"country": "otomanos"}), stop_reason="tool_use"),
        message(text("Los otomanos son tus rivales.")),
    )
    calls = []

    result = agent.ask("¿Y los otomanos?", on_tool=lambda name, args: calls.append((name, args)))

    assert result.text == "Los otomanos son tus rivales."
    assert result.tool_calls == ["get_country_briefing"]
    assert calls == [("get_country_briefing", {"country": "otomanos"})]
    tool_message = api.calls[1]["messages"][-1]
    assert tool_message["role"] == "user"
    [tool_result] = tool_message["content"]
    assert tool_result["tool_use_id"] == "tu_1"
    assert tool_result["content"].startswith("# Country briefing: Otomanos (TUR)")
    assert "is_error" not in tool_result
    assert (result.input_tokens, result.cached_tokens, result.output_tokens) == (20, 8, 6)


def test_parallel_tool_calls_answered_in_one_message(campaign):
    agent, api = make_agent(
        campaign,
        message(
            tool_use("get_country_briefing", {}, "a"),
            tool_use("check_war", {"target": "TUR"}, "b"),
            stop_reason="tool_use",
        ),
        message(text("ok")),
    )
    agent.ask("plan")
    results = api.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert results[1]["content"].startswith("# War check: Austria (HAB) vs Otomanos (TUR)")


def test_invalid_input_and_unknown_country_become_tool_errors(campaign):
    agent, api = make_agent(
        campaign,
        message(
            tool_use("check_war", {"target": 5}, "a"),
            tool_use("get_country_briefing", {"country": "Narnia"}, "b"),
            stop_reason="tool_use",
        ),
        message(text("Lo siento.")),
    )
    agent.ask("?")
    first, second = api.calls[1]["messages"][-1]["content"]
    assert first["is_error"] and "INVALID_INPUT" in first["content"]
    assert second["is_error"] and "No country named 'Narnia'" in second["content"]


def test_refusal_stops_without_running_tools(campaign):
    agent, api = make_agent(
        campaign, message(tool_use("get_world_overview", {}), stop_reason="refusal")
    )
    result = agent.ask("?")
    assert result.stop_reason == "refusal"
    assert len(api.calls) == 1


def test_truncated_tool_call_is_not_run(campaign):
    agent, api = make_agent(
        campaign, message(text("Voy a"), tool_use("check_war", {}), stop_reason="max_tokens")
    )
    result = agent.ask("?")
    assert result.tool_calls == []
    assert "cut off" in result.text
    assert len(api.calls) == 1


def test_pause_turn_is_resumed(campaign):
    agent, api = make_agent(
        campaign, message(text("..."), stop_reason="pause_turn"), message(text("listo"))
    )
    assert agent.ask("?").text == "listo"
    assert len(api.calls) == 2


def test_unparseable_streamed_input_is_retried(campaign):
    agent, api = make_agent(
        campaign, FakeStream(message(), error=ValueError("bad json")), message(text("ok"))
    )
    assert agent.ask("?").text == "ok"
    assert len(api.calls) == 2


def test_history_is_append_only_across_questions(campaign):
    agent, api = make_agent(campaign, message(text("uno")), message(text("dos")))
    agent.ask("primera")
    agent.ask("segunda")
    first, second = api.calls[0]["messages"], api.calls[1]["messages"]
    assert second[: len(first)] == first
    assert [m["role"] for m in second] == ["user", "assistant", "user"]


def test_note_is_sent_as_system_message_after_the_question(campaign):
    agent, api = make_agent(campaign, message(text("ok")), message(text("ok")))
    agent.note("The player saved again.")
    agent.ask("?")
    assert api.calls[0]["messages"][-2:] == [
        {"role": "user", "content": "?"},
        {"role": "system", "content": "The player saved again."},
    ]
    agent.ask("again")
    assert api.calls[1]["messages"][-1] == {"role": "user", "content": "again"}  # sent once


def test_runaway_tool_loop_is_stopped(campaign):
    script = [
        message(tool_use("get_world_overview", {}, f"t{i}"), stop_reason="tool_use")
        for i in range(MAX_TOOL_ROUNDS)
    ]
    agent, api = make_agent(campaign, *script)
    assert "too many tool calls" in agent.ask("?").text
    assert len(api.calls) == MAX_TOOL_ROUNDS


# --- tools -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "arguments", "error"),
    [
        ("check_war", {}, "needs `target`"),
        ("check_war", {"target": "  "}, "must be a str"),
        ("get_missions", {"brief": "yes"}, "must be a bool"),
        ("get_world_overview", {"extra": 1}, "unknown arguments"),
        ("get_decisions", [], "expects an object"),
    ],
)
def test_validate_rejects_bad_input(name, arguments, error):
    with pytest.raises(ToolInputError, match=error):
        validate(name, arguments)


def test_validate_unknown_tool():
    with pytest.raises(KeyError):
        validate("format_disk", {})


def test_definitions_match_validation_schemas():
    from chancellor.context.tools import _SCHEMAS

    for tool in TOOL_DEFINITIONS:
        schema = tool["input_schema"]
        assert set(schema["properties"]) == set(_SCHEMAS[tool["name"]])
        required = {f for f, spec in _SCHEMAS[tool["name"]].items() if spec.required}
        assert set(schema.get("required", [])) == required
        assert schema["additionalProperties"] is False


def test_toolbox_runs_save_tools(campaign):
    toolbox = Toolbox(campaign, None)
    assert toolbox.run("get_country_briefing", {}).startswith("# Campaign briefing: Austria")
    assert toolbox.run("get_world_overview", {}).startswith("# World overview")
    with pytest.raises(ToolInputError, match="EU4_GAME_DIR"):
        toolbox.run("get_missions", {})


def test_toolbox_runs_game_file_tools(campaign, tmp_path: Path):
    game = tmp_path / "game"
    (game / "decisions").mkdir(parents=True)
    (game / "decisions" / "d.txt").write_text(
        "country_decisions = { form_x = { potential = { tag = HAB } allow = { adm_tech = 1 } "
        "effect = { change_tag = XXX } } }",
        encoding="utf-8",
    )
    toolbox = Toolbox(campaign, game)
    assert "forms XXX (XXX)" in toolbox.run("get_decisions", {"formables_only": True})
    assert "records no mission tree" in toolbox.run("get_missions", {"brief": True})
    assert toolbox.run("get_expansion_targets", {}).startswith("# Expansion targets")


# --- terminal session ------------------------------------------------------------------


@pytest.fixture
def save_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "user" / "save games"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "mini.eu4")
    return folder


def loader(settings: Settings):
    path = settings.save_dir / "mini.eu4"
    return Campaign.from_raw(load_save(path)), path


def settings_for(save_dir: Path) -> Settings:
    return Settings(save_dir=save_dir, game_dir=None, api_key="test", model="claude-opus-5-5")


def test_session_reloads_when_the_game_saves(save_dir: Path):
    client, api = fake_client(message(text("ok")))
    out = io.StringIO()
    session = ChatSession(settings_for(save_dir), loader, client, out)
    assert not session.refresh()

    path = save_dir / "mini.eu4"
    os.utime(path, (path.stat().st_mtime + 60,) * 2)
    session.ask("¿Qué ha cambiado?")

    assert "[Loaded mini.eu4, 1471.10.2]" in out.getvalue()
    sent = api.calls[0]["messages"]
    assert sent[-1]["role"] == "system"
    assert "The player saved again" in sent[-1]["content"]


def test_run_chat_commands(save_dir: Path):
    client, api = fake_client(message(text("Respuesta.")))
    inputs = iter(["", "/help", "¿Cómo voy?", "/usage", "/exit"])
    out = io.StringIO()

    code = run_chat(settings_for(save_dir), loader, client, read=lambda _: next(inputs), out=out)

    text_out = out.getvalue()
    assert code == 0
    assert text_out.startswith("Chancellor ready: HAB (HAB), 1471.10.2 (mini.eu4).")
    assert "/reload" in text_out  # help
    assert "Respuesta." in text_out
    assert "Input 10 tokens (+4 from cache), output 3 tokens." in text_out
    assert len(api.calls) == 1


def test_run_chat_ends_on_eof(save_dir: Path):
    client, _ = fake_client()

    def read(_):
        raise EOFError

    assert run_chat(settings_for(save_dir), loader, client, read=read, out=io.StringIO()) == 0
