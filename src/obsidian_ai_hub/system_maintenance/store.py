"""Persistence for system maintenance failure findings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from obsidian_ai_hub.database import get_db_connection

STATUS_OPEN = "open"
STATUS_PROPOSED = "proposed"
STATUS_CODING_CREATED = "coding_created"
STATUS_DISMISSED = "dismissed"
STATUS_RESOLVED = "resolved"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_findings(
    collected: Iterable[Mapping[str, Any]],
    *,
    resolve_missing_runs: int,
    now_iso: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Upsert observed findings and age out unseen ones.

    A finding unseen for ``resolve_missing_runs`` consecutive syncs becomes
    ``resolved``. When a resolved fingerprint reappears it starts a new
    incident as ``open`` with cleared references. Returns the stored rows for
    the fingerprints observed in this pass.
    """
    now = now_iso or _now_iso()
    collected_by_fp = {str(f["fingerprint"]): f for f in collected}
    conn = get_db_connection()
    try:
        with conn:
            rows = {
                row["fingerprint"]: dict(row)
                for row in conn.execute("SELECT * FROM system_maintenance_findings;")
            }

            for fp, finding in collected_by_fp.items():
                kind = str(finding.get("kind") or "command")
                label = str(finding.get("label") or "")
                exception_type = finding.get("exception_type")
                first_seen = str(finding.get("first_seen_at") or now)
                last_seen = str(finding.get("last_seen_at") or now)
                occurrence = int(finding.get("occurrence_count") or 1)
                row = rows.get(fp)
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO system_maintenance_findings (
                            fingerprint, kind, label, exception_type, first_seen_at,
                            last_seen_at, occurrence_count, missing_count, status, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'open', ?);
                        """,
                        (
                            fp,
                            kind,
                            label,
                            exception_type,
                            first_seen,
                            last_seen,
                            occurrence,
                            now,
                        ),
                    )
                elif row["status"] == STATUS_RESOLVED:
                    conn.execute(
                        """
                        UPDATE system_maintenance_findings
                        SET kind = ?, label = ?, exception_type = ?,
                            first_seen_at = ?, last_seen_at = ?,
                            occurrence_count = ?, missing_count = 0,
                            status = 'open', hitl_run_id = NULL, coding_run_id = NULL,
                            updated_at = ?
                        WHERE fingerprint = ?;
                        """,
                        (
                            kind,
                            label,
                            exception_type,
                            first_seen,
                            last_seen,
                            occurrence,
                            now,
                            fp,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE system_maintenance_findings
                        SET kind = ?, label = ?, exception_type = ?,
                            last_seen_at = ?, occurrence_count = ?, missing_count = 0,
                            updated_at = ?
                        WHERE fingerprint = ?;
                        """,
                        (kind, label, exception_type, last_seen, occurrence, now, fp),
                    )

            for fp, row in rows.items():
                if fp in collected_by_fp or row["status"] == STATUS_RESOLVED:
                    continue
                missing = int(row["missing_count"] or 0) + 1
                if missing >= resolve_missing_runs:
                    conn.execute(
                        "UPDATE system_maintenance_findings SET missing_count = ?, "
                        "status = 'resolved', updated_at = ? WHERE fingerprint = ?;",
                        (missing, now, fp),
                    )
                else:
                    conn.execute(
                        "UPDATE system_maintenance_findings SET missing_count = ?, "
                        "updated_at = ? WHERE fingerprint = ?;",
                        (missing, now, fp),
                    )

            if not collected_by_fp:
                return {}
            placeholders = ",".join("?" for _ in collected_by_fp)
            stored = {
                row["fingerprint"]: dict(row)
                for row in conn.execute(
                    "SELECT * FROM system_maintenance_findings "
                    f"WHERE fingerprint IN ({placeholders});",
                    tuple(collected_by_fp),
                )
            }
            return stored
    finally:
        conn.close()


def mark_proposed(
    fingerprints: Iterable[str], hitl_run_id: str, *, now_iso: Optional[str] = None
) -> None:
    now = now_iso or _now_iso()
    conn = get_db_connection()
    try:
        with conn:
            conn.executemany(
                "UPDATE system_maintenance_findings SET status = 'proposed', "
                "hitl_run_id = ?, updated_at = ? WHERE fingerprint = ?;",
                [(hitl_run_id, now, fp) for fp in fingerprints],
            )
    finally:
        conn.close()


def mark_dismissed(fingerprint: str, *, now_iso: Optional[str] = None) -> None:
    now = now_iso or _now_iso()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE system_maintenance_findings SET status = 'dismissed', "
                "updated_at = ? WHERE fingerprint = ?;",
                (now, fingerprint),
            )
    finally:
        conn.close()


def mark_coding_created(
    fingerprint: str,
    coding_run_id: Optional[str],
    *,
    now_iso: Optional[str] = None,
) -> None:
    now = now_iso or _now_iso()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE system_maintenance_findings SET status = 'coding_created', "
                "coding_run_id = ?, updated_at = ? WHERE fingerprint = ?;",
                (coding_run_id, now, fingerprint),
            )
    finally:
        conn.close()


def reopen_finding(fingerprint: str, *, now_iso: Optional[str] = None) -> None:
    now = now_iso or _now_iso()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE system_maintenance_findings SET status = 'open', "
                "updated_at = ? WHERE fingerprint = ?;",
                (now, fingerprint),
            )
    finally:
        conn.close()


def recover_pending_findings(*, now_iso: Optional[str] = None) -> int:
    """Reopen findings whose lifecycle pointer never became usable.

    A ``proposed`` finding whose HITL run is missing, failed, or cancelled, and
    a ``coding_created`` finding without a coding run id, are returned to
    ``open`` so the next diagnosis run can propose them again. Findings with a
    recorded coding run id are left alone even if the run row is later pruned.
    """
    now = now_iso or _now_iso()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                UPDATE system_maintenance_findings
                SET status = 'open', hitl_run_id = NULL, updated_at = ?
                WHERE status = 'proposed'
                  AND (
                    hitl_run_id IS NULL
                    OR NOT EXISTS (
                        SELECT 1 FROM hitl_runs WHERE hitl_runs.run_id = system_maintenance_findings.hitl_run_id
                    )
                    OR hitl_run_id IN (
                        SELECT run_id FROM hitl_runs WHERE status IN ('failed', 'cancelled')
                    )
                  );
                """,
                (now,),
            )
            recovered = cur.rowcount
            cur = conn.execute(
                """
                UPDATE system_maintenance_findings
                SET status = 'open', updated_at = ?
                WHERE status = 'coding_created' AND coding_run_id IS NULL;
                """,
                (now,),
            )
            recovered += cur.rowcount
            return recovered
    finally:
        conn.close()
