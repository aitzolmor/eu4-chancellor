"""The panel's API chat, with a fake Anthropic client (no network, no cost)."""

import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from chancellor.app.api_chat import ApiChat, _describe
from chancellor.app.budget import Budget
from chancellor.config import Settings
from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.save.loader import load_save

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"


def _message(*blocks, stop_reason="end_turn"):
    usage = SimpleNamespace(
        input_tokens=2000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1000,
    )
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage, model=None)


def _text(value):
    return SimpleNamespace(type="text", text=value)


class _Stream:
    def __init__(self, final):
        self.final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for block in self.final.content:
            if block.type == "text":
                yield SimpleNamespace(type="text", text=block.text)

    def get_final_message(self):
        return self.final


class _Messages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def stream(self, **_kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Stream(item)


@pytest.fixture
def toolbox(tmp_path: Path) -> Toolbox:
    path = tmp_path / "mini.eu4"
    shutil.copy(FIXTURE, path)
    return Toolbox(Campaign.from_raw(load_save(path)), None)


def _settings(api_key="test") -> Settings:
    return Settings(save_dir=None, game_dir=None, api_key=api_key, model="claude-sonnet-5-5")


def _chat(toolbox, *script, api_key="test", budget=None):
    messages = _Messages(script)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    chat = ApiChat(
        _settings(api_key), lambda: toolbox, budget=budget, client_factory=lambda _s: client
    )
    return chat, messages


def _wait_for(events, name, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(event == name for event, _ in events):
            return
        time.sleep(0.01)
    raise AssertionError(f"no {name} event; got {events}")


def test_starts_in_claude_desktop_mode(toolbox):
    chat, _ = _chat(toolbox)
    state = chat.state()
    assert state["mode"] == "claude_desktop"
    assert state["api_available"] is True
    assert (state["model"], state["question_cap"], state["budget"]) == (
        "claude-sonnet-5-5",
        0.5,
        5.0,
    )


def test_unavailable_without_a_key_or_budget(toolbox):
    chat, _ = _chat(toolbox, api_key=None)
    assert chat.state()["api_available"] is False
    assert chat.set_mode("api") == {
        "ok": False,
        "error": "No API key: set ANTHROPIC_API_KEY in .env.",
    }

    spent = Budget(total=1.0, question_cap=0.5)
    spent.charge(1.0)
    chat, _ = _chat(toolbox, budget=spent)
    assert "budget is used up" in chat.set_mode("api")["error"]


def test_asking_needs_the_api_mode(toolbox):
    chat, messages = _chat(toolbox, _message(_text("never")))
    events = []
    assert chat.ask("¿Cómo voy?", lambda *e: events.append(e))["ok"] is False
    assert messages.calls == 0


def test_answer_streams_and_is_charged(toolbox):
    chat, _ = _chat(toolbox, _message(_text("Bien, "), _text("canciller.")))
    assert chat.set_mode("api")["mode"] == "api"
    events = []
    assert chat.ask("¿Cómo voy?", lambda *e: events.append(e)) == {"ok": True}
    _wait_for(events, "chat-done")
    deltas = "".join(detail["text"] for name, detail in events if name == "chat-delta")
    assert deltas == "Bien, canciller."
    done = next(detail for name, detail in events if name == "chat-done")
    assert done["cost"] == pytest.approx(0.014)  # 2000 in at $2/M + 1000 out at $10/M
    assert done["spent"] == pytest.approx(0.014)  # charged to the shared budget
    assert done["questions"] == 1 and done["busy"] is False
    assert done["note"] is None


def test_api_errors_reach_the_page(toolbox):
    error = type("RateLimitError", (Exception,), {})("slow down")
    chat, _ = _chat(toolbox, error)
    chat.set_mode("api")
    events = []
    chat.ask("¿Cómo voy?", lambda *e: events.append(e))
    _wait_for(events, "chat-error")
    detail = next(d for name, d in events if name == "chat-error")
    assert detail["error"] == "Rate limited by the API; wait a moment and ask again."
    assert chat.state()["busy"] is False


def test_one_question_at_a_time(toolbox):
    chat, _ = _chat(toolbox, _message(_text("Uno.")))
    chat.set_mode("api")
    chat._busy.acquire()
    try:
        assert chat.ask("¿Otra?", lambda *e: None) == {
            "ok": False,
            "error": "Still answering the previous question.",
        }
    finally:
        chat._busy.release()


def test_switching_off_keeps_the_spending(toolbox):
    chat, _ = _chat(toolbox)
    chat.set_mode("api")
    assert chat.set_mode("claude_desktop")["mode"] == "claude_desktop"
    assert chat.set_mode("telepathy") == {"ok": False, "error": "Unknown chat mode 'telepathy'."}


def test_failures_are_described_for_the_player():
    auth = type("AuthenticationError", (Exception,), {})("bad key")
    assert "ANTHROPIC_API_KEY" in _describe(auth)
    credit = type("BadRequestError", (Exception,), {"status_code": 400})(
        "Your credit balance is too low"
    )
    assert _describe(credit) == "The API account has no credit left."
