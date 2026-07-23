from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class QuestionDraft:
    """Template for creating a question in a question set."""
    question_key: str
    question_type: str
    title: Optional[str] = None
    prompt: Optional[str] = None
    choices: Optional[list[Any]] = None
    is_required: int = 1
    sequence: int = 0
    context: Optional[dict[str, Any]] = None
    expires_at: Optional[str] = None

    def to_question_data(self) -> dict[str, Any]:
        """Convert to the dict format expected by register_run_and_questions."""
        q = {
            "question_key": self.question_key,
            "question_type": self.question_type,
            "display_text": self.prompt or self.title or "",
            "choices": self.choices,
            "is_required": self.is_required,
            "sequence": self.sequence,
            "title": self.title,
            "prompt": self.prompt,
            "context_json": self.context,
            "expires_at": self.expires_at,
        }
        return q
