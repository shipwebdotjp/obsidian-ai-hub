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


def validate_ask_user_questions(q_items: Any) -> Optional[str]:
    """Strictly validate LLM-produced ask_user questions.

    Returns an error message when invalid, else None. Invalid sets must
    bounce back as ToolMessage errors without creating a HITL run.
    """
    if not isinstance(q_items, list) or not q_items:
        return "ask_user requires a non-empty questions array."
    seen_qids: set[str] = set()
    for qi, q in enumerate(q_items):
        if not isinstance(q, dict):
            return f"ask_user questions[{qi}] must be an object."
        qid = str(q.get("question_id") or "").strip()
        qtext = str(q.get("question") or "").strip()
        if not qid or not qtext:
            return (
                f"ask_user questions[{qi}] requires non-empty "
                "question_id and question."
            )
        if qid in seen_qids:
            return f"Duplicate question_id '{qid}' in ask_user call."
        seen_qids.add(qid)
        ch = q.get("choices", [])
        if not isinstance(ch, list) or not ch:
            return (
                f"ask_user questions[{qi}] choices must be a non-empty list of objects."
            )
        if not all(isinstance(c, dict) for c in ch):
            return (
                f"ask_user questions[{qi}] choices must be a list of objects."
            )
        for ci, c in enumerate(ch):
            val = str(c.get("value") or "").strip()
            label = str(c.get("label") or "").strip()
            if not val:
                return (
                    f"ask_user questions[{qi}].choices[{ci}] requires non-empty value."
                )
            if val == RESERVED_CHOICE_VALUE:
                return (
                    f"ask_user questions[{qi}].choices[{ci}] value "
                    f"'{RESERVED_CHOICE_VALUE}' is reserved."
                )
            if not label:
                return (
                    f"ask_user questions[{qi}].choices[{ci}] requires non-empty label."
                )
    return None


def build_questions_data(q_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build HITL questions_data with normalized choices (appends fixed other)."""
    questions_data = []
    for idx, q_item in enumerate(q_items):
        q_id = q_item.get("question_id", f"q_{idx+1}")
        q_text = q_item.get("question", "")
        raw_choices = q_item.get("choices", [])
        norm_choices = normalize_question_choices(
            raw_choices if isinstance(raw_choices, list) else []
        )
        questions_data.append(
            {
                "question_key": q_id,
                "question_type": "single_choice",
                "display_text": q_text,
                "choices": norm_choices,
                "is_required": 1,
                "sequence": idx,
            }
        )
    return questions_data


def extract_qa_history(cp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return accumulated Q&A history from a checkpoint (backward compatible).

    v2 checkpoints carry ``qa_history`` (list of tool_call_id/ask_user_args/answers).
    v1 checkpoints carry only the latest ``tool_call_id``/``ask_user_args``/``answers``;
    they are adapted as a single-entry history.
    """
    raw_hist = cp.get("qa_history")
    if isinstance(raw_hist, list):
        out = []
        for entry in raw_hist:
            if not isinstance(entry, dict):
                continue
            tool_call_id = entry.get("tool_call_id")
            answers = entry.get("answers")
            if not tool_call_id or answers is None:
                continue
            out.append(
                {
                    "tool_call_id": tool_call_id,
                    "ask_user_args": entry.get("ask_user_args") or {},
                    "answers": answers,
                }
            )
        return out
    tool_call_id = cp.get("tool_call_id")
    answers = cp.get("answers")
    if tool_call_id and answers is not None:
        return [
            {
                "tool_call_id": tool_call_id,
                "ask_user_args": cp.get("ask_user_args") or {},
                "answers": answers,
            }
        ]
    return []


def build_resume_turns(cp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build ordered resume payloads from checkpoint history.

    Each item is ``{"tool_call_id": ..., "ask_user_args": ..., "payload": {"answers": ...}}``.
    """
    turns = []
    for entry in extract_qa_history(cp):
        answers = entry["answers"]
        payload = answers if isinstance(answers, dict) and "answers" in answers else {"answers": answers}
        turns.append(
            {
                "tool_call_id": entry["tool_call_id"],
                "ask_user_args": entry["ask_user_args"],
                "payload": payload,
            }
        )
    return turns


def carry_history_for_new_checkpoint(prior_cp: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Carry accumulated history into a new interruption checkpoint."""
    if not isinstance(prior_cp, dict):
        return []
    return extract_qa_history(prior_cp)


def append_answer_to_history(
    cp: Dict[str, Any], tool_call_id: str, ask_user_args: Dict[str, Any], formatted_answers: Dict[str, Any]
) -> Dict[str, Any]:
    """Return a checkpoint copy with the new answer appended to qa_history."""
    merged = dict(cp)
    merged["answers"] = formatted_answers
    hist = list(extract_qa_history(cp))
    hist.append(
        {
            "tool_call_id": tool_call_id,
            "ask_user_args": ask_user_args,
            "answers": formatted_answers,
        }
    )
    merged["qa_history"] = hist
    return merged


@tool(args_schema=AskUserInput)
def ask_user(questions: List[AskUserQuestionItem]) -> str:
    """会話内でユーザーに1つまたは複数の質問（要件定義、確認事項、選択肢）を行います。1回のターンで ask_user 単独の呼び出しのみ許可されます。呼び出すと会話は待機状態となり、ユーザーの回答後に再開します。"""
    # This tool is intercepted by the runtime before actual execution.
    # If invoked directly, return a status indicating pending user response.
    return '{"status": "waiting_user"}'


ask_user.name = "ask_user"  # type: ignore[attr-defined]
