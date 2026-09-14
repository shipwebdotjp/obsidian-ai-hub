"""Structured deviation self-report protocol for child runs.

Child Agent/Coding runs are instructed to stop out-of-plan work and emit a
``<deviation_request>{...}</deviation_request>`` block instead. The adapter
parses the final child text for that block and raises ``DeviationReported``;
unreported deviations are never detected by the parent.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

DEVIATION_TAG = "deviation_request"
DEVIATION_PATTERN = re.compile(
    r"<deviation_request>(.*?)</deviation_request>", re.DOTALL
)

DEVIATION_INSTRUCTION = (
    "Plan外のCapability、対象、または副作用が必要になった場合は、その作業を"
    "実行せずに停止し、理由と必要な追加Stepを次の形式でだけ出力してください:\n"
    '<deviation_request>{"reason": "理由", "steps": '
    '[{"capability_key": "...", "title": "...", "target": {...}, '
    '"inputs": {...}, "side_effects": "..."}]}</deviation_request>'
)


def parse_deviation_report(text: str) -> dict[str, Any] | None:
    """Return ``{"reason": str, "steps": [...]}`` when the tag is present."""
    match = DEVIATION_PATTERN.search(text or "")
    if match is None:
        return None
    try:
        report = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid deviation_request payload: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError("deviation_request payload must be an object.")
    reason = report.get("reason")
    steps = report.get("steps")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("deviation_request requires a non-blank reason.")
    if not isinstance(steps, list) or not steps:
        raise ValueError("deviation_request requires a non-empty steps list.")
    return {"reason": reason.strip(), "steps": steps}


def build_revised_plan(
    plan_inner: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Append reported steps to a copy of the saved plan inner dict.

    Reported steps are untrusted child LLM output: capability keys must be in
    the code-defined catalog and target/inputs must be objects. Approval stays
    human, but injection (e.g. ``run_shell``) is refused here, not at review.
    """
    from obsidian_ai_hub.tasks.capabilities import CAPABILITY_DEFINITIONS

    allowed = {d.key for d in CAPABILITY_DEFINITIONS}
    for index, step in enumerate(report["steps"]):
        if not isinstance(step, dict):
            raise ValueError(f"Reported step {index} must be an object.")
        key = step.get("capability_key")
        if key not in allowed:
            raise ValueError(f"Reported step {index} uses unknown capability '{key}'.")
        if not isinstance(step.get("target"), dict) or not isinstance(
            step.get("inputs"), dict
        ):
            raise ValueError(f"Reported step {index} target/inputs must be objects.")
    revised = copy.deepcopy(plan_inner)
    existing = revised.get("steps")
    if not isinstance(existing, list):
        raise ValueError("Saved plan has no steps list.")
    existing.extend(report["steps"])
    return revised


def tail_text(text: str, limit: int = 1000) -> str:
    """Keep the tail of a child result for the Task summary."""
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]
