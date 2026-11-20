"""Ask a question to any model behind an OpenAI-compatible API, with the Chancellor's tools.

Used to measure how other models do with the same tools (D-062): LM Studio, Ollama and
most local servers speak this API (``/v1/chat/completions`` with ``tools``). This is a
plain loop with no streaming, caching or pricing: for evaluating a model on the
evaluation set, not for the panel's chat, which stays on the Anthropic API (D-028).

Small models have small contexts, so a tool result longer than ``max_tool_chars`` is cut,
with a note saying so; the evaluation reports when that happened.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_BASE_URL = "http://localhost:1234/v1"  # LM Studio's local server
MAX_ROUNDS = 4


class Tools(Protocol):
    """What runs the tools: :class:`chancellor.context.tools.Toolbox` in practice."""

    @property
    def definitions(self) -> list[dict[str, Any]]: ...  # noqa: D102

    def run(self, name: str, args: dict[str, Any]) -> str: ...  # noqa: D102


@dataclass
class Answer:
    """What the model did with one question.

    Attributes:
        text: Its final answer.
        tools: The tools it called, in order.
        seconds: How long the whole exchange took.
        cut: Whether a tool result had to be shortened to fit.
        error: What went wrong, if the exchange failed.
    """

    text: str = ""
    tools: list[str] = field(default_factory=list)
    seconds: float = 0.0
    cut: bool = False
    error: str = ""


def openai_tools(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The Chancellor's tool definitions in the OpenAI ``tools`` format."""
    return [
        {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": d["input_schema"],
            },
        }
        for d in definitions
    ]


def ask(
    question: str,
    tools: Tools,
    model: str,
    *,
    system: str,
    base_url: str = DEFAULT_BASE_URL,
    max_tool_chars: int = 14000,
    max_tokens: int = 1024,
    timeout: float = 1800.0,
    post: Any = None,
) -> Answer:
    """Ask one question and run the tools the model calls until it answers.

    Args:
        question: The player's question.
        tools: The tools, bound to a save.
        model: The model's identifier on the server.
        system: The system prompt (the MCP server's instructions).
        base_url: The server's ``/v1`` URL.
        max_tool_chars: Longest tool result sent back; longer ones are cut.
        max_tokens: Longest reply; a small model can otherwise ramble for minutes.
        timeout: Seconds to wait for one response (local models are slow).
        post: Replaces the HTTP call in tests: ``(url, payload) -> response dict``.
    """
    post = post or (lambda url, payload: _post(url, payload, timeout))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    answer = Answer()
    start = time.monotonic()
    try:
        for _ in range(MAX_ROUNDS):
            response = post(
                f"{base_url.rstrip('/')}/chat/completions",
                {
                    "model": model,
                    "messages": messages,
                    "tools": openai_tools(tools.definitions),
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                },
            )
            message = response["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if not calls:
                answer.text = message.get("content") or ""
                break
            messages.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
            for call in calls:
                name = call["function"]["name"]
                answer.tools.append(name)
                result = _run(tools, name, call["function"].get("arguments") or "{}")
                if len(result) > max_tool_chars:
                    result = result[:max_tool_chars] + "\n\n[Cut to fit the model's context.]"
                    answer.cut = True
                messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
                )
        else:
            answer.error = f"no answer after {MAX_ROUNDS} rounds of tool calls"
    except (OSError, KeyError, ValueError) as exc:
        answer.error = f"{exc.__class__.__name__}: {exc}"
    answer.seconds = time.monotonic() - start
    return answer


def _run(tools: Tools, name: str, arguments: str) -> str:
    try:
        args = json.loads(arguments) if arguments.strip() else {}
        return tools.run(name, args if isinstance(args, dict) else {})
    except Exception as exc:  # noqa: BLE001 - the model sees the error and may retry
        return f"Error: {exc.__class__.__name__}: {exc}"


def _post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - a local URL the user gives
        return json.loads(response.read().decode("utf-8"))
