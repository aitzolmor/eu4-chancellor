"""Terminal chat with the Chancellor (``chancellor chat``).

The first Phase 4 interface: a read-eval-print loop beside the game. Before each question
it checks whether the game wrote a newer save; if so it reloads the campaign and tells
Claude that earlier tool results may be stale. The desktop panel's API chat reuses the
same agent. Both spend from the same budget (:mod:`chancellor.app.budget`, D-028): every
response is charged as it arrives, and a question stops before it can pass its cap.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from chancellor.app.budget import Budget, BudgetExhausted
from chancellor.config import Settings
from chancellor.context.campaign import Campaign
from chancellor.context.tools import Toolbox
from chancellor.llm.client import ChancellorAgent

HELP = """\
Ask anything about your campaign, e.g. "Should I attack Burgundy?" or "What should my
plan be for the next 50 years?". The Chancellor reads your latest save on its own.

Commands:
  /reload   reload the latest save now
  /usage    tokens and money spent (this session and the budget)
  /help     show this help
  /exit     leave (Ctrl+C or Ctrl+Z then Enter also work)
"""


@dataclass
class _Loaded:
    campaign: Campaign
    path: Path
    mtime: float


class ChatSession:
    """Keeps the agent and the loaded save in sync with the game's save folder."""

    def __init__(
        self,
        settings: Settings,
        load: Callable[[Settings], tuple[Campaign, Path]],
        client: Any,
        out: TextIO = sys.stdout,
        budget: Budget | None = None,
    ) -> None:
        """Load the current save and create the agent.

        Args:
            settings: Paths, model and budget settings.
            load: Loads the current campaign and returns it with its save path.
            client: Anthropic client.
            out: Where to print.
            budget: The API budget; by default the one from ``settings``.
        """
        self.settings = settings
        self.budget = budget or Budget(settings.api_budget_usd, settings.question_cap_usd)
        self._load = load
        self.out = out
        self.loaded = self._load_current()
        self.agent = ChancellorAgent(
            client,
            Toolbox(self.loaded.campaign, settings.game_dir),
            model=settings.model,
            effort=settings.effort,
        )
        self.totals = {"input": 0, "cached": 0, "output": 0, "cost": 0.0}

    def _load_current(self) -> _Loaded:
        campaign, path = self._load(self.settings)
        return _Loaded(campaign, path, path.stat().st_mtime)

    def refresh(self, force: bool = False) -> bool:
        """Reload if the game wrote a newer save. Returns whether a reload happened."""
        if not force and not self._save_changed():
            return False
        previous = self.loaded
        self.loaded = self._load_current()
        self.agent.toolbox = Toolbox(self.loaded.campaign, self.settings.game_dir)
        self.agent.note(
            f"The player saved again: the campaign is now at {self.loaded.campaign.date} "
            f"(was {previous.campaign.date}). Tool results from earlier in this conversation "
            "may be out of date; look things up again before relying on them."
        )
        self._print(f"[Loaded {self.loaded.path.name}, {self.loaded.campaign.date}]")
        return True

    def _save_changed(self) -> bool:
        if self.settings.save_dir is None:
            return False
        from chancellor.save.loader import find_current_save

        try:
            current = find_current_save(self.settings.save_dir)
        except FileNotFoundError:
            return False
        return current != self.loaded.path or current.stat().st_mtime != self.loaded.mtime

    def ask(self, question: str) -> None:
        """Answer one question, streaming the reply, within the budget."""
        try:
            limit = self.budget.question_limit()
        except BudgetExhausted as exc:
            self._print(f"[{exc}]")
            return
        self.refresh()

        def on_tool(name: str, arguments: dict[str, Any]) -> None:
            shown = ", ".join(f"{k}={v}" for k, v in arguments.items())
            self._print(f"\n  · {name}({shown})")

        result = self.agent.ask(
            question,
            on_text=lambda text: self._write(text),
            on_tool=on_tool,
            cost_limit=limit,
            on_cost=self.budget.charge,
        )
        if result.stop_reason == "cost_limit":
            self._print(f"\n{result.text}")
        elif result.stop_reason == "refusal":
            self._print("\n[The model declined to answer this request.]")
        elif not result.text.strip():
            self._print("\n[No answer was returned.]")
        self._print("")
        self.totals["input"] += result.input_tokens
        self.totals["cached"] += result.cached_tokens
        self.totals["output"] += result.output_tokens
        self.totals["cost"] += result.cost
        self._print(f"[${result.cost:.3f} for this question; {self.budget.summary()}]")

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def _print(self, text: str) -> None:
        self.out.write(text + "\n")
        self.out.flush()


def run_chat(
    settings: Settings,
    load: Callable[[Settings], tuple[Campaign, Path]],
    client: Any | None = None,
    read: Callable[[str], str] = input,
    out: TextIO = sys.stdout,
) -> int:
    """Run the interactive chat until the player leaves.

    Returns:
        Process exit code.
    """
    import anthropic  # deferred: importing the SDK takes seconds, and only chat needs it

    if client is None:
        client = (
            anthropic.Anthropic(api_key=settings.api_key)
            if settings.api_key
            else anthropic.Anthropic()
        )
    session = ChatSession(settings, load, client, out)
    campaign = session.loaded.campaign
    out.write(
        f"Chancellor ready: {campaign.label(campaign.player)}, {campaign.date} "
        f"({session.loaded.path.name}). Model {settings.model}, effort {settings.effort}.\n"
        f"Billed per question: up to ${settings.question_cap_usd:.2f} each; "
        f"{session.budget.summary()}.\n"
        "Type /help for commands.\n\n"
    )
    while True:
        try:
            question = read("> ").strip()
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            return 0
        if not question:
            continue
        if question in ("/exit", "/quit"):
            return 0
        if question == "/help":
            out.write(HELP)
            continue
        if question == "/reload":
            session.refresh(force=True)
            continue
        if question == "/usage":
            t = session.totals
            out.write(
                f"Input {t['input']:,} tokens (+{t['cached']:,} from cache), "
                f"output {t['output']:,} tokens, ${t['cost']:.3f} this session; "
                f"{session.budget.summary()}.\n"
            )
            continue
        try:
            session.ask(question)
        except KeyboardInterrupt:
            out.write("\n[Interrupted]\n")
        except anthropic.AuthenticationError:
            out.write(
                "\n[Authentication failed: set ANTHROPIC_API_KEY in .env (see .env.example).]\n"
            )
            return 1
        except anthropic.RateLimitError:
            out.write("\n[Rate limited by the API; wait a moment and ask again.]\n")
        except anthropic.APIStatusError as exc:
            out.write(f"\n[API error {exc.status_code}: {exc.message}]\n")
        except anthropic.APIConnectionError:
            out.write("\n[Could not reach the API; check the internet connection.]\n")
