"""CLI entry point for system maintenance diagnosis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from obsidian_ai_hub.system_maintenance import collector, store
from obsidian_ai_hub.system_maintenance.diagnosis import run_diagnosis
from obsidian_ai_hub.system_maintenance.proposals import (
    register_maintenance_hitl_run,
    validate_target_project,
)
from obsidian_ai_hub.utils import config


def run_system_maintenance_cli() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    recovered = store.recover_pending_findings(now_iso=now.isoformat())
    if recovered:
        print(f"未完了だった保守レコード {recovered} 件を再診断対象に戻しました。")

    print(f"[{now.isoformat()}] CLI実行ログ・LLMコール履歴の障害診断を開始します...")
    findings = collector.collect_failure_findings(now=now)
    rows = store.sync_findings(
        findings,
        resolve_missing_runs=config.SYSTEM_MAINTENANCE_RESOLVE_MISSING_RUNS,
        now_iso=now.isoformat(),
    )
    open_findings = [
        finding
        for finding in findings
        if (rows.get(finding["fingerprint"]) or {}).get("status") == store.STATUS_OPEN
    ]
    if not open_findings:
        print(f"新規に診断すべき障害はありません（収集 {len(findings)} 件）。")
        return {
            "collected": len(findings),
            "diagnosed": 0,
            "proposals": 0,
            "hitl_run_id": None,
        }

    limit = int(config.SYSTEM_MAINTENANCE_MAX_FINDINGS)
    targets = open_findings[:limit]
    if len(open_findings) > limit:
        print(
            f"未診断の障害が{len(open_findings)}件あるため、上位{limit}件のみ診断します。"
        )

    validate_target_project()

    proposals = run_diagnosis(targets)
    if not proposals:
        print("LLM診断の結果、提案可能な対策はありませんでした。")
        return {
            "collected": len(findings),
            "diagnosed": len(targets),
            "proposals": 0,
            "hitl_run_id": None,
        }

    print(f"診断完了: {len(proposals)}件の改善提案を作成しました。")
    for index, proposal in enumerate(proposals, 1):
        print(f"提案 #{index}: [{proposal['severity']}] {proposal['fingerprint']}")
        print(f"  原因: {proposal['cause']}")
        print(f"  対策: {proposal['countermeasure']}")

    findings_by_fingerprint = {}
    for finding in findings:
        stored = rows.get(finding["fingerprint"]) or {}
        findings_by_fingerprint[finding["fingerprint"]] = {
            **finding,
            "first_seen_at": stored.get("first_seen_at")
            or finding["first_seen_at"],
        }
    run_id = register_maintenance_hitl_run(proposals, findings_by_fingerprint, now=now)
    if run_id:
        print(f"メンテナンス提案を HITL キューに登録しました。Run ID: {run_id}")
    return {
        "collected": len(findings),
        "diagnosed": len(targets),
        "proposals": len(proposals),
        "hitl_run_id": run_id,
    }
