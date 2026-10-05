from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.models import (
    MEMORY_COLUMNS,
    DedupReassessmentRequiredError,
    _validate_date_str,
    _validate_edit_payload,
    coerce_injection_mode_for_approval,
    compute_memory_fingerprint,
    deserialize_memory,
    get_current_timestamp,
    merge_evidence,
    merge_topics_and_tags,
    normalize_stability,
    serialize_memory,
    update_target_with_candidate_data,
    validate_injection_mode_for_memory,
)
from obsidian_ai_hub.memory.store import log_memory_event
from obsidian_ai_hub.memory.projection import project_approved_memories
from obsidian_ai_hub.retrieval import memory_adapter as _retrieval_sync

logger = logging.getLogger(__name__)

_REASSESSING_IDS: set[str] = set()
_REASSESSING_LOCK = threading.Lock()


class ReassessConflictError(Exception):
    """Raised when reassessment is already running for a candidate memory."""
    pass


def reassess_candidate_memory(memory_id: str) -> dict:
    """
    Re-assess a candidate memory using LLM dedup assessment.

    - Rejects concurrent calls using _REASSESSING_IDS.
    - Restricted to candidate memories that are not clean 'ready'.
    - Updates proposals and target fingerprints without auto-applying merges/replacements.
    - Validates target status & fingerprint right before saving.
    - Logs audit events: dedup_reassessment_requested, dedup_reassessment_succeeded/failed.
    """
    from obsidian_ai_hub.utils.embeddings import get_embedder
    from obsidian_ai_hub.memory.dedup import run_deduplication, perform_dedup_assessment_llm
    from obsidian_ai_hub.memory.store import load_all_memories, get_memory_events

    with _REASSESSING_LOCK:
        if memory_id in _REASSESSING_IDS:
            raise ReassessConflictError("Reassessment operation already in progress for this memory")
        _REASSESSING_IDS.add(memory_id)

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
            row = cursor.fetchone()
            if row is None:
                raise LookupError(f"Memory not found: {memory_id}")

            cand = deserialize_memory(dict(row))
            if cand.get("status") != "candidate":
                raise ValueError(f"Memory {memory_id} is not a candidate (current status: {cand.get('status')})")

            rev_state = cand.get("review_state") or "ready"
            if rev_state == "ready":
                raise ValueError("Candidate is already ready; reassessment is not applicable")

            log_memory_event(
                event_type="dedup_reassessment_requested",
                memory_id=memory_id,
                previous_status="candidate",
                new_status="candidate",
                reason="手動操作: 再判定リクエストを受理しました",
                conn=conn,
                actor="user",
            )
            conn.commit()
            orig_updated_at = cand.get("updated_at")
        finally:
            conn.close()

        embedder = get_embedder()
        all_mems = load_all_memories()
        approved_mems = [m for m in all_mems if m.get("status") == "approved"]

        suggestions = run_deduplication(cand, approved_mems, embedder=embedder)
        cand["dedup_suggestions"] = suggestions

        if not suggestions:
            cand["dedup_assessment"] = {
                "decision": "new",
                "reason": "再判定の結果、類似・重複する記憶が見つかりませんでした。",
                "reassessment_required": False,
            }
        else:
            perform_dedup_assessment_llm([cand], approved_mems)
            assessment = cand.get("dedup_assessment") or {}
            if assessment.get("decision") in ("merge", "supersede", "new"):
                assessment["reassessment_required"] = False
                assessment["reassessment_reason"] = None
            else:
                assessment["reassessment_required"] = True

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
            fresh_cand_row = cursor.fetchone()
            if fresh_cand_row is None:
                raise LookupError(f"Memory not found: {memory_id}")
            fresh_cand = deserialize_memory(dict(fresh_cand_row))
            if fresh_cand.get("status") != "candidate":
                raise ReassessConflictError(
                    f"Candidate {memory_id} status changed during reassessment "
                    f"(current: {fresh_cand.get('status')})"
                )
            if fresh_cand.get("updated_at") != orig_updated_at:
                # Candidate was updated during the LLM window: discard LLM result,
                # keep reassessment-required state and record audit reason.
                cand = fresh_cand
                mismatch_reason = "候補が判定処理中に更新されました"
            else:
                target_id = cand.get("dedup_assessment", {}).get("target_memory_id") if isinstance(cand.get("dedup_assessment"), dict) else None
                target_fp = cand.get("dedup_assessment", {}).get("target_fingerprint") if isinstance(cand.get("dedup_assessment"), dict) else None
                decision = cand.get("dedup_assessment", {}).get("decision") if isinstance(cand.get("dedup_assessment"), dict) else None

                mismatch_reason = None
                if decision in ("merge", "supersede") and target_id:
                    cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (target_id,))
                    t_row = cursor.fetchone()
                    if t_row is None:
                        mismatch_reason = "対象記憶が存在しません"
                    else:
                        t_mem = deserialize_memory(dict(t_row))
                        if t_mem.get("status") != "approved":
                            mismatch_reason = "対象記憶が承認済み状態ではありません"
                        else:
                            current_fp = compute_memory_fingerprint(t_mem)
                            if target_fp and current_fp != target_fp:
                                mismatch_reason = "対象記憶が判定処理中に変更されました"

            if mismatch_reason:
                cand["dedup_assessment"] = {
                    "decision": "failed",
                    "reason": f"保存前の不一致検証失敗: {mismatch_reason}",
                    "reassessment_required": True,
                    "reassessment_reason": mismatch_reason,
                    "failure_kind": "response_invalid",
                }
                event_type = "dedup_reassessment_failed"
                event_reason = f"再判定保存直前の不一致検証失敗: {mismatch_reason}"
            else:
                if isinstance(cand.get("dedup_assessment"), dict) and cand.get("dedup_assessment", {}).get("decision") == "failed":
                    event_type = "dedup_reassessment_failed"
                    event_reason = cand.get("dedup_assessment", {}).get("reason") or "LLM再判定に失敗しました"
                else:
                    event_type = "dedup_reassessment_succeeded"
                    event_reason = "再判定処理が正常に完了しました"

            cand["updated_at"] = get_current_timestamp()

            db_row = serialize_memory(cand)
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE memories SET dedup_suggestions = ?, dedup_assessment = ?, "
                    "updated_at = ? WHERE memory_id = ? AND status = 'candidate'",
                    (
                        db_row.get("dedup_suggestions"),
                        db_row.get("dedup_assessment"),
                        db_row.get("updated_at"),
                        memory_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ReassessConflictError(
                        f"Candidate {memory_id} is no longer in candidate status"
                    )
                log_memory_event(
                    event_type=event_type,
                    memory_id=memory_id,
                    previous_status="candidate",
                    new_status="candidate",
                    reason=event_reason,
                    conn=conn,
                    actor="system",
                )

            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
            fresh_row = cursor.fetchone()
            if fresh_row is None:
                raise LookupError(f"Memory not found: {memory_id}")
            detail = deserialize_memory(dict(fresh_row))
            detail["events"] = get_memory_events(memory_id)
            return detail
        finally:
            conn.close()
    finally:
        with _REASSESSING_LOCK:
            _REASSESSING_IDS.discard(memory_id)


def _person_ids_from_people(people) -> list[str]:
    """Extract sorted-unique person_ids from an attached people list."""
    ids: set[str] = set()
    for p in people or []:
        if isinstance(p, dict) and p.get("person_id"):
            ids.add(p["person_id"])
        elif isinstance(p, str) and p:
            ids.add(p)
    return sorted(ids)


def review_memory(
    memory_id: str, action: str, new_content: Optional[str] = None
) -> bool:
    """
    Review candidate memory with specified action (approve, reject, edit).

    The retrieval vector write runs before the source DB write; a vector
    failure raises ``RetrievalSyncError`` and the memory is left unchanged.
    """
    from obsidian_ai_hub.retrieval.service import RetrievalSyncError

    logger.info(f"Reviewing memory {memory_id} with action {action}")

    if action not in ("approve", "reject", "edit"):
        logger.error(f"Unknown action: {action}")
        return False

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        row = cursor.fetchone()
        if row is None:
            logger.error(f"Memory with ID {memory_id} not found")
            return False

        if action == "edit" and not new_content:
            logger.error("Content is required for edit action")
            return False

        target = deserialize_memory(dict(row))
        prev_status = target.get("status")
        if prev_status == "superseded":
            logger.error(f"Cannot review a superseded memory: {memory_id}")
            return False
        timestamp_now = get_current_timestamp()
        old_snapshot = dict(target)

        if action == "approve":
            if target.get("status") != "candidate":
                logger.error(f"Cannot approve memory {memory_id} with status {target.get('status')}")
                raise ValueError("Only candidates can be approved")
            rev_state = target.get("review_state")
            if rev_state != "ready":
                logger.error(f"Cannot approve candidate {memory_id} in review_state {rev_state}")
                raise ValueError(f"Direct approval is only allowed for 'ready' candidates (current: {rev_state})")

            target["status"] = "approved"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now
            coerce_injection_mode_for_approval(target)
            event_type, new_status, changes = "approved", "approved", None
        elif action == "reject":
            target["status"] = "rejected"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now
            event_type, new_status, changes = "rejected", "rejected", None
        else:  # edit
            before_content = target.get("content", "")
            target["content"] = new_content
            target["status"] = "approved"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now
            coerce_injection_mode_for_approval(target)
            event_type, new_status = "edited", "approved"
            changes = {"content": {"before": before_content, "after": new_content}}

        post_state = target if new_status == "approved" else None
        try:
            prepared = _retrieval_sync.prepare_many({memory_id: post_state})
        except RetrievalSyncError:
            logger.error(
                f"Retrieval sync failed; memory {memory_id} left unchanged"
            )
            raise

        try:
            db_row = serialize_memory(target)
            set_clause = ", ".join(
                f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
            )
            values = [
                db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
            ] + [memory_id]
            conn.execute(
                f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
            )

            log_memory_event(
                event_type=event_type,
                memory_id=memory_id,
                previous_status=prev_status,
                new_status=new_status,
                changes=changes,
                conn=conn,
            )
            _retrieval_sync.apply_many_catalog_write(conn, prepared)
            conn.commit()
        except Exception:
            _retrieval_sync.restore_many({memory_id: old_snapshot})
            raise
    finally:
        conn.close()

    # Re-project approved memories markdown
    project_approved_memories()
    return True


def renew_memory(memory_id: str, payload: dict) -> dict:
    """
    Reactivate an expired memory by setting status='approved' and updating review dates.

    - Memory must have status='expired'.
    - review_due_at is required and must be in the future (> today JST).
    - valid_until (if set) must be in the future (> today JST).
    - Writes changes, logs 'renewed' audit event, syncs retrieval index & approved.md projection.
    """
    from datetime import timezone
    content = payload.get("content")
    review_due_at = payload.get("review_due_at")
    valid_until_present = "valid_until" in payload
    valid_until = payload.get("valid_until")
    reason = payload.get("reason") or "手動操作: 有効期限・定期確認日の更新による再承認"

    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    if not review_due_at or not isinstance(review_due_at, str):
        raise ValueError("review_due_at is required")
    _validate_date_str(review_due_at, "review_due_at")
    if review_due_at <= today:
        raise ValueError("review_due_at must be in the future")

    if valid_until_present and valid_until is not None:
        _validate_date_str(valid_until, "valid_until")
        if valid_until <= today:
            raise ValueError("valid_until must be in the future")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        row = cursor.fetchone()
        if row is None:
            raise LookupError(f"Memory not found: {memory_id}")

        target = deserialize_memory(dict(row))
        if target.get("status") != "expired":
            raise ValueError(f"Only expired memories can be renewed (current status: {target.get('status')})")

        timestamp_now = get_current_timestamp()
        old_snapshot = dict(target)

        if not valid_until_present:
            valid_until = target.get("valid_until")

        changes = {
            "status": {"before": "expired", "after": "approved"},
            "review_due_at": {"before": target.get("review_due_at"), "after": review_due_at},
            "valid_until": {"before": target.get("valid_until"), "after": valid_until},
        }

        if content and content.strip() and content != target.get("content"):
            changes["content"] = {"before": target.get("content"), "after": content}
            target["content"] = content

        target["status"] = "approved"
        target["review_due_at"] = review_due_at
        target["valid_until"] = valid_until
        target["reviewed_by"] = "user"
        target["reviewed_at"] = timestamp_now
        target["updated_at"] = timestamp_now
        coerce_injection_mode_for_approval(target)

        prepared = _retrieval_sync.prepare_many({memory_id: target})

        try:
            with conn:
                db_row = serialize_memory(target)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                ] + [memory_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                log_memory_event(
                    event_type="renewed",
                    memory_id=memory_id,
                    previous_status="expired",
                    new_status="approved",
                    changes=changes,
                    reason=reason,
                    conn=conn,
                    actor="user",
                )
                _retrieval_sync.apply_many_catalog_write(conn, prepared)
        except Exception:
            _retrieval_sync.restore_many({memory_id: old_snapshot})
            raise

        cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        fresh_row = cursor.fetchone()
        detail = deserialize_memory(dict(fresh_row))
        from obsidian_ai_hub.memory.store import get_memory_events
        detail["events"] = get_memory_events(memory_id)
    finally:
        conn.close()

    project_approved_memories()
    return detail


def update_memory_fields(memory_id: str, fields: dict) -> dict:
    """
    Web/API specific: edit EDITABLE_FIELDS and auto-approve.
    Returns {"found": bool, "updated": bool, "changes": dict, "memory": dict|None}.
    Raises ValueError on validation errors.
    """
    logger.info(f"Updating memory {memory_id} with fields {list(fields.keys())}")
    validated = _validate_edit_payload(dict(fields))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        row = cursor.fetchone()
        if row is None:
            return {"found": False, "updated": False, "changes": {}, "memory": None}

        target = deserialize_memory(dict(row))
        prev_status = target.get("status")
        if prev_status == "superseded":
            raise ValueError("Cannot edit a superseded memory")
        if prev_status == "expired":
            raise ValueError("Cannot edit an expired memory. Use renewal endpoint to reactivate it.")
        old_snapshot = dict(target)
        timestamp_now = get_current_timestamp()

        if "injection_mode" in validated:
            # Editing auto-approves, so eligibility is checked against the
            # post-write approved state.
            validate_injection_mode_for_memory(
                validated["injection_mode"],
                scope=target.get("scope") or "user",
                status="approved",
            )

        person_ids_update = None
        if "person_ids" in validated:
            person_ids_update = validated.pop("person_ids")

        changes = {}
        for k, v in validated.items():
            before = target.get(k)
            if before != v:
                changes[k] = {"before": before, "after": v}
                target[k] = v

        if person_ids_update is not None:
            from obsidian_ai_hub.memory.store import _attach_people_to_memories, set_memory_people
            # People linkage is written inside the transaction below.
            changes["person_ids"] = {"updated": person_ids_update}

        if not changes:
            return {
                "found": True,
                "updated": False,
                "changes": {},
                "memory": target,
            }

        target["status"] = "approved"
        target["reviewed_by"] = "user"
        target["reviewed_at"] = timestamp_now
        target["updated_at"] = timestamp_now
        coerce_injection_mode_for_approval(target)

        prepared = _retrieval_sync.prepare_many({memory_id: target})

        try:
            with conn:
                cursor = conn.cursor()
                if person_ids_update is not None:
                    from obsidian_ai_hub.memory.store import set_memory_people as _set_people
                    _set_people(memory_id, person_ids_update, conn=conn)

                db_row = serialize_memory(target)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                ] + [memory_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                log_memory_event(
                    event_type="edited",
                    memory_id=memory_id,
                    previous_status=prev_status,
                    new_status="approved",
                    changes=changes,
                    conn=conn,
                )
                _retrieval_sync.apply_many_catalog_write(conn, prepared)
        except Exception:
            _retrieval_sync.restore_many({memory_id: old_snapshot})
            raise

        # Re-attach people for the response (read-only, outside the txn).
        if person_ids_update is not None:
            from obsidian_ai_hub.memory.store import _attach_people_to_memories as _attach
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
            fresh = cursor.fetchone()
            if fresh is not None:
                target = deserialize_memory(dict(fresh))
                _attach(cursor, [target])
    finally:
        conn.close()

    project_approved_memories()
    return {"found": True, "updated": True, "changes": changes, "memory": target}


def batch_review_memories(memory_ids: list, action: str) -> dict:
    """
    Web/API specific: approve or reject multiple memories in one go.
    Returns {"updated": [ids...], "not_found": [ids...], "events": int}.
    action must be 'approve' or 'reject'.
    """
    if action not in ("approve", "reject"):
        raise ValueError("action must be 'approve' or 'reject'")
    if not isinstance(memory_ids, list) or not memory_ids:
        raise ValueError("memory_ids must be a non-empty list")
    if not all(isinstance(mid, str) for mid in memory_ids):
        raise ValueError("memory_ids must be strings")

    seen = set()
    deduped_ids = []
    for mid in memory_ids:
        if mid not in seen:
            seen.add(mid)
            deduped_ids.append(mid)
    memory_ids = deduped_ids

    new_status = "approved" if action == "approve" else "rejected"
    event_type = {"approve": "approved", "reject": "rejected"}[action]
    updated = []
    not_found = []
    event_count = 0

    conn = get_db_connection()
    try:
        # Phase 1: load all targets without writing.
        cursor = conn.cursor()
        timestamp_now = get_current_timestamp()
        targets: dict[str, dict] = {}
        prev_statuses: dict[str, object] = {}
        old_snapshots: dict[str, dict] = {}
        skipped = []
        for memory_id in memory_ids:
            cursor.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
            )
            row = cursor.fetchone()
            if row is None:
                not_found.append(memory_id)
                continue
            target = deserialize_memory(dict(row))
            prev_status = target.get("status")

            if action == "approve":
                if prev_status != "candidate" or target.get("review_state") != "ready":
                    skipped.append(memory_id)
                    continue
            elif action == "reject":
                if prev_status != "candidate":
                    skipped.append(memory_id)
                    continue

            old_snapshots[memory_id] = dict(target)
            target["status"] = new_status
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now
            if new_status == "approved":
                coerce_injection_mode_for_approval(target)
            targets[memory_id] = target
            prev_statuses[memory_id] = prev_status

        # Phase 2: vector writes before any source change.
        post_states = {
            mid: (t if new_status == "approved" else None)
            for mid, t in targets.items()
        }
        prepared = _retrieval_sync.prepare_many(post_states)

        # Phase 3: source + catalog in one transaction.
        try:
            with conn:
                cursor = conn.cursor()
                for memory_id, target in targets.items():
                    db_row = serialize_memory(target)
                    set_clause = ", ".join(
                        f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                    )
                    values = [
                        db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                    ] + [memory_id]
                    conn.execute(
                        f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                    )

                    log_memory_event(
                        event_type=event_type,
                        memory_id=memory_id,
                        previous_status=prev_statuses[memory_id],
                        new_status=new_status,
                        conn=conn,
                    )
                    event_count += 1
                    updated.append(memory_id)
                _retrieval_sync.apply_many_catalog_write(conn, prepared)
        except Exception:
            _retrieval_sync.restore_many(old_snapshots)
            raise
    finally:
        conn.close()

    if updated:
        project_approved_memories()

    return {
        "updated": updated,
        "not_found": not_found,
        "skipped": skipped,
        "events": event_count,
    }


