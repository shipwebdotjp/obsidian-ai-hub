"""System maintenance diagnosis: collection, dedupe, diagnosis, and HITL flow."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.dispatcher import dispatch_runs, register_handler
from obsidian_ai_hub.hitl.service import submit_answer
from obsidian_ai_hub.system_maintenance import collector, proposals, store
from obsidian_ai_hub.system_maintenance.cli import run_system_maintenance_cli
from obsidian_ai_hub.system_maintenance.diagnosis import (
    parse_diagnosis_response,
    run_diagnosis,
)
from obsidian_ai_hub.system_maintenance.proposals import (
    register_maintenance_hitl_run,
    run_approved_system_maintenance,
)
from obsidian_ai_hub.utils import config


def _now_iso(offset_hours: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=offset_hours)).isoformat()


def _insert_command_run(
    conn,
    run_id: str,
    command: str = "uv run -m obsidian_ai_hub --merge-inbox",
    exception_type: str = "RuntimeError",
    exception_message: str = "boom 123",
    status: str = "failed",
    started_at: str | None = None,
) -> None:
    started = started_at or _now_iso()
    conn.execute(
        """
        INSERT INTO command_runs (
            run_id, command, args_json, started_at, finished_at, status,
            summary, exception_type, exception_message, traceback
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            run_id,
            command,
            "{}",
            started,
            started,
            status,
            None,
            exception_type if status != "running" else None,
            exception_message if status != "running" else None,
            f"Traceback for {run_id}",
        ),
    )


