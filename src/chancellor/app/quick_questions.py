"""Ready-made questions the panel hands to Claude Desktop (UI_DESIGN, build order step 5).

Each question has a short button label and the full prompt that is copied to the
clipboard. The prompts name what to look at, so Claude reaches for the right
Chancellor tools (MCP) on the first try instead of guessing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class QuickQuestion:
    """One button in the panel.

    Attributes:
        id: Stable identifier the page sends back.
        label: Button text.
        prompt: What is copied for Claude Desktop.
    """

    id: str
    label: str
    prompt: str

    def to_dict(self) -> dict[str, str]:
        """Plain values for the page."""
        return asdict(self)


QUICK_QUESTIONS: tuple[QuickQuestion, ...] = (
    QuickQuestion(
        "campaign",
        "How is my campaign going?",
        "How is my campaign going? Read my latest save with the Chancellor tools and give "
        "me the three things that most need my attention, with the numbers behind them.",
    ),
    QuickQuestion(
        "expand",
        "Where should I expand next?",
        "Where should I expand next? Check my expansion targets, their war odds and the "
        "coalition risk, and recommend one target with the reasons and the risks.",
    ),
    QuickQuestion(
        "threats",
        "What are the biggest threats?",
        "What are the biggest threats to my country right now? Look at my rivals, the "
        "great powers and their alliances, coalitions and truces that end soon.",
    ),
    QuickQuestion(
        "goals",
        "What should I aim for next?",
        "What should I aim for in the next ten to twenty years? Use my missions and the "
        "formable nations I can see, and give me a prioritised plan.",
    ),
)


def find_question(question_id: str) -> QuickQuestion | None:
    """The quick question with this id, or ``None``."""
    return next((q for q in QUICK_QUESTIONS if q.id == question_id), None)