def resolve_memory(
    candidate_id: str,
    action: str,
    target_memory_id: str,
    integrated_content: Optional[str] = None,
    switch_date: Optional[str] = None,
) -> tuple[dict, Optional[dict]]:
    """
    Resolve a candidate memory by keeping both, replacing, merging, or superseding the existing one.
    Returns (candidate, target).
    Raises ValueError on invalid state/inputs.
    """
    allowed_actions = (
        "keep_both",
        "replace_existing",
        "merge_existing",
        "supersede_existing",
    )
    if action not in allowed_actions:
        raise ValueError(f"action must be one of {allowed_actions}")

    conn = get_db_connection()
    prepared: dict | None = None
    old_snapshots: dict[str, dict] = {}
    try:
        with conn:
            cursor = conn.cursor()

            # Fetch candidate
            cursor.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (candidate_id,)
            )
            cand_row = cursor.fetchone()
            if cand_row is None:
                raise ValueError(f"Candidate memory not found: {candidate_id}")
            cand = deserialize_memory(dict(cand_row))

            if cand.get("status") != "candidate":
                raise ValueError(
                    f"Memory {candidate_id} is not in candidate status (current: {cand.get('status')})"
                )

            # Fetch target
            cursor.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (target_memory_id,)
            )
            target_row = cursor.fetchone()
            target = deserialize_memory(dict(target_row)) if target_row is not None else None

            if action in ("replace_existing", "merge_existing", "supersede_existing"):
                from obsidian_ai_hub.memory.store import _attach_people_to_memories

                reassessment_needed = False
                reassessment_reason = ""

                if target is None or target.get("status") != "approved":
                    reassessment_needed = True
                    reassessment_reason = "対象メモリが存在しないか、承認済み状態ではありません"
                else:
                    _attach_people_to_memories(cursor, [target, cand])
                    assessment = cand.get("dedup_assessment")
                    if not isinstance(assessment, dict) or not assessment.get("target_fingerprint"):
                        reassessment_needed = True
                        reassessment_reason = "対象メモリの指紋(fingerprint)が未保存です"
                    else:
                        current_target_fp = compute_memory_fingerprint(target)
                        if current_target_fp != assessment.get("target_fingerprint"):
                            reassessment_needed = True
                            reassessment_reason = "対象メモリが判定時点から変更されています"

                if reassessment_needed:
                    timestamp_now = get_current_timestamp()
                    assessment = cand.get("dedup_assessment")
                    if not isinstance(assessment, dict):
                        assessment = {
                            "decision": "failed",
                            "reason": "対象メモリの変更・不在・指紋未保存のため再判定が必要です",
                        }
                    assessment["reassessment_required"] = True
                    assessment["reassessment_reason"] = reassessment_reason
                    cand["dedup_assessment"] = assessment
                    cand["updated_at"] = timestamp_now

                    db_row_cand = serialize_memory(cand)
                    set_clause = ", ".join(
                        f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                    )
                    values = [
                        db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                    ] + [candidate_id]
                    conn.execute(
                        f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                    )

                    log_memory_event(
                        event_type="dedup_reassessment_required",
                        memory_id=candidate_id,
                        previous_status="candidate",
                        new_status="candidate",
                        reason=f"再判定要求へ移行: {reassessment_reason}",
                        conn=conn,
                    )
                    conn.commit()
                    raise DedupReassessmentRequiredError(
                        "対象メモリが判定時点から変更されたため、月次メモリ保守で再判定します。"
                    )

            if target is None:
                raise ValueError(f"Target memory not found: {target_memory_id}")
            if target.get("status") != "approved":
                raise ValueError(
                    f"Target memory {target_memory_id} is not in approved status"
                )

            # Validate target_memory_id matches dedup_assessment.target_memory_id
            assessment = cand.get("dedup_assessment")
            ass_target = (
                assessment.get("target_memory_id")
                if (assessment and isinstance(assessment, dict))
                else None
            )

            if ass_target:
                if ass_target != target_memory_id:
                    raise ValueError(
                        f"Target {target_memory_id} does not match LLM assessed target: {ass_target}"
                    )
            else:
                # Fallback to dedup_suggestions for backward compatibility/old data
                suggestions = cand.get("dedup_suggestions") or []
                target_ids = [
                    s.get("target_memory_id")
                    for s in suggestions
                    if s.get("target_memory_id")
                ]
                if target_memory_id not in target_ids:
                    raise ValueError(
                        f"Target {target_memory_id} is not in candidate's suggestions: {target_ids}"
                    )

            timestamp_now = get_current_timestamp()

            old_snapshots[candidate_id] = dict(cand)
            if target is not None:
                old_snapshots[target_memory_id] = dict(target)

            if action == "keep_both":
                cand["status"] = "approved"
                cand["reviewed_by"] = "user"
                cand["reviewed_at"] = timestamp_now
                cand["updated_at"] = timestamp_now
                coerce_injection_mode_for_approval(cand)

                prepared = _retrieval_sync.prepare_many({candidate_id: cand})

                db_row_cand = serialize_memory(cand)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                ] + [candidate_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                log_memory_event(
                    event_type="approved",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="approved",
                    reason="手動操作: 両方保持を選択して承認",
                    conn=conn,
                )
                _retrieval_sync.apply_many_catalog_write(conn, prepared)

            elif action == "replace_existing":
                # Save target state before update
                before_target = dict(target)
                before_person_ids = _person_ids_from_people(
                    before_target.get("people")
                )

                # Update target with candidate data
                target = update_target_with_candidate_data(
                    target, cand, reviewed_by="user"
                )
                coerce_injection_mode_for_approval(target)

                # Replace target's people linkage with the candidate's.
                # The candidate is rejected below, so without this sync a
                # candidate-only person association would vanish from memory.
                from obsidian_ai_hub.memory.store import (
                    _attach_people_to_memories as _attach_people,
                    set_memory_people as _set_people,
                )

                new_person_ids = _person_ids_from_people(cand.get("people"))
                if new_person_ids != before_person_ids:
                    _set_people(target_memory_id, new_person_ids, conn=conn)
                    _attach_people(cursor, [target])

                prepared = _retrieval_sync.prepare_many(
                    {target_memory_id: target, candidate_id: None}
                )

                # Save updated target
                db_row_target = serialize_memory(target)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row_target.get(col)
                    for col in MEMORY_COLUMNS
                    if col != "memory_id"
                ] + [target_memory_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                # Compute differences
                changes_diff = {}
                for field in MEMORY_COLUMNS:
                    if field in ["updated_at", "reviewed_at"]:
                        continue
                    before_val = before_target.get(field)
                    after_val = target.get(field)
                    if before_val != after_val:
                        changes_diff[field] = {"before": before_val, "after": after_val}
                after_person_ids = _person_ids_from_people(target.get("people"))
                if before_person_ids != after_person_ids:
                    changes_diff["person_ids"] = {
                        "before": before_person_ids,
                        "after": after_person_ids,
                    }

                # Log event for target
                log_memory_event(
                    event_type="edited",
                    memory_id=target_memory_id,
                    previous_status="approved",
                    new_status="approved",
                    changes=changes_diff,
                    reason=f"手動操作: 置換による更新（対象候補: {candidate_id}）",
                    conn=conn,
                )

                # Reject candidate
                cand["status"] = "rejected"
                cand["reviewed_by"] = "user"
                cand["reviewed_at"] = timestamp_now
                cand["updated_at"] = timestamp_now

                db_row_cand = serialize_memory(cand)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                ] + [candidate_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                # Log event for candidate
                log_memory_event(
                    event_type="rejected",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="rejected",
                    changes={
                        "relation": "supersedes",
                        "target_memory_id": target_memory_id,
                    },
                    reason="手動操作: 既存記憶の置換を選択して却下",
                    conn=conn,
                )
                _retrieval_sync.apply_many_catalog_write(conn, prepared)

            elif action == "merge_existing":
                if (
                    not integrated_content
                    or not isinstance(integrated_content, str)
                    or not integrated_content.strip()
                ):
                    raise ValueError(
                        "integrated_content is required for merge_existing action"
                    )

                # Save target state before update
                before_target = dict(target)
                before_person_ids = _person_ids_from_people(
                    before_target.get("people")
                )

                # Update target with candidate/integrated data
                target["content"] = integrated_content
                for field in [
                    "kind",
                    "valid_until",
                    "review_due_at",
                    "stability",
                    "sensitivity",
                    "extraction_confidence",
                    "contradicts",
                ]:
                    target[field] = cand.get(field)
                target["stability"] = normalize_stability(
                    cand.get("stability"), default="tentative"
                )
                target["topics"] = merge_topics_and_tags(
                    target.get("topics") or [], cand.get("topics") or []
                )
                target["tags"] = merge_topics_and_tags(
                    target.get("tags") or [], cand.get("tags") or []
                )
                target["evidence"] = merge_evidence(
                    target.get("evidence") or [], cand.get("evidence") or []
                )
                target["updated_at"] = timestamp_now
                target["reviewed_by"] = "user"
                target["reviewed_at"] = timestamp_now
                coerce_injection_mode_for_approval(target)

                # Union target and candidate people so a candidate-only person
                # association survives the merge (the candidate is rejected below).
                from obsidian_ai_hub.memory.store import (
                    _attach_people_to_memories as _attach_people,
                    set_memory_people as _set_people,
                )

                union_person_ids = sorted(
                    set(before_person_ids)
                    | set(_person_ids_from_people(cand.get("people")))
                )
                if union_person_ids != before_person_ids:
                    _set_people(target_memory_id, union_person_ids, conn=conn)
                    _attach_people(cursor, [target])

                prepared = _retrieval_sync.prepare_many(
                    {target_memory_id: target, candidate_id: None}
                )

                # Save updated target
                db_row_target = serialize_memory(target)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row_target.get(col)
                    for col in MEMORY_COLUMNS
                    if col != "memory_id"
                ] + [target_memory_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                # Compute differences
                changes_diff = {}
                for field in MEMORY_COLUMNS:
                    if field in ["updated_at", "reviewed_at"]:
                        continue
                    before_val = before_target.get(field)
                    after_val = target.get(field)
                    if before_val != after_val:
                        changes_diff[field] = {"before": before_val, "after": after_val}
                after_person_ids = _person_ids_from_people(target.get("people"))
                if before_person_ids != after_person_ids:
                    changes_diff["person_ids"] = {
                        "before": before_person_ids,
                        "after": after_person_ids,
                    }

                # Log event for target
                log_memory_event(
                    event_type="edited",
                    memory_id=target_memory_id,
                    previous_status="approved",
                    new_status="approved",
                    changes=changes_diff,
                    reason=f"手動操作: マージによる更新（対象候補: {candidate_id}）",
                    conn=conn,
                )

                # Reject candidate
                cand["status"] = "rejected"
                cand["reviewed_by"] = "user"
                cand["reviewed_at"] = timestamp_now
                cand["updated_at"] = timestamp_now

                db_row_cand = serialize_memory(cand)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                ] + [candidate_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                # Log event for candidate
                log_memory_event(
                    event_type="rejected",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="rejected",
                    changes={
                        "relation": "duplicate",
                        "target_memory_id": target_memory_id,
                    },
                    reason="手動操作: 既存記憶へのマージを選択して却下",
                    conn=conn,
                )
                _retrieval_sync.apply_many_catalog_write(conn, prepared)

            elif action == "supersede_existing":
                if not switch_date or not isinstance(switch_date, str):
                    raise ValueError(
                        "switch_date is required for supersede_existing action"
                    )
                try:
                    switch_dt = datetime.strptime(switch_date, "%Y-%m-%d")
                except ValueError:
                    raise ValueError("switch_date must be in YYYY-MM-DD format")

                # Validate switch_date > target valid_from
                old_valid_from = target.get("valid_from")
                if old_valid_from:
                    old_vf_dt = None
                    try:
                        old_vf_dt = datetime.strptime(old_valid_from, "%Y-%m-%d")
                    except ValueError:
                        pass
                    if old_vf_dt and switch_dt <= old_vf_dt:
                        raise ValueError(
                            f"switch_date ({switch_date}) must be strictly after existing valid_from ({old_valid_from})"
                        )

                predecessor_until_dt = switch_dt - timedelta(days=1)
                predecessor_until_str = predecessor_until_dt.strftime("%Y-%m-%d")

                # Save target and candidate states before update
                before_target = dict(target)
                before_cand = dict(cand)

                # Update old memory
                target["status"] = "superseded"
                target["valid_until"] = predecessor_until_str
                target["updated_at"] = timestamp_now

                # Vector write for the outgoing memory before any source change.
                prepared = _retrieval_sync.prepare_many({target_memory_id: None})

                db_row_target = serialize_memory(target)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row_target.get(col)
                    for col in MEMORY_COLUMNS
                    if col != "memory_id"
                ] + [target_memory_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                # Log event for target
                log_memory_event(
                    event_type="superseded",
                    memory_id=target_memory_id,
                    previous_status="approved",
                    new_status="superseded",
                    changes={
                        "valid_until": {
                            "before": before_target.get("valid_until"),
                            "after": predecessor_until_str,
                        },
                        "superseded_by": candidate_id,
                    },
                    reason=f"手動操作: 置換による終了（後継候補: {candidate_id}）",
                    conn=conn,
                )

                # Update new memory
                cand["status"] = "approved"
                cand["valid_from"] = switch_date
                cand["supersedes"] = target_memory_id
                cand["memory_key"] = target.get("memory_key")
                cand["reviewed_by"] = "user"
                cand["reviewed_at"] = timestamp_now
                cand["updated_at"] = timestamp_now
                coerce_injection_mode_for_approval(cand)

                # Vector write for the incoming memory before its source change.
                _cand_prepared = _retrieval_sync.prepare_many({candidate_id: cand})
                prepared.update(_cand_prepared)

                db_row_cand = serialize_memory(cand)
                set_clause = ", ".join(
                    f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                values = [
                    db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"
                ] + [candidate_id]
                conn.execute(
                    f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values
                )

                # Compute differences for candidate approved event
                cand_changes = {
                    "status": {"before": "candidate", "after": "approved"},
                    "valid_from": {
                        "before": before_cand.get("valid_from"),
                        "after": switch_date,
                    },
                    "supersedes": {
                        "before": before_cand.get("supersedes"),
                        "after": target_memory_id,
                    },
                }
                if before_cand.get("memory_key") != target.get("memory_key"):
                    cand_changes["memory_key"] = {
                        "before": before_cand.get("memory_key"),
                        "after": target.get("memory_key"),
                    }

                log_memory_event(
                    event_type="approved",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="approved",
                    changes=cand_changes,
                    reason=f"手動操作: 既存記憶 {target_memory_id} の後継として承認",
                    conn=conn,
                )
                _retrieval_sync.apply_many_catalog_write(conn, prepared)
    except Exception:
        if prepared is not None:
            _retrieval_sync.restore_many(old_snapshots)
        raise
    finally:
        conn.close()

    project_approved_memories()

    return cand, target


def delete_memory(memory_id: str) -> dict:
    """Completely delete a memory and its retrieval index entries.

    The Chroma delete runs before the source delete; a vector failure
    raises ``RetrievalSyncError`` and the memory is left untouched.
    """
    from obsidian_ai_hub.memory.store import _prune_dedup_suggestions

    conn = get_db_connection()
    was_approved = False
    events_deleted = 0
    target = None
    old_snapshot: dict | None = None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        row = cursor.fetchone()
        if row is None:
            return {
                "found": False,
                "deleted": False,
                "events_deleted": 0,
                "memory": None,
            }

        target = deserialize_memory(dict(row))
        old_snapshot = dict(target)
        was_approved = target.get("status") == "approved"

        # Chroma-first: never start the source delete on vector failure.
        _retrieval_sync.prepare_memory_delete(memory_id)

        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM memory_events WHERE memory_id = ?", (memory_id,)
                )
                events_deleted = cursor.rowcount

                _prune_dedup_suggestions(cursor, memory_id)
                cursor.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
                _retrieval_sync.apply_many_catalog_write(
                    conn, {memory_id: {"op": "delete"}}
                )
        except Exception:
            _retrieval_sync.restore_many({memory_id: old_snapshot})
            raise
    finally:
        conn.close()

    if was_approved:
        project_approved_memories()

    return {
        "found": True,
        "deleted": True,
        "events_deleted": events_deleted,
        "memory": target,
    }


def batch_delete_memories(memory_ids: list[str]) -> dict:
    from obsidian_ai_hub.memory.store import _prune_dedup_suggestions

    if not memory_ids:
        return {"deleted": [], "not_found": [], "events_deleted": 0}

    memory_ids = list(dict.fromkeys(memory_ids))
    conn = get_db_connection()
    deleted = []
    not_found = []
    total_events = 0
    had_approved = False

    try:
        # Phase 1: load targets without writing.
        cursor = conn.cursor()
        targets: dict[str, dict] = {}
        for mid in memory_ids:
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,))
            row = cursor.fetchone()
            if row is None:
                not_found.append(mid)
                continue
            targets[mid] = deserialize_memory(dict(row))

        # Phase 2: Chroma-first deletes; never start source deletes on failure.
        for mid in targets:
            _retrieval_sync.prepare_memory_delete(mid)
        prepared = {mid: {"op": "delete"} for mid in targets}

        # Phase 3: source + catalog in one transaction.
        try:
            with conn:
                cursor = conn.cursor()
                for mid, target in targets.items():
                    if target.get("status") == "approved":
                        had_approved = True

                    cursor.execute("DELETE FROM memory_events WHERE memory_id = ?", (mid,))
                    total_events += cursor.rowcount
                    cursor.execute("DELETE FROM memories WHERE memory_id = ?", (mid,))
                    deleted.append(mid)

                for mid in deleted:
                    _prune_dedup_suggestions(cursor, mid)
                _retrieval_sync.apply_many_catalog_write(conn, prepared)
        except Exception:
            _retrieval_sync.restore_many(dict(targets))
            raise
    finally:
        conn.close()

    if had_approved:
        project_approved_memories()

    return {"deleted": deleted, "not_found": not_found, "events_deleted": total_events}