def _insert_llm_call(
    conn,
    call_id: str,
    run_id: str | None = None,
    provider: str = "openai",
    model: str = "gpt-test",
    exception_type: str = "TimeoutError",
    exception_message: str = "timed out 42",
    status: str = "failed",
    started_at: str | None = None,
) -> None:
    started = started_at or _now_iso()
    conn.execute(
        """
        INSERT INTO llm_call_logs (
            call_id, run_id, provider, model, temperature, max_tokens, prompt,
            response, started_at, finished_at, status, exception_type,
            exception_message, traceback
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            call_id,
            run_id,
            provider,
            model,
            0.7,
            1000,
            "prompt body should never reach the diagnosis prompt",
            None,
            started,
            started,
            status,
            exception_type if status != "running" else None,
            exception_message if status != "running" else None,
            f"Traceback for {call_id}",
        ),
    )


@pytest.fixture
def maintenance_project(tmp_path):
    git_repo = tmp_path / "maintenance_repo"
    git_repo.mkdir()
    subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=git_repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=git_repo, check=True
    )
    (git_repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=git_repo, check=True)

    conn = get_db_connection()
    cursor = conn.execute(
        """
        INSERT INTO projects (
            normalized_name, display_name, domain, status, project_path,
            created_at, updated_at
        ) VALUES ('maintenance-repo', 'Maintenance Repo', 'personal', 'active', ?,
                  datetime('now'), datetime('now'));
        """,
        (str(git_repo),),
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"project_id": project_id, "repo_path": str(git_repo)}


def test_fingerprint_normalizes_varying_ids():
    first = collector.compute_fingerprint(
        "command", "cmd", "RuntimeError", "failed at 2026-09-25T01:02:03Z id abcdef1234567890"
    )
    second = collector.compute_fingerprint(
        "command", "cmd", "RuntimeError", "failed at 2026-09-26T04:05:06Z id 0987654321fedcba"
    )
    other = collector.compute_fingerprint(
        "command", "cmd", "ValueError", "failed at 2026-09-26T04:05:06Z id 0987654321fedcba"
    )
    assert first == second
    assert first != other


def test_collect_bundles_llm_failures_into_command_finding():
    conn = get_db_connection()
    _insert_command_run(conn, "run_1", exception_message="boom 111")
    _insert_command_run(conn, "run_2", exception_message="boom 222")
    _insert_llm_call(conn, "call_related", run_id="run_1")
    _insert_llm_call(conn, "call_standalone", run_id=None)
    conn.commit()
    conn.close()

    findings = collector.collect_failure_findings(window_hours=24, stale_running_hours=1000)
    by_kind = {finding["kind"]: finding for finding in findings}
    assert set(by_kind) == {"command", "llm"}
    assert by_kind["command"]["occurrence_count"] == 2
    assert by_kind["command"]["related_llm_failures"][0]["call_id"] == "call_related"
    assert by_kind["llm"]["call_ids"] == ["call_standalone"]
    assert "prompt body" not in json.dumps(by_kind, ensure_ascii=False)


def test_sync_findings_resolves_and_reopens():
    conn = get_db_connection()
    _insert_command_run(conn, "run_1")
    conn.commit()
    conn.close()
    findings = collector.collect_failure_findings(window_hours=24, stale_running_hours=1000)

    stored = store.sync_findings(findings, resolve_missing_runs=2)
    fingerprint = findings[0]["fingerprint"]
    assert stored[fingerprint]["status"] == "open"

    store.sync_findings([], resolve_missing_runs=2)
    row = store.sync_findings([], resolve_missing_runs=2)
    assert row == {}
    conn = get_db_connection()
    row = dict(
        conn.execute(
            "SELECT * FROM system_maintenance_findings WHERE fingerprint = ?;",
            (fingerprint,),
        ).fetchone()
    )
    conn.close()
    assert row["status"] == "resolved"

    stored = store.sync_findings(findings, resolve_missing_runs=2)
    assert stored[fingerprint]["status"] == "open"
    assert stored[fingerprint]["coding_run_id"] is None


def test_collect_redacts_secrets_in_command_label():
    conn = get_db_connection()
    _insert_command_run(
        conn,
        "run_1",
        command="sync --api-key=supersecretvalue --target inbox",
        exception_message="failed",
    )
    conn.commit()
    conn.close()

    findings = collector.collect_failure_findings(window_hours=24, stale_running_hours=1000)
    assert len(findings) == 1
    assert "supersecretvalue" not in findings[0]["label"]
    assert "[REDACTED]" in findings[0]["label"]


def test_redact_secrets_handles_quoted_keys():
    text = "failed with {'password': 'hunter2xyz'} and {\"api_key\": \"abcdef123456\"}"
    redacted = collector.redact_secrets(text)
    assert "hunter2xyz" not in redacted
    assert "abcdef123456" not in redacted


def test_fingerprint_stable_across_varying_secrets():
    conn = get_db_connection()
    _insert_command_run(
        conn, "run_1", exception_message="auth failed: bearer abcdefghijk12345"
    )
    _insert_command_run(
        conn, "run_2", exception_message="auth failed: bearer zyxwvutsrq98765"
    )
    conn.commit()
    conn.close()

    findings = collector.collect_failure_findings(window_hours=24, stale_running_hours=1000)
    assert len(findings) == 1
    assert findings[0]["occurrence_count"] == 2


def test_sync_findings_keeps_first_seen_at_stable():
    finding = {
        "fingerprint": "fp_stable",
        "kind": "command",
        "label": "cmd",
        "exception_type": "RuntimeError",
        "occurrence_count": 1,
        "first_seen_at": "2026-09-24T00:00:00+00:00",
        "last_seen_at": "2026-09-24T00:00:00+00:00",
    }
    first = store.sync_findings([finding], resolve_missing_runs=3)
    assert first["fp_stable"]["first_seen_at"] == "2026-09-24T00:00:00+00:00"

    shifted = {
        **finding,
        "first_seen_at": "2026-09-25T12:00:00+00:00",
        "last_seen_at": "2026-09-25T12:00:00+00:00",
    }
    stored = store.sync_findings([shifted], resolve_missing_runs=3)
    assert stored["fp_stable"]["first_seen_at"] == "2026-09-24T00:00:00+00:00"


def test_recover_pending_findings():
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO system_maintenance_findings (
            fingerprint, kind, label, first_seen_at, last_seen_at,
            occurrence_count, missing_count, status, hitl_run_id, coding_run_id, updated_at
        ) VALUES
            ('fp_proposed_missing', 'command', 'cmd', 'x', 'x', 1, 0, 'proposed', 'no_such_run', NULL, 'x'),
            ('fp_coding_pending', 'command', 'cmd', 'x', 'x', 1, 0, 'coding_created', NULL, NULL, 'x'),
            ('fp_coding_linked', 'command', 'cmd', 'x', 'x', 1, 0, 'coding_created', NULL, 'no_such_run', 'x');
        """
    )
    conn.commit()
    conn.close()

    recovered = store.recover_pending_findings()
    assert recovered == 2
    conn = get_db_connection()
    rows = {
        row["fingerprint"]: dict(row)
        for row in conn.execute("SELECT * FROM system_maintenance_findings;")
    }
    conn.close()
    assert rows["fp_proposed_missing"]["status"] == "open"
    assert rows["fp_coding_pending"]["status"] == "open"
    assert rows["fp_coding_linked"]["status"] == "coding_created"


