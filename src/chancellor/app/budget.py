"""The API budget: what the app has spent across sessions, and what it may still spend.

The player's API balance is small and fixed (D-028), so the app keeps its own running
total in ``state.json`` (:mod:`chancellor.app.state`), shared by ``chancellor chat`` and
the panel's API chat. It counts what the app spent, priced from the usage the API
returned; spending outside the app (the Console, other programs) is not seen, so the
budget should be set to what is left for the app.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from chancellor.app.state import load_api_spent, save_api_spent


class BudgetExhausted(RuntimeError):
    """The budget cannot cover another question."""


@dataclass
class Budget:
    """A spending limit kept between sessions.

    Attributes:
        total: The most the app may spend in all, in US dollars.
        question_cap: The most one question may cost.
    """

    total: float
    question_cap: float

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    @property
    def spent(self) -> float:
        """What the app has spent so far, across sessions."""
        return load_api_spent()

    @property
    def remaining(self) -> float:
        """What is left of the budget (never below zero)."""
        return max(self.total - self.spent, 0.0)

    def question_limit(self) -> float:
        """The most the next question may cost: the cap, or less when little is left.

        Raises:
            BudgetExhausted: If less than a cent is left.
        """
        remaining = self.remaining
        if remaining < 0.01:
            raise BudgetExhausted(
                f"The API budget is used up: ${self.spent:.2f} of ${self.total:.2f} spent."
            )
        return min(self.question_cap, remaining)

    def charge(self, amount: float) -> None:
        """Record money spent (called after every response, so nothing is lost)."""
        if amount <= 0:
            return
        with self._lock:
            save_api_spent(load_api_spent() + amount)

    def summary(self) -> str:
        """``$0.23 of $5.00 spent``."""
        return f"${self.spent:.2f} of ${self.total:.2f} spent"
