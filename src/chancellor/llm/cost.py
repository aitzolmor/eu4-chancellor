"""What API requests cost, from the usage figures the API returns (D-028).

The player's API balance is small and fixed, so the chat counts what every response
costs as it arrives and stops a question before it can run away. Prices are US dollars
per million tokens, from Anthropic's published price list (checked 2026-11-03). A cache
write costs 1.25 times the input price (5-minute cache); a cache read is listed per
model. An unknown model is priced like the most expensive one listed, so the guard
errs on the safe side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_MILLION = 1_000_000
_CACHE_WRITE_FACTOR = 1.25


@dataclass(frozen=True)
class Prices:
    """US dollars per million tokens for one model."""

    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        """A 5-minute cache write: 1.25 times the input price."""
        return self.input * _CACHE_WRITE_FACTOR


PRICES: dict[str, Prices] = {
    "claude-fable-5-2": Prices(8.00, 40.00, 0.20),
    "claude-opus-5-5": Prices(4.00, 20.00, 0.20),
    "claude-opus-5": Prices(5.00, 25.00, 0.50),
    "claude-opus-4-8": Prices(5.00, 25.00, 0.50),
    "claude-sonnet-5-5": Prices(2.00, 10.00, 0.10),
    "claude-sonnet-5": Prices(2.00, 10.00, 0.20),
    "claude-haiku-5-5": Prices(0.10, 0.50, 0.01),
}
_MOST_EXPENSIVE = max(PRICES.values(), key=lambda p: p.output)


def prices_for(model: str | None) -> Prices:
    """The prices of a model; the most expensive listed ones for an unknown model."""
    return PRICES.get(model or "", _MOST_EXPENSIVE)


@dataclass
class Usage:
    """Tokens of one or more requests, split the way they are billed."""

    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def of(cls, response: Any) -> Usage:
        """Read the usage of an API response (missing fields count as zero)."""
        usage = getattr(response, "usage", None)

        def get(name: str) -> int:
            return int(getattr(usage, name, 0) or 0) if usage is not None else 0

        return cls(
            input_tokens=get("input_tokens"),
            cache_write_tokens=get("cache_creation_input_tokens"),
            cache_read_tokens=get("cache_read_input_tokens"),
            output_tokens=get("output_tokens"),
        )

    def cost(self, prices: Prices) -> float:
        """What these tokens cost, in US dollars."""
        return (
            self.input_tokens * prices.input
            + self.cache_write_tokens * prices.cache_write
            + self.cache_read_tokens * prices.cache_read
            + self.output_tokens * prices.output
        ) / _MILLION

    def add(self, other: Usage) -> None:
        """Add another request's tokens to these."""
        self.input_tokens += other.input_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.output_tokens += other.output_tokens


def worst_request_cost(prices: Prices, input_tokens: int, max_tokens: int) -> float:
    """The most one request can cost: all input written to the cache, full output."""
    return (input_tokens * prices.cache_write + max_tokens * prices.output) / _MILLION