def test_parse_diagnosis_response_rejects_invalid_items():
    payload = {
        "proposals": [
            {
                "fingerprint": "fp_ok",
                "cause": "原因",
                "countermeasure": "対策",
                "severity": "high",
                "coding_instruction": "直す",
            },
            {
                "fingerprint": "fp_invalid",
                "cause": "原因",
                "countermeasure": "対策",
                "severity": "critical",
                "coding_instruction": "直す",
            },
        ]
    }
    parsed = parse_diagnosis_response(f"```json\n{json.dumps(payload)}\n```")
    assert [proposal["fingerprint"] for proposal in parsed] == ["fp_ok"]


def test_run_diagnosis_filters_unknown_fingerprints():
    findings = [
        {
            "fingerprint": "fp_known",
            "kind": "command",
            "label": "cmd",
            "exception_type": "RuntimeError",
            "occurrence_count": 1,
            "first_seen_at": "x",
            "last_seen_at": "x",
            "run_ids": ["run_1"],
            "call_ids": [],
            "exception_messages": ["boom"],
            "tracebacks": ["trace"],
            "related_llm_failures": [],
        }
    ]
    response = json.dumps(
        {
            "proposals": [
                {
                    "fingerprint": "fp_known",
                    "cause": "原因",
                    "countermeasure": "対策",
                    "severity": "medium",
                    "coding_instruction": "直す",
                },
                {
                    "fingerprint": "fp_hallucinated",
                    "cause": "原因",
                    "countermeasure": "対策",
                    "severity": "medium",
                    "coding_instruction": "直す",
                },
            ]
        }
    )
    with patch(
        "obsidian_ai_hub.system_maintenance.diagnosis.llm_client.generate_llm_response",
        return_value=response,
    ) as mocked:
        proposals_result = run_diagnosis(findings)
    assert mocked.call_count == 1
    assert [proposal["fingerprint"] for proposal in proposals_result] == ["fp_known"]


def test_run_diagnosis_dedupes_repeated_fingerprint():
    findings = [
        {
            "fingerprint": "fp_known",
            "kind": "command",
            "label": "cmd",
            "exception_type": "RuntimeError",
            "occurrence_count": 1,
            "first_seen_at": "x",
            "last_seen_at": "x",
            "run_ids": ["run_1"],
            "call_ids": [],
            "exception_messages": ["boom"],
            "tracebacks": ["trace"],
            "related_llm_failures": [],
        }
    ]
    proposal = {
        "fingerprint": "fp_known",
        "cause": "原因",
        "countermeasure": "対策",
        "severity": "medium",
        "coding_instruction": "直す",
    }
    response = json.dumps({"proposals": [proposal, {**proposal, "cause": "別の原因"}]})
    with patch(
        "obsidian_ai_hub.system_maintenance.diagnosis.llm_client.generate_llm_response",
        return_value=response,
    ):
        proposals_result = run_diagnosis(findings)
    assert len(proposals_result) == 1
    assert proposals_result[0]["cause"] == "原因"


