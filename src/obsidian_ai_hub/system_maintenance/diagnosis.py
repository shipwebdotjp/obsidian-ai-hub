"""LLM diagnosis of collected failure findings."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Mapping, Sequence

from pydantic import BaseModel, Field, ValidationError

from obsidian_ai_hub.utils import config, llm_client, prompt

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$")


class DiagnosisProposal(BaseModel):
    fingerprint: str
    cause: str
    countermeasure: str
    severity: str = Field(pattern="^(low|medium|high)$")
    coding_instruction: str


def render_findings_for_prompt(findings: Sequence[Mapping[str, Any]]) -> str:
    sections: List[str] = []
    for index, finding in enumerate(findings, 1):
        lines = [
            f"### Finding {index}",
            f"- fingerprint: {finding.get('fingerprint')}",
            f"- kind: {finding.get('kind')}",
            f"- label: {finding.get('label')}",
            f"- exception_type: {finding.get('exception_type')}",
            f"- occurrences: {finding.get('occurrence_count')}"
            f" ({finding.get('first_seen_at')} - {finding.get('last_seen_at')})",
        ]
        run_ids = finding.get("run_ids") or []
        if run_ids:
            lines.append(f"- run_ids: {', '.join(str(r) for r in run_ids[:10])}")
        call_ids = finding.get("call_ids") or []
        if call_ids:
            lines.append(f"- call_ids: {', '.join(str(c) for c in call_ids[:10])}")
        messages = finding.get("exception_messages") or []
        if messages:
            lines.append("- exception_messages:")
            lines.extend(f"  - {message}" for message in messages)
        related = finding.get("related_llm_failures") or []
        if related:
            lines.append("- related_llm_failures:")
            for item in related:
                lines.append(
                    f"  - {item.get('call_id')} {item.get('provider')}/{item.get('model')} "
                    f"{item.get('exception_type')}: {item.get('exception_message')}"
                )
        tracebacks = finding.get("tracebacks") or []
        if tracebacks:
            lines.append("- tracebacks:")
            for traceback in tracebacks:
                lines.append("```")
                lines.append(traceback)
                lines.append("```")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def parse_diagnosis_response(text: str) -> List[Dict[str, Any]]:
    cleaned = _CODE_FENCE_RE.sub("", (text or "").strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse system maintenance diagnosis as JSON: %s", exc)
        return []

    raw = data.get("proposals") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        logger.warning(
            "System maintenance diagnosis response is not a proposal list: %s",
            type(raw).__name__,
        )
        return []

    proposals: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            proposal = DiagnosisProposal.model_validate(item)
        except ValidationError as exc:
            logger.warning("Dropping invalid diagnosis proposal: %s", exc.errors())
            continue
        proposals.append(proposal.model_dump())
    return proposals


def run_diagnosis(findings: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Diagnose findings and return proposals limited to known fingerprints."""
    if not findings:
        return []

    rendered = prompt.render_prompt(
        config.SYSTEM_MAINTENANCE_PROMPT_PATH,
        {"findings_text": render_findings_for_prompt(findings)},
    )
    response = llm_client.generate_llm_response(
        provider=config.SYSTEM_MAINTENANCE_PROVIDER,
        model=config.SYSTEM_MAINTENANCE_MODEL,
        prompt=rendered,
        temperature=0.2,
        max_tokens=8000,
    ).strip()

    allowed = {str(f["fingerprint"]) for f in findings}
    proposals = []
    seen = set()
    for proposal in parse_diagnosis_response(response):
        fingerprint = proposal["fingerprint"]
        if fingerprint not in allowed:
            logger.warning(
                "Dropping diagnosis proposal with unknown fingerprint %s",
                fingerprint,
            )
            continue
        if fingerprint in seen:
            logger.warning(
                "Dropping duplicate diagnosis proposal for fingerprint %s",
                fingerprint,
            )
            continue
        seen.add(fingerprint)
        proposals.append(proposal)
    return proposals
