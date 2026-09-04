"""Definition and input models for the ask_user system tool."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

RESERVED_CHOICE_VALUE = "other"


class ChoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(description="選択肢の識別キー (英数字/スネークケース)。'other' は予約値のため使用不可。")
    label: str = Field(min_length=1, description="画面表示ラベル。")
    description: Optional[str] = Field(default=None, description="選択肢の補足説明。")

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: str) -> str:
        clean = (v or "").strip()
        if not clean:
            raise ValueError("Choice value cannot be empty.")
        if clean == RESERVED_CHOICE_VALUE:
            raise ValueError(f"Choice value '{RESERVED_CHOICE_VALUE}' is reserved.")
        return clean


class AskUserQuestionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(description="質問の安定識別子 (例: 'q_confirm_scope', 'q_target_branch')。")
    question: str = Field(min_length=1, description="ユーザーに尋ねる質問文。")
    choices: List[ChoiceOption] = Field(
        min_length=1,
        description="選択肢のリスト。最低1個以上指定してください。",
    )

    @field_validator("question_id")
    @classmethod
    def validate_question_id(cls, v: str) -> str:
        clean = (v or "").strip()
        if not clean:
            raise ValueError("question_id cannot be empty.")
        return clean


class AskUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: List[AskUserQuestionItem] = Field(
        min_length=1,
        description="ユーザーへ確認する質問のリスト。複数の質問をまとめて指定できます。",
    )

    @model_validator(mode="after")
    def _unique_question_ids(self) -> "AskUserInput":
        ids = [q.question_id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question_id values must be unique.")
        return self


def normalize_question_choices(raw_choices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize choice list by appending fixed 'other' (自由入力) option.

    Skips malformed entries (non-dict, empty value) and duplicates so
    LLM-controlled input cannot crash the question UI.
    """
    out = []
    seen: set[str] = set()
    has_other = False
    for c in raw_choices:
        if not isinstance(c, dict):
            continue
        val = str(c.get("value") or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        if val == RESERVED_CHOICE_VALUE:
            has_other = True
        out.append(
            {
                "value": val,
                "label": str(c.get("label") or val),
                "description": c.get("description"),
            }
        )
    if not has_other:
        out.append(
            {
                "value": RESERVED_CHOICE_VALUE,
                "label": "その他（自由入力）",
                "description": "自由入力テキストで回答します。",
            }
        )
    return out


@tool(args_schema=AskUserInput)
def ask_user(questions: List[AskUserQuestionItem]) -> str:
    """会話内でユーザーに1つまたは複数の質問（要件定義、確認事項、選択肢）を行います。1回のターンで ask_user 単独の呼び出しのみ許可されます。呼び出すと会話は待機状態となり、ユーザーの回答後に再開します。"""
    # This tool is intercepted by the runtime before actual execution.
    # If invoked directly, return a status indicating pending user response.
    return '{"status": "waiting_user"}'


ask_user.name = "ask_user"  # type: ignore[attr-defined]