def test_changed_content_reuses_existing_coding_run(monkeypatch, maintenance_project):
    monkeypatch.setattr(config, "SYSTEM_MAINTENANCE_PROJECT_ID", maintenance_project["project_id"])
    monkeypatch.setattr(proposals, "_run_worker_is_alive", lambda: True)
    base = {
        "fingerprint": "fp_conflict",
        "label": "cmd",
        "occurrence_count": 1,
        "first_seen_at": "2026-09-25T00:00:00+00:00",
        "severity": "high",
        "countermeasure": "対策",
        "coding_instruction": "直す",
        "run_ids": [],
        "call_ids": [],
    }
    first_run = proposals._enqueue_coding_task({**base, "cause": "原因A"})
    second_run = proposals._enqueue_coding_task({**base, "cause": "原因B"})
    assert first_run == second_run


def _prepare_approval_run(monkeypatch, maintenance_project, worker_alive: bool = True):
    monkeypatch.setattr(config, "SYSTEM_MAINTENANCE_PROJECT_ID", maintenance_project["project_id"])
    monkeypatch.setattr(proposals, "_run_worker_is_alive", lambda: worker_alive)

    conn = get_db_connection()
    _insert_command_run(conn, "run_1", exception_message="boom 111")
    conn.commit()
    conn.close()

    findings = collector.collect_failure_findings(window_hours=24, stale_running_hours=1000)
    store.sync_findings(findings, resolve_missing_runs=3)
    diagnosis = [
        {
            "fingerprint": findings[0]["fingerprint"],
            "cause": "原因",
            "countermeasure": "対策",
            "severity": "high",
            "coding_instruction": "テストを追加する",
        }
    ]
    run_id = register_maintenance_hitl_run(diagnosis, {findings[0]["fingerprint"]: findings[0]})
    assert run_id is not None
    register_handler(proposals.SYSTEM_MAINTENANCE_HANDLER, run_approved_system_maintenance)
    return run_id, findings[0]


def test_approved_proposal_creates_coding_run_once(monkeypatch, maintenance_project):
    run_id, finding = _prepare_approval_run(monkeypatch, maintenance_project)
    fingerprint = finding["fingerprint"]
    submit_answer(run_id, "round_1", "proposal_1", "create")

    conn = get_db_connection()
    processed = dispatch_runs(conn)
    assert processed == 1
    hitl_run = dict(conn.execute("SELECT * FROM hitl_runs WHERE run_id = ?;", (run_id,)).fetchone())
    assert hitl_run["status"] == "completed"
    coding_runs = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM coding_runs WHERE session_id IN "
            "(SELECT session_id FROM coding_sessions WHERE title LIKE 'システムメンテナンス:%');"
        )
    ]
    finding_row = dict(
        conn.execute(
            "SELECT * FROM system_maintenance_findings WHERE fingerprint = ?;",
            (fingerprint,),
        ).fetchone()
    )
    conn.close()

    assert len(coding_runs) == 1
    assert coding_runs[0]["status"] == "queued"
    assert finding_row["status"] == "coding_created"
    assert finding_row["coding_run_id"] == coding_runs[0]["run_id"]

    proposal = {
        "fingerprint": fingerprint,
        "label": finding["label"],
        "occurrence_count": finding["occurrence_count"],
        "first_seen_at": finding["first_seen_at"],
        "severity": "high",
        "cause": "原因",
        "countermeasure": "対策",
        "coding_instruction": "テストを追加する",
        "run_ids": list(finding["run_ids"]),
        "call_ids": [],
    }
    assert proposals._enqueue_coding_task(proposal) == coding_runs[0]["run_id"]


