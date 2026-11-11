"""Thin wrapper around the LLM API (Phase 2, extended with tool use in Phase 3)."""

from __future__ import annotations

from collections.abc import Iterator

from chancellor.config import Settings


class ChancellorClient:
    """Sends player questions to the LLM together with the current campaign context."""

    def __init__(self, settings: Settings) -> None:
        """Create a client.

        Args:
            settings: Resolved settings; ``api_key`` must be set.
        """
        self.settings = settings

    def ask(self, question: str, context: str) -> Iterator[str]:
        """Ask a question and stream the answer.

        The campaign ``context`` is sent as a cached system block so follow-up
        questions about the same save are cheap.

        Args:
            question: The player's question.
            context: Briefing produced by :mod:`chancellor.context.summarizer`.

        Yields:
            Chunks of the answer text as they arrive.
        """
        raise NotImplementedError
