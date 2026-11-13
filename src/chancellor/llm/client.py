"""The chat agent: Claude plus the query tools, in a streaming tool-use loop (Phase 4).

Each player question runs a manual agentic loop on the Messages API:

1. stream Claude's reply, showing text as it arrives;
2. if Claude asked for tools, validate the inputs, run them against the loaded save
   (:class:`chancellor.context.tools.Toolbox`) and send all results back in one message;
3. repeat until Claude answers without tools.

Request settings follow the current API guidance: Claude Opus 5.5 by default (override
with ``CHANCELLOR_MODEL``), adaptive thinking (always on for this model) with an explicit
effort level, top-level prompt caching so the system prompt and tool list are reused
across turns, and server-side refusal fallbacks. The whole assistant content (thinking
included) is appended to the history unchanged, keeping the conversation append-only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import CountryLookupError
from chancellor.context.tools import Toolbox, ToolInputError

DEFAULT_EFFORT = "high"
MAX_TOKENS = 64000
MAX_TOOL_ROUNDS = 12  # safety stop for a runaway loop within one question
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_JSON_RETRIES = 2

SYSTEM_PROMPT = """\
You are the Chancellor, an expert advisor for Europa Universalis IV (game version 1.37) \
sitting beside the player while they play. The player's campaign is loaded from their \
latest save file, and you have tools that read it and the game's own files.

How to work:
- Base every factual claim about the campaign on tool results. Call tools whenever a \
question depends on the current state of the game: your own country, another country, a \
possible war, the world, missions, formable nations or where to expand. Several \
independent lookups can be made in parallel.
- Countries can be named by tag or by their name in the player's game language.
- Say what the data cannot tell: war score, casus belli and some estate or parliament \
conditions are not in the tools' output, and truce end dates are estimates; requirements \
marked [?] could not be checked automatically.
- Give concrete, prioritised advice with the reasons from the data (numbers, names, \
dates), then the main risks. Keep answers focused; use short lists or tables when they \
help.
- Answer in the language the player writes in.
"""


@dataclass
class TurnResult:
    """The outcome of one player question.

    Attributes:
        text: Claude's final answer (text blocks of the last response).
        tool_calls: Names of the tools run, in order.
        stop_reason: Why the last response stopped (``end_turn``, ``refusal``, ...).
        input_tokens: Uncached input tokens across all requests of the turn.
        cached_tokens: Input tokens served from the prompt cache.
        output_tokens: Output tokens across all requests of the turn.
    """

    text: str
    tool_calls: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0


class ChancellorAgent:
    """A conversation with Claude about one campaign."""

    def __init__(
        self,
        client: Any,
        toolbox: Toolbox,
        model: str,
        effort: str = DEFAULT_EFFORT,
    ) -> None:
        """Create an agent.

        Args:
            client: An ``anthropic.Anthropic`` client (or a test double with the same shape).
            toolbox: Tools bound to the loaded save.
            model: Model id, e.g. ``claude-opus-5-5``.
            effort: ``low`` … ``max``; how much the model thinks before answering.
        """
        self.client = client
        self.toolbox = toolbox
        self.model = model
        self.effort = effort
        self.messages: list[dict[str, Any]] = []
        self._pending_note: str | None = None

    def note(self, text: str) -> None:
        """Queue an operator note (e.g. "the player saved again") for the next question.

        It is sent as a mid-conversation system message right after the next user message,
        which keeps the cached prefix of the conversation intact.
        """
        self._pending_note = text

    def ask(
        self,
        question: str,
        on_text: Callable[[str], None] = lambda _: None,
        on_tool: Callable[[str, dict[str, Any]], None] = lambda *_: None,
    ) -> TurnResult:
        """Ask a question and run the tool loop until Claude answers.

        Args:
            question: The player's message.
            on_text: Called with each piece of answer text as it streams.
            on_tool: Called with each tool name and its input before it runs.

        Returns:
            The final answer and usage figures.
        """
        self.messages.append({"role": "user", "content": question})
        if self._pending_note:
            self.messages.append({"role": "system", "content": self._pending_note})
            self._pending_note = None

        result = TurnResult(text="")
        for _ in range(MAX_TOOL_ROUNDS):
            response = self._stream_with_retry(on_text)
            self._add_usage(result, response)
            self.messages.append({"role": "assistant", "content": response.content})
            result.stop_reason = response.stop_reason

            if response.stop_reason == "pause_turn":
                continue
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason == "refusal" or not tool_uses:
                result.text = "".join(b.text for b in response.content if b.type == "text")
                return result
            if response.stop_reason == "max_tokens":
                result.text = "".join(b.text for b in response.content if b.type == "text")
                result.text += "\n\n[The answer was cut off: the response hit its token limit.]"
                return result

            results = []
            for block in tool_uses:
                on_tool(block.name, block.input if isinstance(block.input, dict) else {})
                result.tool_calls.append(block.name)
                results.append(self._run_tool(block))
            self.messages.append({"role": "user", "content": results})

        result.text = "[Stopped: too many tool calls for one question.]"
        return result

    # --- internals ----------------------------------------------------------------------

    def _stream_with_retry(self, on_text: Callable[[str], None]) -> Any:
        """Stream one response, re-issuing it if a streamed tool input was unparseable.

        With streamed tool inputs the SDK raises ``ValueError`` from the stream when the
        JSON cannot be parsed at all. No tool call exists to answer then, so the request is
        simply sent again (a few times at most). API errors are not ``ValueError`` and
        propagate to the caller.
        """
        for attempt in range(_JSON_RETRIES + 1):
            try:
                return self._stream(on_text)
            except ValueError:
                if attempt == _JSON_RETRIES:
                    raise
        raise AssertionError("unreachable")

    def _stream(self, on_text: Callable[[str], None]) -> Any:
        tools = [{**tool, "eager_input_streaming": True} for tool in self.toolbox.definitions]
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=self.messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            betas=[_FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            for event in stream:
                if event.type == "text":
                    on_text(event.text)
            return stream.get_final_message()

    def _run_tool(self, block: Any) -> dict[str, Any]:
        try:
            content = self.toolbox.run(block.name, block.input)
            return {"type": "tool_result", "tool_use_id": block.id, "content": content}
        except ToolInputError as exc:
            error = json.dumps({"INVALID_INPUT": str(exc)})
        except CountryLookupError as exc:
            error = str(exc)
        except KeyError as exc:
            error = f"Unknown tool or country: {exc}"
        return {"type": "tool_result", "tool_use_id": block.id, "content": error, "is_error": True}

    @staticmethod
    def _add_usage(result: TurnResult, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        result.input_tokens += getattr(usage, "input_tokens", 0) or 0
        result.cached_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        result.output_tokens += getattr(usage, "output_tokens", 0) or 0