def test_same_label_findings_get_separate_sessions(monkeypatch, maintenance_project):
    monkeypatch.setattr(config, "SYSTEM_MAINTENANCE_PROJECT_ID", maintenance_project["project_id"])
    monkeypatch.setattr(proposals, "_run_worker_is_alive", lambda: True)
    base = {
        "label": "merge_inbox",
        "occurrence_count": 1,
        "first_seen_at": "2026-09-25T00:00:00+00:00",
        "severity": "high",
        "cause": "原因",
        "countermeasure": "対策",
        "coding_instruction": "直す",
        "run_ids": [],
        "call_ids": [],
    }
    first = {**base, "fingerprint": "fp_alpha"}
    second = {**base, "fingerprint": "fp_beta"}

    first_run = proposals._enqueue_coding_task(first)
    second_run = proposals._enqueue_coding_task(second)

    assert first_run != second_run
    assert proposals._enqueue_coding_task(first) == first_run


def test_is_lock_held_reports_contention(tmp_path):
    import fcntl
    import os

    from obsidian_ai_hub.runs import instance

    lock_path = tmp_path / "test.run-worker.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert instance.is_lock_held(lock_path) is True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert instance.is_lock_held(lock_path) is False


def test_worker_down_reopens_finding_and_fails_run(monkeypatch, maintenance_project):
    run_id, finding_record = _prepare_approval_run(
        monkeypatch, maintenance_project, worker_alive=False
    )
    fingerprint = finding_record["fingerprint"]
    submit_answer(run_id, "round_1", "proposal_1", "create")

    conn = get_db_connection()
    dispatch_runs(conn)
    hitl_run = dict(conn.execute("SELECT * FROM hitl_runs WHERE run_id = ?;", (run_id,)).fetchone())
    finding = dict(
        conn.execute(
            "SELECT * FROM system_maintenance_findings WHERE fingerprint = ?;",
            (fingerprint,),
        ).fetchone()
    )
    coding_count = conn.execute("SELECT COUNT(*) FROM coding_runs;").fetchone()[0]
    conn.close()

    assert hitl_run["status"] == "failed"
    assert finding["status"] == "open"
    assert coding_count == 0


def test_cli_end_to_end_registers_hitl(monkeypatch, maintenance_project):
    monkeypatch.setattr(config, "SYSTEM_MAINTENANCE_PROJECT_ID", maintenance_project["project_id"])
    monkeypatch.setattr(proposals, "_run_worker_is_alive", lambda: True)

    conn = get_db_connection()
    _insert_command_run(conn, "run_1", exception_message="boom 111")
    conn.commit()
    conn.close()

    response = json.dumps(
        {
            "proposals": [
                {
                    "fingerprint": collector.compute_fingerprint(
                        "command",
                        "uv run -m obsidian_ai_hub --merge-inbox",
                        "RuntimeError",
                        "boom 111",
                    ),
                    "cause": "原因",
                    "countermeasure": "対策",
                    "severity": "low",
                    "coding_instruction": "直す",
                }
            ]
        }
    )
    with patch(
        "obsidian_ai_hub.system_maintenance.diagnosis.llm_client.generate_llm_response",
        return_value=response,
    ) as mocked:
        result = run_system_maintenance_cli()

    assert mocked.call_count == 1
    assert result["proposals"] == 1
    assert result["hitl_run_id"] is not None

    conn = get_db_connection()
    run = dict(
        conn.execute(
            "SELECT * FROM hitl_runs WHERE run_id = ?;", (result["hitl_run_id"],)
        ).fetchone()
    )
    finding = dict(
        conn.execute(
            "SELECT * FROM system_maintenance_findings ORDER BY last_seen_at DESC LIMIT 1;"
        ).fetchone()
    )
    conn.close()
    assert run["handler"] == proposals.SYSTEM_MAINTENANCE_HANDLER
    assert run["status"] == "pending_user"
    assert finding["status"] == "proposed"


def test_cli_skips_llm_without_findings(monkeypatch):
    with patch(
        "obsidian_ai_hub.system_maintenance.diagnosis.llm_client.generate_llm_response",
        side_effect=AssertionError("LLM must not be called without findings"),
    ) as mocked:
        result = run_system_maintenance_cli()
    assert mocked.call_count == 0
    assert result["proposals"] == 0
    assert result["hitl_run_id"] is None
