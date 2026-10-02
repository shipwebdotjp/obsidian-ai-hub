"""Adapter for Gmail capabilities (``gmail_create_draft``).

Executes ``gmail_create_draft`` with stable action request keys and
at-most-once idempotency ledger enforcement for both Workflow and Task Agent.
Uncertain API outcomes, receipt persistence failures, and input hash mismatches
transition to ``needs_attention`` without retries or duplicate draft creation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from obsidian_ai_hub.gmail.auth import GmailAuthError
from obsidian_ai_hub.gmail.client import GmailDraftDispatchError, GmailService
from obsidian_ai_hub.gmail.store import (
    DraftRequestHashMismatchError,
    DraftRequestPendingOrUnknownError,
)
from obsidian_ai_hub.tasks.execution import StepResult

logger = logging.getLogger(__name__)


class GmailDraftAdapter:
    """Execute saved plan steps backed by GmailService for gmail_create_draft."""

    def execute_step(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> StepResult:
        from obsidian_ai_hub.tasks.capability_schemas import (
            validate_capability_inputs,
        )
        from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

        capability_key = str(step.get("capability_key"))
        definition = {d.key: d for d in get_capability_definitions()}.get(
            capability_key
        )
        if definition is None or definition.adapter_kind != "gmail":
            raise ValueError(
                f"Capability '{capability_key}' is not a Gmail capability."
            )

        inputs = step.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError(
                f"Step {step_index} inputs must be an object, got {type(inputs).__name__}."
            )

        # Pre-dispatch input validation. Validation errors raise ValueError
        # (normal node/task failure before any external API call).
        try:
            validated_inputs = validate_capability_inputs(capability_key, inputs)
        except ValueError as exc:
            raise ValueError(f"Step {step_index} {exc}") from exc

        # Derive stable request key per logical action
        workflow_run_id = task.get("workflow_run_id")
        workflow_activation_id = task.get("workflow_activation_id")

        if workflow_run_id and workflow_activation_id:
            request_key = f"gmail_draft:wf:{workflow_run_id}:{workflow_activation_id}"
        else:
            task_id = task.get("task_id", "")
            plan_id = plan.get("plan_id") or task.get("current_plan_id") or "plan"
            request_key = f"gmail_draft:task:{task_id}:{plan_id}:{step_index}"

        mode = str(validated_inputs.get("mode") or "")
        body_text = str(validated_inputs.get("body_text") or "")
        to = validated_inputs.get("to")
        cc = validated_inputs.get("cc")
        bcc = validated_inputs.get("bcc")
        subject = validated_inputs.get("subject")
        reply_to_message_id = validated_inputs.get("reply_to_message_id")
        reply_all = bool(validated_inputs.get("reply_all", False))

        srv = GmailService()

        try:
            res = srv.create_draft(
                mode=mode,
                body_text=body_text,
                request_key=request_key,
                to=to,
                cc=cc,
                bcc=bcc,
                subject=subject,
                reply_to_message_id=reply_to_message_id,
                reply_all=reply_all,
            )
        except DraftRequestHashMismatchError as exc:
            existing = exc.existing or {}
            output = {
                "status": existing.get("status") or "unknown",
                "request_key": request_key,
                "gmail_draft_id": existing.get("gmail_draft_id"),
                "gmail_message_id": existing.get("gmail_message_id"),
                "gmail_thread_id": existing.get("gmail_thread_id"),
                "reused_receipt": False,
                "receipt_persisted": True,
            }
            return StepResult(
                step_index=step_index,
                capability_key=capability_key,
                summary=json.dumps(output, ensure_ascii=False),
                output=output,
                needs_attention=True,
                attention_reason="input_hash_mismatch",
                error=f"Input hash mismatch for request key '{request_key}'. Execution halted without calling Gmail API.",
            )
        except DraftRequestPendingOrUnknownError as exc:
            existing = exc.existing or {}
            output = {
                "status": existing.get("status") or "unknown",
                "request_key": request_key,
                "gmail_draft_id": existing.get("gmail_draft_id"),
                "gmail_message_id": existing.get("gmail_message_id"),
                "gmail_thread_id": existing.get("gmail_thread_id"),
                "reused_receipt": False,
                "receipt_persisted": True,
            }
            return StepResult(
                step_index=step_index,
                capability_key=capability_key,
                summary=json.dumps(output, ensure_ascii=False),
                output=output,
                needs_attention=True,
                attention_reason="pending_or_unknown_request",
                error=f"Draft request '{request_key}' is in status '{existing.get('status')}'. Automatic re-execution blocked.",
            )
        except GmailDraftDispatchError as exc:
            # Dispatch error or uncertain API call outcome
            logger.exception("gmail_create_draft dispatch failed for key %s", request_key)
            output = {
                "status": "unknown",
                "request_key": request_key,
                "gmail_draft_id": None,
                "gmail_message_id": None,
                "gmail_thread_id": None,
                "reused_receipt": False,
                "receipt_persisted": False,
            }
            return StepResult(
                step_index=step_index,
                capability_key=capability_key,
                summary=json.dumps(output, ensure_ascii=False),
                output=output,
                needs_attention=True,
                attention_reason="uncertain_outcome",
                error=f"Gmail API dispatch failed or returned an uncertain outcome: {exc.original_exception}",
            )

        # Check local receipt persistence
        if res.get("receipt_persisted") is False:
            return StepResult(
                step_index=step_index,
                capability_key=capability_key,
                summary=json.dumps(res, ensure_ascii=False),
                output=res,
                needs_attention=True,
                attention_reason="receipt_persistence_failed",
                error="Gmail draft created successfully, but local receipt persistence failed.",
            )

        return StepResult(
            step_index=step_index,
            capability_key=capability_key,
            summary=json.dumps(res, ensure_ascii=False),
            output=res,
            needs_attention=False,
        )
