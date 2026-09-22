from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Sequence

from obsidian_ai_hub.utils import config, llm_client, prompt

if TYPE_CHECKING:
    from obsidian_ai_hub.hitl.dispatcher import HitlResult

_research_executor = ThreadPoolExecutor(max_workers=1)

logger = logging.getLogger(__name__)

INVALID_FILENAME_CHARS = '/\\:*?"<>|'
MAX_FILENAME_BYTES = 120
RESEARCH_MODE_INTERNAL = "internal"
RESEARCH_MODE_WEB = "web"
RESEARCH_MODE_DEEP = "deep"
RESEARCH_MODE_PROJECT = "project"
RESEARCH_MODE_ALIASES = {
    "quick-first": RESEARCH_MODE_INTERNAL,
    "web-first": RESEARCH_MODE_DEEP,
    "coding": RESEARCH_MODE_PROJECT,
    "codebase": RESEARCH_MODE_PROJECT,
}

MAX_CONTEXT_LINES = 48
MAX_CONTEXT_CHARS = 1200

PROJECT_ROUTE_CONFIDENCE_THRESHOLD = 0.85


@dataclass
class ResearchRouteDecision:
    mode: str
    project_id: Optional[int] = None
    confidence: Optional[float] = None


@dataclass
class ResolvedResearchRoute:
    mode: str
    project_id: Optional[int]
    context: str


@dataclass
class ResearchReport:
    title: str
    mode: str
    markdown: str


@dataclass
class ResearchRunResult:
    success_count: int = 0
    error_count: int = 0
    error_topics: Optional[list[str]] = None

    def __post_init__(self) -> None:
        if self.error_topics is None:
            self.error_topics = []


def _normalize_optional_text(text: Optional[str]) -> str:
    return text.strip() if isinstance(text, str) and text.strip() else ""


def _normalize_research_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    normalized = RESEARCH_MODE_ALIASES.get(normalized, normalized)
    if normalized in {
        RESEARCH_MODE_INTERNAL,
        RESEARCH_MODE_WEB,
        RESEARCH_MODE_DEEP,
        RESEARCH_MODE_PROJECT,
    }:
        return normalized
    return RESEARCH_MODE_INTERNAL


def _normalize_router_decision(text: str) -> Optional[str]:
    normalized = text.strip().lower()
    if not normalized:
        return None

    if normalized.startswith("deep"):
        return RESEARCH_MODE_DEEP
    if normalized.startswith("web"):
        return RESEARCH_MODE_WEB
    if normalized.startswith("internal"):
        return RESEARCH_MODE_INTERNAL

    tokens = [token for token in re.split(r"[^a-z]+", normalized) if token]
    if tokens:
        first = tokens[0]
        if first == "deep":
            return RESEARCH_MODE_DEEP
        if first == "web":
            return RESEARCH_MODE_WEB
        if first == "internal":
            return RESEARCH_MODE_INTERNAL

    if "deep" in normalized:
        return RESEARCH_MODE_DEEP
    if "web" in normalized and "internal" not in normalized:
        return RESEARCH_MODE_WEB
    if (
        "internal" in normalized
        and "web" not in normalized
        and "deep" not in normalized
    ):
        return RESEARCH_MODE_INTERNAL
    return None


