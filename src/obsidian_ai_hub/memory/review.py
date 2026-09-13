from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.models import (
    MEMORY_COLUMNS,
    _validate_edit_payload,
    deserialize_memory,
    get_current_timestamp,
    merge_evidence,
    merge_topics_and_tags,
    normalize_stability,
    serialize_memory,
    update_target_with_candidate_data,
)
from obsidian_ai_hub.memory.store import log_memory_event
from obsidian_ai_hub.memory.projection import project_approved_memories

logger = logging.getLogger(__name__)


def review_memory(
    memory_id: str, action: str, new_content: Optional[str] = None
) -> bool:
    """
    Review candidate memory with specified action (approve, reject, edit).
    """
    logger.info(f"Reviewing memory {memory_id} with action {action}")

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

        if action == "approve":
            target["status"] = "approved"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now

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
                event_type="approved",
                memory_id=memory_id,
                previous_status=prev_status,
                new_status="approved",
                conn=conn,
            )
            conn.commit()
        elif action == "reject":
            target["status"] = "rejected"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now

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
                event_type="rejected",
                memory_id=memory_id,
                previous_status=prev_status,
                new_status="rejected",
                conn=conn,
            )
            conn.commit()
        elif action == "edit":
            before_content = target.get("content", "")
            target["content"] = new_content
            target["status"] = "approved"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now

            changes = {"content": {"before": before_content, "after": new_content}}

            db_row = serialize_memory(target)
            set_clause = ", ".join(f"{col} = ?" for col in db_row if col != "memory_id")
            values = [db_row[col] for col in db_row if col != "memory_id"] + [memory_id]
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
            conn.commit()
        else:
            logger.error(f"Unknown action: {action}")
            return False
    finally:
        conn.close()

    # Re-project approved memories markdown
    project_approved_memories()
    return True


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
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
            row = cursor.fetchone()
            if row is None:
                return {"found": False, "updated": False, "changes": {}, "memory": None}

            target = deserialize_memory(dict(row))
            prev_status = target.get("status")
            if prev_status == "superseded":
                raise ValueError("Cannot edit a superseded memory")
            timestamp_now = get_current_timestamp()

            changes = {}
            for k, v in validated.items():
                before = target.get(k)
                if before != v:
                    changes[k] = {"before": before, "after": v}
                    target[k] = v

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

            db_row = serialize_memory(target)
            set_clause = ", ".join(f"{col} = ?" for col in db_row if col != "memory_id")
            values = [db_row[col] for col in db_row if col != "memory_id"] + [memory_id]
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
        with conn:
            cursor = conn.cursor()
            timestamp_now = get_current_timestamp()

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
                if prev_status == "superseded":
                    skipped.append(memory_id)
                    continue
                target["status"] = new_status
                target["reviewed_by"] = "user"
                target["reviewed_at"] = timestamp_now
                target["updated_at"] = timestamp_now

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
                    conn=conn,
                )
                event_count += 1
                updated.append(memory_id)
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
            if target_row is None:
                raise ValueError(f"Target memory not found: {target_memory_id}")
            target = deserialize_memory(dict(target_row))

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

            if action == "keep_both":
                cand["status"] = "approved"
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

                log_memory_event(
                    event_type="approved",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="approved",
                    reason="手動操作: 両方保持を選択して承認",
                    conn=conn,
                )

            elif action == "replace_existing":
                # Save target state before update
                before_target = dict(target)

                # Update target with candidate data
                target = update_target_with_candidate_data(
                    target, cand, reviewed_by="user"
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
    finally:
        conn.close()

    project_approved_memories()

    return cand, target


def delete_memory(memory_id: str) -> dict:
    from obsidian_ai_hub.memory.store import _prune_dedup_suggestions

    conn = get_db_connection()
    was_approved = False
    events_deleted = 0
    target = None
    try:
        with conn:
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
            was_approved = target.get("status") == "approved"

            cursor.execute(
                "DELETE FROM memory_events WHERE memory_id = ?", (memory_id,)
            )
            events_deleted = cursor.rowcount

            _prune_dedup_suggestions(cursor, memory_id)
            cursor.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
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
        with conn:
            cursor = conn.cursor()
            for mid in memory_ids:
                cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,))
                row = cursor.fetchone()
                if row is None:
                    not_found.append(mid)
                    continue

                target = deserialize_memory(dict(row))
                if target.get("status") == "approved":
                    had_approved = True

                cursor.execute("DELETE FROM memory_events WHERE memory_id = ?", (mid,))
                total_events += cursor.rowcount
                cursor.execute("DELETE FROM memories WHERE memory_id = ?", (mid,))
                deleted.append(mid)

            for mid in deleted:
                _prune_dedup_suggestions(cursor, mid)
    finally:
        conn.close()

    if had_approved:
        project_approved_memories()

    return {"deleted": deleted, "not_found": not_found, "events_deleted": total_events}
