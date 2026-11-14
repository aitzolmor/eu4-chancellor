"""The panel's API chat: the paid mode the player switches on (D-020, D-028).

Off by default and only for the session: every launch starts in Claude Desktop mode.
Turning it on needs an API key and budget left. Questions run on a worker thread with
:class:`chancellor.llm.client.ChancellorAgent`; the answer streams to the page as events
(``chat-delta``, ``chat-tool``, ``chat-done``, ``chat-error``) through ``emit``. Every
response is charged to the shared budget as it arrives, and each question stops before
it could pass its cap.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from chancellor.app.budget import Budget, BudgetExhausted
from chancellor.config import Settings
from chancellor.context.tools import Toolbox
from chancellor.llm.client import ChancellorAgent

Emit = Callable[[str, dict[str, Any]], None]


def anthropic_client(settings: Settings) -> Any:
    """A real Anthropic client. Importing the SDK takes seconds, so it happens here."""
    import anthropic

    return anthropic.Anthropic(api_key=settings.api_key) if settings.api_key else None


class ApiChat:
    """The API chat of one panel session."""

    def __init__(
        self,
        settings: Settings,
        toolbox: Callable[[], Toolbox],
        budget: Budget | None = None,
        client_factory: Callable[[Settings], Any] = anthropic_client,
    ) -> None:
        """Create the chat (nothing is imported or sent until it is switched on).

        Args:
            settings: Model, effort, key and budget settings.
            toolbox: Returns the toolbox for the newest save (reloads when it changed).
            budget: The shared API budget; by default the one from ``settings``.
            client_factory: Builds the API client; replaceable in tests.
        """
        self._settings = settings
        self._toolbox = toolbox
        self._budget = budget or Budget(settings.api_budget_usd, settings.question_cap_usd)
        self._client_factory = client_factory
        self._agent: ChancellorAgent | None = None
        self._on = False
        self._busy = threading.Lock()
        self._ready = threading.Event()
        self._session_cost = 0.0
        self._questions = 0

    # --- what the page shows ------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        """Mode, availability and money, for the header badge and the menu."""
        reason = self._unavailable_reason()
        return {
            "mode": "api" if self._on else "claude_desktop",
            "api_available": reason is None,
            "reason": reason,
            "model": self._settings.model,
            "effort": self._settings.effort,
            "question_cap": self._settings.question_cap_usd,
            "spent": round(self._budget.spent, 4),
            "budget": self._settings.api_budget_usd,
            "session_cost": round(self._session_cost, 4),
            "questions": self._questions,
            "busy": self._busy.locked(),
        }

    def _unavailable_reason(self) -> str | None:
        if not self._settings.api_key:
            return "No API key: set ANTHROPIC_API_KEY in .env."
        if self._budget.remaining < 0.01:
            return f"The API budget is used up ({self._budget.summary()})."
        return None

    # --- switching ------------------------------------------------------------------------

    def set_mode(self, mode: str) -> dict[str, Any]:
        """Switch between ``claude_desktop`` and ``api``. The page asks the player first.

        Returns:
            :meth:`state`, or ``{"ok": False, "error": ...}`` when the API is unavailable.
        """
        if mode == "claude_desktop":
            self._on = False
            return {"ok": True, **self.state()}
        if mode != "api":
            return {"ok": False, "error": f"Unknown chat mode '{mode}'."}
        reason = self._unavailable_reason()
        if reason:
            return {"ok": False, "error": reason}
        self._on = True
        if self._agent is None and not self._ready.is_set():
            threading.Thread(target=self._prepare, name="api-chat-prepare", daemon=True).start()
        return {"ok": True, **self.state()}

    def _prepare(self) -> None:
        """Build the client and agent off the UI thread (the SDK import is slow)."""
        try:
            client = self._client_factory(self._settings)
            self._agent = ChancellorAgent(
                client, self._toolbox(), model=self._settings.model, effort=self._settings.effort
            )
        except Exception:  # noqa: BLE001 - reported when the player asks
            self._agent = None
        finally:
            self._ready.set()

    # --- asking ---------------------------------------------------------------------------

    def ask(self, question: str, emit: Emit) -> dict[str, Any]:
        """Start answering a question on a worker thread; the answer arrives as events.

        Returns:
            ``{"ok": True}`` once started, or ``{"ok": False, "error": ...}``.
        """
        question = question.strip()
        if not self._on:
            return {"ok": False, "error": "The API chat is off; switch it on in the menu."}
        if not question:
            return {"ok": False, "error": "Type a question first."}
        try:
            limit = self._budget.question_limit()
        except BudgetExhausted as exc:
            return {"ok": False, "error": str(exc)}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "error": "Still answering the previous question."}
        threading.Thread(
            target=self._answer, args=(question, limit, emit), name="api-chat", daemon=True
        ).start()
        return {"ok": True}

    def _answer(self, question: str, limit: float, emit: Emit) -> None:
        try:
            self._ready.wait(60)
            agent = self._agent
            if agent is None:
                emit("chat-error", {"error": "The API client could not be created."})
                return
            self._follow_save(agent)

            def charge(cost: float) -> None:
                self._budget.charge(cost)
                self._session_cost += cost

            result = agent.ask(
                question,
                on_text=lambda text: emit("chat-delta", {"text": text}),
                on_tool=lambda name, _args: emit("chat-tool", {"name": name}),
                cost_limit=limit,
                on_cost=charge,
            )
            self._questions += 1
            note = None
            if result.stop_reason == "cost_limit":
                note = result.text
            elif result.stop_reason == "refusal":
                note = "The model declined to answer this request."
            elif not result.text.strip():
                note = "No answer was returned."
            emit(
                "chat-done",
                {"cost": round(result.cost, 4), "note": note, **self.state(), "busy": False},
            )
        except Exception as exc:  # noqa: BLE001 - any failure must reach the page
            emit("chat-error", {"error": _describe(exc), **self.state(), "busy": False})
        finally:
            self._busy.release()

    def _follow_save(self, agent: ChancellorAgent) -> None:
        """Give the agent the newest save, and tell Claude when it changed."""
        toolbox = self._toolbox()
        if toolbox is agent.toolbox:
            return
        before, after = agent.toolbox.campaign.date, toolbox.campaign.date
        agent.toolbox = toolbox
        agent.note(
            f"The player saved again: the campaign is now at {after} (was {before}). Tool "
            "results from earlier in this conversation may be out of date; look things up "
            "again before relying on them."
        )


def _describe(exc: Exception) -> str:
    """A short, player-facing message for an API failure (the SDK is not imported here)."""
    name = type(exc).__name__
    messages = {
        "AuthenticationError": "Authentication failed: check ANTHROPIC_API_KEY in .env.",
        "PermissionDeniedError": "The API key is not allowed to use this model.",
        "RateLimitError": "Rate limited by the API; wait a moment and ask again.",
        "APIConnectionError": "Could not reach the API; check the internet connection.",
        "APITimeoutError": "The API took too long to answer; ask again.",
    }
    if name in messages:
        return messages[name]
    status = getattr(exc, "status_code", None)
    if status == 400 and "credit" in str(exc).lower():
        return "The API account has no credit left."
    return f"API error{f' {status}' if status else ''}: {exc}"