def _strict_router_mode(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    normalized = RESEARCH_MODE_ALIASES.get(normalized, normalized)
    if normalized in {
        RESEARCH_MODE_INTERNAL,
        RESEARCH_MODE_WEB,
        RESEARCH_MODE_DEEP,
        RESEARCH_MODE_PROJECT,
    }:
        return normalized
    return None


def _load_json_object(text: str) -> Optional[dict]:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_project_choice(
    project_id: object,
    confidence: object,
    candidate_ids: set[int],
) -> Optional[tuple[int, float]]:
    if isinstance(project_id, bool):
        return None
    if isinstance(project_id, float):
        if not project_id.is_integer():
            return None
        project_id = int(project_id)
    try:
        resolved_id = int(project_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if resolved_id not in candidate_ids:
        return None
    if isinstance(confidence, bool):
        return None
    try:
        resolved_confidence = float(confidence)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if (
        not math.isfinite(resolved_confidence)
        or resolved_confidence < PROJECT_ROUTE_CONFIDENCE_THRESHOLD
    ):
        return None
    return resolved_id, resolved_confidence


def _parse_router_response(
    text: str, candidate_ids: set[int]
) -> Optional[ResearchRouteDecision]:
    """Parse a router response into a decision.

    Accepts the structured JSON contract first, then falls back to the legacy
    single-word response. A structured ``project`` choice is only accepted when
    its integer id is in ``candidate_ids`` and its confidence clears the
    threshold; otherwise the response is treated as unusable.
    """
    payload = _load_json_object(text)
    if payload is not None:
        mode = _strict_router_mode(payload.get("mode"))
        if mode is None:
            return None
        if mode == RESEARCH_MODE_PROJECT:
            choice = _coerce_project_choice(
                payload.get("project_id"),
                payload.get("confidence"),
                candidate_ids,
            )
            if choice is None:
                return None
            project_id, confidence = choice
            return ResearchRouteDecision(
                mode=RESEARCH_MODE_PROJECT,
                project_id=project_id,
                confidence=confidence,
            )
        return ResearchRouteDecision(mode=mode)

    legacy_mode = _normalize_router_decision(text)
    if legacy_mode is None:
        return None
    return ResearchRouteDecision(mode=legacy_mode)


def _list_project_router_candidates() -> list[dict]:
    """Return registered projects that are valid Git repositories.

    Only id, name, goal, description and keywords are exposed to the router;
    filesystem paths and code content are never sent.
    """
    from obsidian_ai_hub.coding.backend import validate_git_repo
    from obsidian_ai_hub.web.services.projects import list_projects

    try:
        projects = list_projects()
    except Exception:
        logger.exception("Failed to list projects for research routing")
        return []

    candidates: list[dict] = []
    for project in projects:
        path = project.get("project_path")
        if not path:
            continue
        try:
            validate_git_repo(path)
        except Exception:
            continue
        candidates.append(
            {
                "project_id": project.get("project_id"),
                "name": project.get("display_name")
                or project.get("normalized_name")
                or "",
                "goal": project.get("goal") or "",
                "description": project.get("description") or "",
                "keywords": project.get("keywords") or [],
            }
        )
    return candidates


def _format_project_candidates(candidates: Sequence[dict]) -> str:
    if not candidates:
        return "(該当プロジェクトなし)"
    blocks: list[str] = []
    for candidate in candidates:
        lines = [f"- id: {candidate.get('project_id')} | 名称: {candidate.get('name')}"]
        goal = _normalize_optional_text(candidate.get("goal"))
        if goal:
            lines.append(f"  目的: {goal}")
        description = _normalize_optional_text(candidate.get("description"))
        if description:
            lines.append(f"  説明: {description}")
        keywords = ", ".join(
            str(keyword) for keyword in candidate.get("keywords") or [] if keyword
        )
        if keywords:
            lines.append(f"  キーワード: {keywords}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def build_web_research_router_prompt(
    theme: str,
    *,
    context: Optional[str] = None,
    why_now: Optional[str] = None,
    direction: Optional[str] = None,
    projects_text: Optional[str] = None,
) -> str:
    context_text = _normalize_optional_text(context) or "(なし)"
    why_now_text = _normalize_optional_text(why_now) or "(なし)"
    direction_text = _normalize_optional_text(direction) or "(なし)"
    projects_text = _normalize_optional_text(projects_text) or "(該当プロジェクトなし)"

    return prompt.render_prompt(
        config.RESEARCH_ROUTER_PROMPT_PATH,
        {
            "theme": theme,
            "why_now_text": why_now_text,
            "context_text": context_text,
            "direction_text": direction_text,
            "projects_text": projects_text,
        },
    )


def route_research_topic(
    theme: str,
    *,
    context: Optional[str] = None,
    why_now: Optional[str] = None,
    direction: Optional[str] = None,
) -> ResearchRouteDecision:
    candidates = _list_project_router_candidates()
    p = build_web_research_router_prompt(
        theme,
        context=context,
        why_now=why_now,
        direction=direction,
        projects_text=_format_project_candidates(candidates),
    )
    try:
        response = llm_client.generate_llm_response(
            provider=config.RESEARCH_ROUTER_PROVIDER,
            model=config.RESEARCH_ROUTER_MODEL,
            prompt=p,
            temperature=0.0,
            max_tokens=512,
        )
    except Exception:
        logger.exception("Failed to route research topic with LLM")
        return ResearchRouteDecision(mode=RESEARCH_MODE_INTERNAL)

    candidate_ids = {
        int(candidate["project_id"])
        for candidate in candidates
        if candidate.get("project_id") is not None
    }
    decision = _parse_router_response(response, candidate_ids)
    if decision is None:
        logger.warning(
            "Unclear research routing decision from LLM: %s", response.strip()
        )
        return ResearchRouteDecision(mode=RESEARCH_MODE_INTERNAL)

    return decision


def _load_activity_context() -> str:
    from obsidian_ai_hub.research import db

    try:
        entries = db.list_recent_activity_days(
            days=config.RESEARCH_CONTEXT_LOOKBACK_DAYS
        )
    except Exception:
        logger.exception("Failed to load activity context")
        return ""

    if not entries:
        return ""

    blocks: list[str] = []
    for e in entries:
        summary = (e.get("summary") or "")[:MAX_CONTEXT_CHARS]
        category = e.get("category") or ""
        keywords = ", ".join(e.get("keywords", []) or [])
        date_str = e.get("activity_date", "")
        lines = [f"- {date_str} | {summary}"]
        if category:
            lines.append(f"  category: {category}")
        if keywords:
            kw_trunc = keywords[:MAX_CONTEXT_CHARS]
            lines.append(f"  keywords: {kw_trunc}")
        blocks.append("\n".join(lines))

        if len(blocks) >= MAX_CONTEXT_LINES:
            break

    return "\n\n".join(blocks)


def _load_db_existing_theme_context() -> str:
    from obsidian_ai_hub.research import db

    try:
        themes = db.list_themes()
    except Exception:
        logger.exception("Failed to load research themes from DB")
        return ""

    lines = [f"- {t['theme']}" for t in themes[:50] if t.get("theme")]
    return "\n".join(lines) if lines else "(none)"


def collect_research_context(theme: str, explicit_context: Optional[str] = None) -> str:
    sections: list[str] = []

    explicit_text = _normalize_optional_text(explicit_context)
    if explicit_text:
        sections.append("## ユーザーの補足\n" + explicit_text)

    activity_text = _load_activity_context()
    if activity_text:
        sections.append("## 最近のアクティビティ\n" + activity_text)

    existing_themes_text = _load_db_existing_theme_context()
    if existing_themes_text:
        sections.append("## 既存の調査テーマ\n" + existing_themes_text)

    try:
        from obsidian_ai_hub.handler.obsidian_vault_retriever import (
            search_obsidian_vault,
        )

        vault_search_results = search_obsidian_vault.invoke({"query": theme, "k": 5})
        if vault_search_results and '"error":' not in vault_search_results:
            sections.append("## Vault 検索結果\n" + vault_search_results)
    except Exception:
        logger.exception("Failed to retrieve context from Obsidian Vault search")

    return "\n\n".join(sections).strip()


def build_research_prompt(
    theme: str,
    *,
    mode: str = RESEARCH_MODE_INTERNAL,
    context: Optional[str] = None,
    output_style: Optional[str] = None,
    why_now: Optional[str] = None,
    project_label: Optional[str] = None,
) -> str:
    context_text = _normalize_optional_text(context)
    why_now_text = _normalize_optional_text(why_now)
    why_now_section = f"\n## 調べたい背景:\n{why_now_text}\n" if why_now_text else ""
    context_section = f"\n## 参考文脈:\n{context_text}\n" if context_text else ""

    output_style_text = (
        _normalize_optional_text(output_style) or config.RESEARCH_DEFAULT_OUTPUT_STYLE
    )
    normalized_mode = _normalize_research_mode(mode)

    if normalized_mode == RESEARCH_MODE_PROJECT:
        project_label_text = _normalize_optional_text(project_label)
        project_section = (
            f"\n## 対象プロジェクト:\n{project_label_text}"
            if project_label_text
            else ""
        )
        return prompt.render_prompt(
            config.RESEARCH_PROJECT_PROMPT_PATH,
            {
                "theme": theme,
                "why_now_section": why_now_section,
                "context_section": context_section,
                "project_section": project_section,
                "output_style_text": output_style_text,
            },
        )

    if normalized_mode == RESEARCH_MODE_WEB:
        search_results = _run_web_search_with_raw_theme(theme)
        logger.debug(
            "Web research search results for theme '%s': %s", theme, search_results
        )
        return prompt.render_prompt(
            config.RESEARCH_WEB_PROMPT_PATH,
            {
                "output_style_text": output_style_text,
                "theme": theme,
                "why_now_section": why_now_section,
                "context_section": context_section,
                "search_results": search_results,
            },
        )

    if normalized_mode == RESEARCH_MODE_DEEP:
        return prompt.render_prompt(
            config.RESEARCH_DEEP_PROMPT_PATH,
            {
                "theme": theme,
                "why_now_section": why_now_section,
                "context_section": context_section,
                "output_style_text": output_style_text,
            },
        )

    return prompt.render_prompt(
        config.RESEARCH_INTERNAL_PROMPT_PATH,
        {
            "theme": theme,
            "why_now_section": why_now_section,
            "context_section": context_section,
            "output_style_text": output_style_text,
        },
    )


def build_title_prompt(theme: str, expanded_prompt: str) -> str:
    return prompt.render_prompt(
        config.RESEARCH_TITLE_PROMPT_PATH,
        {
            "theme": theme,
            "expanded_prompt": expanded_prompt,
        },
    )


def generate_research_title(theme: str, expanded_prompt: str) -> str:
    title = llm_client.generate_llm_response(
        provider=config.RESEARCH_TITLE_GENERATION_PROVIDER,
        model=config.RESEARCH_TITLE_GENERATION_MODEL,
        prompt=build_title_prompt(theme, expanded_prompt),
        temperature=0.0,
        max_tokens=512,
    ).strip()
    title = title.strip().strip('"').strip("'")
    if not title:
        title = theme
    return title


@contextmanager
def _gpt_researcher_environment():
    values = {
        "RETRIEVER": config.RESEARCH_GPT_RESEARCHER_RETRIEVER,
        "FAST_LLM": config.RESEARCH_GPT_RESEARCHER_FAST_LLM,
        "SMART_LLM": config.RESEARCH_GPT_RESEARCHER_SMART_LLM,
        "STRATEGIC_LLM": config.RESEARCH_GPT_RESEARCHER_STRATEGIC_LLM,
        "EMBEDDING": config.RESEARCH_GPT_RESEARCHER_EMBEDDING,
        "SMART_TOKEN_LIMIT": config.RESEARCH_GPT_RESEARCHER_SMART_TOKEN_LIMIT,
        "BROWSE_CHUNK_MAX_LENGTH": config.RESEARCH_GPT_RESEARCHER_BROWSE_CHUNK_MAX_LENGTH,
        "LANGUAGE": config.RESEARCH_GPT_RESEARCHER_LANGUAGE,
    }
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _run_gpt_researcher(query: str) -> str:
    try:
        from gpt_researcher import GPTResearcher
    except Exception as exc:
        raise RuntimeError(
            "gpt_researcher package is required for research agent"
        ) from exc

    with _gpt_researcher_environment():
        researcher = GPTResearcher(
            query=query,
            report_type="research_report",
            mcp_configs=[
                {
                    "name": "my_knowledge_search",
                    "command": "uv",
                    "args": [
                        "--directory",
                        config.RESEARCH_VECTORSEARCH_DIR,
                        "run",
                        config.RESEARCH_VECTORSEARCH_SCRIPT,
                    ],
                }
            ],
            verbose=False,
        )
        await researcher.conduct_research()
        report = await researcher.write_report()
    return (report or "").strip()


def _run_web_search(query: str) -> str:
    try:
        from obsidian_ai_hub.handler.web_search import web_search
    except Exception as exc:
        raise RuntimeError("web_search tool is required for web research") from exc

    try:
        results = web_search.invoke({"query": query, "k": 5})
    except Exception as exc:
        raise RuntimeError("web_search failed") from exc

    return (results or "").strip()


def _run_web_search_with_raw_theme(theme: str) -> str:
    rendered_prompt = prompt.render_prompt(
        config.RESEARCH_QUERY_GENERATION_PROMPT_PATH, {"theme": theme}
    )
    search_query = llm_client.generate_llm_response(
        provider=config.RESEARCH_QUERY_GENERATION_PROVIDER,
        model=config.RESEARCH_QUERY_GENERATION_MODEL,
        prompt=rendered_prompt,
        temperature=0.0,
        max_tokens=512,
    ).strip()
    logger.info("Generated Tavily search query for theme '%s'", theme)
    return _run_web_search(search_query)


def conduct_research(
    prompt: str,
    *,
    mode: str = RESEARCH_MODE_INTERNAL,
    output_style: Optional[str] = None,
    project_id: Optional[int] = None,
) -> str:
    output_style = (
        _normalize_optional_text(output_style) or config.RESEARCH_DEFAULT_OUTPUT_STYLE
    )
    normalized_mode = _normalize_research_mode(mode)

    if normalized_mode == RESEARCH_MODE_INTERNAL:
        return llm_client.generate_llm_response(
            provider=config.RESEARCH_INTERNAL_PROVIDER,
            model=config.RESEARCH_INTERNAL_MODEL,
            prompt=prompt,
            temperature=0.2,
            max_tokens=8000,
        ).strip()

    if normalized_mode == RESEARCH_MODE_WEB:
        from obsidian_ai_hub.handler.web_search import web_search
        from obsidian_ai_hub.handler.web_extract import web_extract

        return llm_client.generate_llm_response_with_tools(
            provider=config.RESEARCH_WEB_PROVIDER,
            model=config.RESEARCH_WEB_MODEL,
            prompt=prompt,
            tools=[web_search, web_extract],
            temperature=0.2,
            max_tokens=8000,
            max_iterations=3,
        ).strip()

    if normalized_mode == RESEARCH_MODE_PROJECT:
        if project_id is None:
            raise ValueError("project research mode requires a project_id")
        from obsidian_ai_hub.research.coding_research import (
            run_project_research_report,
        )

        return run_project_research_report(prompt, project_id=project_id)

    report = asyncio.run(_run_gpt_researcher(prompt))
    return report


def build_markdown(
    title: str,
    body: str,
    generated_at: Optional[str] = None,
    *,
    source: str = "gpt-researcher",
    output_style: Optional[str] = None,
) -> str:
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).astimezone().isoformat()

    frontmatter = [
        "---\n",
        f"title: {title}\n",
        "status: researched\n",
        f"generated_at: {generated_at}\n",
        f"source: {source}\n",
        f"output_style: {output_style or config.RESEARCH_DEFAULT_OUTPUT_STYLE}\n",
        "---\n",
        "\n",
    ]
    body_text = body.rstrip()
    if body_text:
        body_text += "\n"
    return "".join(frontmatter) + body_text


def make_research_filename(title: str) -> str:
    safe = title.translate({ord(char): "_" for char in INVALID_FILENAME_CHARS})
    safe = safe.strip()
    if not safe:
        return "untitled.md"
    return f"{_truncate_filename_base(safe)}.md"


def _truncate_filename_base(base: str) -> str:
    encoded = base.encode("utf-8")
    if len(encoded) <= MAX_FILENAME_BYTES:
        return base

    trimmed = encoded[:MAX_FILENAME_BYTES]
    while trimmed:
        try:
            return trimmed.decode("utf-8")
        except UnicodeDecodeError:
            trimmed = trimmed[:-1]
    return "untitled"


def write_lines_atomic(path: Path, lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        try:
            tmp.writelines(lines)
            tmp.flush()
            os.fsync(tmp.fileno())
        except Exception:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def save_markdown(path: Path, content: str) -> None:
    write_lines_atomic(path, [content])


def _resolve_project_label(project_id: Optional[int]) -> Optional[str]:
    if project_id is None:
        return None
    try:
        from obsidian_ai_hub.web.services.projects import get_project_detail

        project = get_project_detail(int(project_id))
    except Exception:
        logger.exception("Failed to resolve project %s for research", project_id)
        return None
    if not project:
        return None
    name = project.get("display_name") or project.get("normalized_name") or ""
    path = project.get("project_path") or ""
    if name and path:
        return f"{name} ({path})"
    return name or path or None


def resolve_research_route(
    theme: str,
    *,
    direction: Optional[str] = None,
    why_now: Optional[str] = None,
    mode: str = "auto",
    context: Optional[str] = None,
    project_id: Optional[int] = None,
) -> ResolvedResearchRoute:
    """Resolve the execution mode and project for a theme.

    In ``auto`` mode an explicit ``project_id`` wins. Otherwise the router may
    return a high-confidence registered Git project, in which case the mode is
    overridden to ``project``. Any unusable router response falls back to the
    normal routing result.
    """
    combined_context = collect_research_context(theme, context)
    resolved_mode = mode
    resolved_project_id = project_id
    if mode == "auto":
        if project_id is not None:
            resolved_mode = RESEARCH_MODE_PROJECT
        else:
            decision = route_research_topic(
                theme,
                context=combined_context,
                why_now=why_now,
                direction=direction,
            )
            resolved_mode = decision.mode
            if decision.mode == RESEARCH_MODE_PROJECT:
                resolved_project_id = decision.project_id

    normalized_mode = _normalize_research_mode(resolved_mode)
    if normalized_mode == RESEARCH_MODE_PROJECT and resolved_project_id is None:
        raise ValueError("project research mode requires a project_id")
    logger.info(
        "Resolved research mode for theme '%s': %s (project=%s)",
        theme,
        normalized_mode,
        resolved_project_id,
    )
    return ResolvedResearchRoute(
        mode=normalized_mode,
        project_id=resolved_project_id,
        context=combined_context,
    )


def _produce_research_report(
    theme: str,
    route: ResolvedResearchRoute,
    *,
    why_now: Optional[str] = None,
    output_style: Optional[str] = None,
) -> ResearchReport:
    p = build_research_prompt(
        theme,
        mode=route.mode,
        context=route.context,
        output_style=output_style,
        why_now=why_now,
        project_label=_resolve_project_label(route.project_id),
    )
    title = generate_research_title(theme, p)
    report_body = conduct_research(
        p,
        mode=route.mode,
        output_style=output_style,
        project_id=route.project_id,
    )
    source = {
        RESEARCH_MODE_INTERNAL: "internal-llm",
        RESEARCH_MODE_WEB: "tavily-search",
        RESEARCH_MODE_DEEP: "gpt-researcher",
        RESEARCH_MODE_PROJECT: "coding-agent",
    }.get(route.mode, "internal-llm")

    body = f"## テーマ\n{theme}\n\n## 調査結果レポート\n{report_body}"
    markdown = build_markdown(title, body, source=source, output_style=output_style)

    return ResearchReport(title=title, mode=route.mode, markdown=markdown)


def _persist_resolved_project(
    theme_id: str,
    job_id: str,
    previous_project_id: Optional[int],
) -> Callable[[ResolvedResearchRoute], None]:
    """Build a callback that persists an auto-selected project before execution.

    The theme and job rows are updated in the same transaction so a job never
    runs the coding agent without a matching persisted project scope.
    """

    def _persist(route: ResolvedResearchRoute) -> None:
        if route.mode != RESEARCH_MODE_PROJECT:
            return
        if _same_project_scope(route.project_id, previous_project_id):
            return
        from obsidian_ai_hub.research import db

        db.assign_project(theme_id, job_id, route.project_id)
        logger.info(
            "Persisted auto-selected project %s for theme %s (job=%s)",
            route.project_id,
            theme_id,
            job_id,
        )

    return _persist


def run_research(
    theme: str,
    *,
    direction: Optional[str] = None,
    why_now: Optional[str] = None,
    mode: str = "auto",
    context: Optional[str] = None,
    output_style: Optional[str] = None,
    project_id: Optional[int] = None,
    on_route_resolved: Optional[
        Callable[[ResolvedResearchRoute], None]
    ] = None,
) -> ResearchReport:
    route = resolve_research_route(
        theme,
        direction=direction,
        why_now=why_now,
        mode=mode,
        context=context,
        project_id=project_id,
    )
    if on_route_resolved is not None:
        on_route_resolved(route)
    return _produce_research_report(
        theme,
        route,
        why_now=why_now,
        output_style=output_style,
    )


def run_theme_research(
    theme_id: str,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> Optional[dict]:
    from obsidian_ai_hub.research import db

    theme_obj = db.get_theme(theme_id)
    if theme_obj is None:
        logger.error("Theme not found: %s", theme_id)
        return None

    job = db.create_job(theme_id, project_id=theme_obj.get("project_id"))
    job_id = job["job_id"]

    try:
        db.update_job(job_id, status="running")
        report = run_research(
            theme=theme_obj["theme"],
            direction=theme_obj.get("direction"),
            why_now=theme_obj.get("why_now"),
            mode=mode,
            output_style=output_style,
            project_id=theme_obj.get("project_id"),
            on_route_resolved=_persist_resolved_project(
                theme_id, job_id, theme_obj.get("project_id")
            ),
        )
        db.update_job(
            job_id,
            status="succeeded",
            generated_title=report.title,
            mode=report.mode,
            markdown=report.markdown,
        )
        logger.info(
            "Research succeeded for theme '%s' (job=%s)", theme_obj["theme"], job_id
        )
    except Exception as exc:
        logger.exception("Research failed for theme '%s'", theme_obj["theme"])
        db.update_job(
            job_id,
            status="failed",
            error=str(exc),
        )

    return db.latest_job(theme_id)


def cleanup_stale_jobs() -> None:
    from obsidian_ai_hub.research import db

    conn = db._get_db()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT job_id FROM research_jobs WHERE status IN ('pending', 'running')"
            )
            jobs = cursor.fetchall()
            for row in jobs:
                job_id = row["job_id"]
                cursor.execute(
                    "UPDATE research_jobs SET status = 'failed', error = ?, finished_at = ? WHERE job_id = ?",
                    ("サーバー再起動により中断", db.get_current_timestamp(), job_id),
                )
            if jobs:
                logger.info("Cleaned up %d stale jobs on startup", len(jobs))
    except Exception:
        logger.exception("Failed to clean up stale jobs on startup")
    finally:
        conn.close()


def _same_project_scope(left: Optional[int], right: Optional[int]) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return False


def get_or_create_theme_and_job(
    theme: str,
    mode: str = "auto",
    context: Optional[str] = None,
    output_style: Optional[str] = None,
    project_id: Optional[int] = None,
) -> tuple[dict, dict]:
    from obsidian_ai_hub.research import db

    if not theme or not theme.strip():
        raise ValueError("Theme must not be empty or blank")

    normalized = db.normalize_theme_key(theme)
    existing = db.find_exact_duplicate(normalized)

    if (
        existing
        and existing.get("status") == "approved"
        and _same_project_scope(existing.get("project_id"), project_id)
    ):
        theme_id = existing["theme_id"]
        theme_rec = existing
        logger.info("Reusing existing approved theme %s for re-research", theme_id)
    else:
        theme_rec = db.create_theme(
            theme=theme.strip(),
            direction=context or None,
            why_now=context or None,
            kind="explore",
            confidence=1.0,
            status="candidate",
            project_id=project_id,
        )
        theme_id = theme_rec["theme_id"]

    job_rec = db.create_job(theme_id, project_id=theme_rec.get("project_id"))

    theme_rec["latest_job"] = {
        "job_id": job_rec["job_id"],
        "status": job_rec["status"],
        "generated_title": job_rec.get("generated_title"),
        "mode": job_rec.get("mode"),
        "error": job_rec.get("error"),
        "started_at": job_rec.get("started_at"),
        "finished_at": job_rec.get("finished_at"),
        "project_id": job_rec.get("project_id"),
    }

    return theme_rec, job_rec


def _claim_research_job(job_id: str) -> Optional[dict]:
    """Atomically claim a pending research job.

    Uses a conditional UPDATE that only affects rows whose status is
    ``'pending'``, and inspects the affected-row count to determine
    ownership. Returns the updated job dict on success, or ``None`` if
    the job did not exist or was already claimed by another caller.
    """
    from obsidian_ai_hub.research import db as research_db

    conn = research_db.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE research_jobs SET status = 'running' WHERE job_id = ? AND status = 'pending'",
            (job_id,),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return None
        conn.commit()
        return research_db.get_job(job_id, conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_research_job_sync(
    theme_id: str,
    job_id: str,
    mode: str = "auto",
    output_style: Optional[str] = None,
    context: Optional[str] = None,
) -> dict:
    from obsidian_ai_hub.research import db

    job = _claim_research_job(job_id)
    if job is None:
        logger.warning(
            "Job %s could not be claimed (already claimed or nonexistent), refusing to re-run.",
            job_id,
        )
        return db.get_job(job_id) or {}

    theme_obj = db.get_theme(theme_id)
    if theme_obj is None:
        err_msg = f"Theme {theme_id} not found"
        logger.error(err_msg)
        db.update_job(job_id, status="failed", error=err_msg)
        return db.get_job(job_id)

    try:
        report = run_research(
            theme=theme_obj["theme"],
            direction=theme_obj.get("direction"),
            why_now=theme_obj.get("why_now"),
            mode=mode,
            context=context,
            output_style=output_style,
            project_id=theme_obj.get("project_id"),
            on_route_resolved=_persist_resolved_project(
                theme_id, job_id, theme_obj.get("project_id")
            ),
        )

        db.update_job(
            job_id,
            status="succeeded",
            generated_title=report.title,
            mode=report.mode,
            markdown=report.markdown,
        )
        logger.info(
            "Research succeeded for theme '%s' (job=%s)", theme_obj["theme"], job_id
        )

        try:
            save_research_to_vault(theme_id, job_id=job_id)

            if theme_obj.get("status") == "candidate":
                db.set_status(theme_id, "approved", reviewed_by="system")
                logger.info("Theme %s status set to approved", theme_id)

        except Exception as save_exc:
            save_err = f"Failed to save research to vault: {str(save_exc)}"
            logger.exception(save_err)
            db.update_job(job_id, status="failed", error=save_err)

    except Exception as exc:
        err_msg = str(exc) or "Research process failed"
        logger.exception("Research failed for theme '%s'", theme_obj["theme"])
        db.update_job(job_id, status="failed", error=err_msg)

    return db.get_job(job_id)


def submit_research_job_bg(
    theme_id: str,
    job_id: str,
    mode: str = "auto",
    output_style: Optional[str] = None,
    context: Optional[str] = None,
):
    future = _research_executor.submit(
        execute_research_job_sync, theme_id, job_id, mode, output_style, context
    )

    def done_callback(fut):
        try:
            fut.result()
        except Exception as exc:
            logger.exception(
                "Background research job %s failed with uncaught exception", job_id
            )
            from obsidian_ai_hub.research import db

            db.update_job(job_id, status="failed", error=str(exc))

    future.add_done_callback(done_callback)
    return future


def save_research_to_vault(theme_id: str, job_id: Optional[str] = None) -> Optional[Path]:
    from obsidian_ai_hub.research import db

    theme_obj = db.get_theme(theme_id)
    if theme_obj is None:
        logger.error("Theme not found: %s", theme_id)
        return None

    if job_id:
        job = db.get_job(job_id)
    else:
        job = db.latest_job(theme_id)

    if job is None or job.get("status") != "succeeded" or not job.get("markdown"):
        logger.error("No successful research job")
        return None

    # Idempotent: already published with existing file — skip
    if job.get("output_path") and job.get("is_published") == 1:
        existing_file = Path(job["output_path"])
        if existing_file.exists():
            logger.info("Vault output already published at %s, skipping.", existing_file)
            return existing_file
        else:
            logger.warning("output_path is set but file missing: %s, rewriting.", existing_file)

    # Always use <safe_title>_<job_id>.md for deterministic output
    title = job.get("generated_title") or theme_obj["theme"]
    filename = make_research_filename(title)
    output_dir = config.RESEARCH_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = output_dir / filename
    stem_path = stem.with_suffix("")
    job_id_slug = job["job_id"].replace(":", "_").replace("/", "_")
    output_path = output_dir / f"{stem_path.name}_{job_id_slug}.md"

    db.update_job(job["job_id"], output_path=str(output_path))

    save_markdown(output_path, job["markdown"])
    db.update_job(job["job_id"], is_published=1)
    logger.info("Saved research to Vault: %s", output_path)
    return output_path


def main(
    theme: Optional[str] = None,
    *,
    context: Optional[str] = None,
    mode: str = "auto",
    output_style: Optional[str] = None,
    project_id: Optional[int] = None,
) -> ResearchRunResult:

    result = ResearchRunResult()
    if theme is None:
        logger.error(
            "--research-agent --theme <theme> is required (queue mode removed)"
        )
        return result

    try:
        theme_rec, job_rec = get_or_create_theme_and_job(
            theme=theme,
            mode=mode,
            context=context,
            output_style=output_style,
            project_id=project_id,
        )

        job = execute_research_job_sync(
            theme_id=theme_rec["theme_id"],
            job_id=job_rec["job_id"],
            mode=mode,
            output_style=output_style,
        )

        if job and job.get("status") == "succeeded":
            result.success_count += 1
        else:
            logger.error("Research failed for theme '%s'", theme)
            result.error_count += 1
            result.error_topics.append(theme)
    except Exception:
        logger.exception("Failed to process research theme: %s", theme)
        result.error_count += 1
        result.error_topics.append(theme or "(unknown)")

    logger.info(
        "Research agent finished: success=%s error=%s",
        result.success_count,
        result.error_count,
    )
    if result.error_topics:
        logger.info("Failed topics: %s", ", ".join(result.error_topics))

    return result


def run_approved_suggestion(ctx) -> "HitlResult":
    from obsidian_ai_hub.hitl.dispatcher import HitlResult
    from obsidian_ai_hub.hitl.service import update_checkpoint
    from obsidian_ai_hub.research import db
    import json

    answer = ctx.answers_by_question_key.get("action")
    if not answer:
        answer = ctx.answers_by_question_key.get("approve")
    if not answer:
        return HitlResult.fail("Action answer not found in active question set answers.")

    if isinstance(answer, dict):
        answer = answer.get("value", answer)

    comment = None
    raw_answer = None
    if getattr(ctx, "raw_answers_by_question_key", None) is not None:
        raw_answer = ctx.raw_answers_by_question_key.get("action") or ctx.raw_answers_by_question_key.get("approve")
    else:
        # Fallback to DB lookup
        from obsidian_ai_hub.hitl.store import get_questions_by_set, get_run
        run = get_run(ctx.run_id, conn=ctx.conn)
        if run and run.get("active_question_set_id"):
            questions = get_questions_by_set(ctx.run_id, run["active_question_set_id"], conn=ctx.conn)
            for q in questions:
                if q["question_key"] in ("action", "approve"):
                    raw_answer = q["answer"]
                    break

    if isinstance(raw_answer, dict):
        comment = raw_answer.get("comment")

    if comment and not comment.strip():
        comment = None

    cp = {}
    if ctx.checkpoint:
        try:
            cp = json.loads(ctx.checkpoint)
        except (json.JSONDecodeError, TypeError):
            pass
    theme_id = cp.get("theme_id") or ctx.checkpoint

    # Legacy rjob_ checkpoints: extract theme_id from the referenced job
    if theme_id and isinstance(theme_id, str) and theme_id.startswith("rjob_"):
        legacy_job = db.get_job(theme_id, conn=ctx.conn)
        if not legacy_job:
            return HitlResult.fail(f"Legacy checkpoint {ctx.checkpoint} references nonexistent job")
        theme_id = legacy_job["theme_id"]
        # Migrate to new JSON format
        new_cp = json.dumps({"theme_id": theme_id, "phase": "awaiting_approval"})
        update_checkpoint(ctx.run_id, checkpoint=new_cp, conn=ctx.conn)
        cp = {"theme_id": theme_id, "phase": "awaiting_approval"}

    if not theme_id:
        return HitlResult.fail(f"Invalid or missing theme_id in checkpoint: {ctx.checkpoint}")

    # Normalize the single-select action into approve/reject plus an optional
    # rejection reason. Legacy scalar values ("approve" / "reject") stay valid.
    status = None
    decision = None
    reason = None
    if answer == "approve":
        status = "approved"
        decision = "approved"
    elif answer == "reject":
        status = "rejected"
        decision = "rejected"
    elif isinstance(answer, str) and answer.startswith("reject:"):
        status = "rejected"
        decision = "rejected"
        reason = answer.split(":", 1)[1].strip()
        if reason not in db.ALLOWED_FEEDBACK_REASONS:
            reason = "other"
    else:
        return HitlResult.fail(f"Invalid action choice: {answer}")

    # Save the theme status and the user feedback in the same DB operation.
    saved = db.set_theme_feedback(
        theme_id,
        status=status,
        decision=decision,
        reason=reason,
        comment=comment,
        reviewed_by="user",
        conn=ctx.conn,
    )
    if saved is None:
        return HitlResult.fail(f"Theme {theme_id} not found when saving feedback")

    if decision == "rejected":
        return HitlResult.complete(checkpoint=json.dumps({**cp, "phase": "rejected"}))

    job_id = cp.get("job_id")

    if not job_id:
        theme_obj = db.get_theme(theme_id, conn=ctx.conn)
        job = db.create_job(
            theme_id,
            conn=ctx.conn,
            project_id=(theme_obj or {}).get("project_id"),
        )
        job_id = job["job_id"]
        new_cp = json.dumps({"theme_id": theme_id, "job_id": job_id, "phase": "job_created"})
        update_checkpoint(ctx.run_id, checkpoint=new_cp, conn=ctx.conn)
        cp = {"theme_id": theme_id, "job_id": job_id, "phase": "job_created"}

    job = db.get_job(job_id)
    js = job.get("status") if job else None

    if js == "succeeded":
        save_research_to_vault(theme_id, job_id)
        new_cp = json.dumps({"theme_id": theme_id, "job_id": job_id, "phase": "published"})
        update_checkpoint(ctx.run_id, checkpoint=new_cp, conn=ctx.conn)
        return HitlResult.complete(checkpoint=new_cp)

    if js == "running":
        return HitlResult.fail("Research job already running elsewhere", checkpoint=ctx.checkpoint)

    if js == "failed":
        return HitlResult.fail(f"Research job previously failed: {job.get('error', 'unknown')}", checkpoint=ctx.checkpoint)

    if js is None:
        return HitlResult.fail(f"Research job {job_id} not found", checkpoint=ctx.checkpoint)

    # js == "pending" — run research
    job = execute_research_job_sync(theme_id, job_id, context=comment)
    js = job.get("status") if job else None

    if js == "succeeded":
        new_cp = json.dumps({"theme_id": theme_id, "job_id": job_id, "phase": "published"})
        update_checkpoint(ctx.run_id, checkpoint=new_cp, conn=ctx.conn)
        return HitlResult.complete(checkpoint=new_cp)
    else:
        error_msg = job.get("error") if job else "Research execution failed"
        return HitlResult.fail(error_msg, checkpoint=ctx.checkpoint)
