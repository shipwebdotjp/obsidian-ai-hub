from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from obsidian_ai_hub.utils import config, llm_client, prompt

_research_executor = ThreadPoolExecutor(max_workers=1)

logger = logging.getLogger(__name__)

INVALID_FILENAME_CHARS = '/\\:*?"<>|'
MAX_FILENAME_BYTES = 120
RESEARCH_MODE_INTERNAL = "internal"
RESEARCH_MODE_WEB = "web"
RESEARCH_MODE_DEEP = "deep"
RESEARCH_MODE_ALIASES = {
    "quick-first": RESEARCH_MODE_INTERNAL,
    "web-first": RESEARCH_MODE_DEEP,
}

MAX_CONTEXT_LINES = 48
MAX_CONTEXT_CHARS = 1200


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
    if normalized in {RESEARCH_MODE_INTERNAL, RESEARCH_MODE_WEB, RESEARCH_MODE_DEEP}:
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
    if "internal" in normalized and "web" not in normalized and "deep" not in normalized:
        return RESEARCH_MODE_INTERNAL
    return None


def build_web_research_router_prompt(
    theme: str,
    *,
    context: Optional[str] = None,
    why_now: Optional[str] = None,
) -> str:
    context_text = _normalize_optional_text(context) or "(なし)"
    why_now_text = _normalize_optional_text(why_now) or "(なし)"

    return prompt.render_prompt(
        config.RESEARCH_ROUTER_PROMPT_PATH,
        {
            "theme": theme,
            "why_now_text": why_now_text,
            "context_text": context_text,
        }
    )


def route_research_topic(
    theme: str,
    *,
    context: Optional[str] = None,
    why_now: Optional[str] = None,
) -> str:
    p = build_web_research_router_prompt(
        theme,
        context=context,
        why_now=why_now,
    )
    try:
        response = llm_client.generate_llm_response(
            provider=config.RESEARCH_ROUTER_PROVIDER,
            model=config.RESEARCH_ROUTER_MODEL,
            prompt=p,
            temperature=0.0,
            max_tokens=16,
        )
    except Exception:
        logger.exception("Failed to route research topic with LLM")
        return RESEARCH_MODE_INTERNAL

    decision = _normalize_router_decision(response)
    if decision is None:
        logger.warning("Unclear research routing decision from LLM: %s", response.strip())
        return RESEARCH_MODE_INTERNAL

    return decision


def _load_activity_context() -> str:
    from obsidian_ai_hub.research import db
    try:
        entries = db.list_recent_activity_days(days=config.RESEARCH_CONTEXT_LOOKBACK_DAYS)
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
        from obsidian_ai_hub.handler.obsidian_vault_retriever import search_obsidian_vault
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
) -> str:
    context_text = _normalize_optional_text(context)
    why_now_text = _normalize_optional_text(why_now)
    why_now_section = f"\n## 調べたい背景:\n{why_now_text}\n" if why_now_text else ""
    context_section = f"\n## 参考文脈:\n{context_text}\n" if context_text else ""

    output_style_text = _normalize_optional_text(output_style) or config.RESEARCH_DEFAULT_OUTPUT_STYLE
    normalized_mode = _normalize_research_mode(mode)

    if normalized_mode == RESEARCH_MODE_WEB:
        search_results = _run_web_search_with_raw_theme(theme)
        logger.debug("Web research search results for theme '%s': %s", theme, search_results)
        return prompt.render_prompt(
            config.RESEARCH_WEB_PROMPT_PATH,
            {
                "output_style_text": output_style_text,
                "theme": theme,
                "why_now_section": why_now_section,
                "context_section": context_section,
                "search_results": search_results,
            }
        )

    if normalized_mode == RESEARCH_MODE_DEEP:
        return prompt.render_prompt(
            config.RESEARCH_DEEP_PROMPT_PATH,
            {
                "theme": theme,
                "why_now_section": why_now_section,
                "context_section": context_section,
                "output_style_text": output_style_text,
            }
        )

    return prompt.render_prompt(
        config.RESEARCH_INTERNAL_PROMPT_PATH,
        {
            "theme": theme,
            "why_now_section": why_now_section,
            "context_section": context_section,
            "output_style_text": output_style_text,
        }
    )


def build_title_prompt(theme: str, expanded_prompt: str) -> str:
    return prompt.render_prompt(
        config.RESEARCH_TITLE_PROMPT_PATH,
        {
            "theme": theme,
            "expanded_prompt": expanded_prompt,
        }
    )


def generate_research_title(theme: str, expanded_prompt: str) -> str:
    title = llm_client.generate_llm_response(
        provider=config.RESEARCH_TITLE_GENERATION_PROVIDER,
        model=config.RESEARCH_TITLE_GENERATION_MODEL,
        prompt=build_title_prompt(theme, expanded_prompt),
        temperature=0.0,
        max_tokens=64,
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
        raise RuntimeError("gpt_researcher package is required for research agent") from exc

    with _gpt_researcher_environment():
        researcher = GPTResearcher(
            query=query,
            report_type="research_report",
            mcp_configs=[
                {
                    "name": "my_knowledge_search",
                    "command": "uv",
                    "args": ["--directory", config.RESEARCH_VECTORSEARCH_DIR, "run", config.RESEARCH_VECTORSEARCH_SCRIPT],
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
        config.RESEARCH_QUERY_GENERATION_PROMPT_PATH,
        {"theme": theme}
    )
    search_query = llm_client.generate_llm_response(
        provider=config.RESEARCH_QUERY_GENERATION_PROVIDER,
        model=config.RESEARCH_QUERY_GENERATION_MODEL,
        prompt=rendered_prompt,
        temperature=0.0,
        max_tokens=64,
    ).strip()
    logger.info("Generated Tavily search query for theme '%s'", theme)
    return _run_web_search(search_query)


def conduct_research(
    prompt: str,
    *,
    mode: str = RESEARCH_MODE_INTERNAL,
    output_style: Optional[str] = None,
) -> str:
    output_style = _normalize_optional_text(output_style) or config.RESEARCH_DEFAULT_OUTPUT_STYLE
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


def run_research(
    theme: str,
    *,
    direction: Optional[str] = None,
    why_now: Optional[str] = None,
    mode: str = "auto",
    context: Optional[str] = None,
    output_style: Optional[str] = None,
) -> ResearchReport:
    combined_context = collect_research_context(theme, context)
    resolved_mode = mode
    if mode == "auto":
        resolved_mode = route_research_topic(
            theme,
            context=combined_context,
            why_now=why_now,
        )
    normalized_mode = _normalize_research_mode(resolved_mode)
    logger.info("Resolved research mode for theme '%s': %s", theme, normalized_mode)

    p = build_research_prompt(
        theme,
        mode=resolved_mode,
        context=combined_context,
        output_style=output_style,
        why_now=why_now,
    )
    title = generate_research_title(theme, p)
    report_body = conduct_research(p, mode=resolved_mode, output_style=output_style)
    source = {
        RESEARCH_MODE_INTERNAL: "internal-llm",
        RESEARCH_MODE_WEB: "tavily-search",
        RESEARCH_MODE_DEEP: "gpt-researcher",
    }.get(normalized_mode, "internal-llm")

    body = f"## テーマ\n{theme}\n\n## 調査結果レポート\n{report_body}"
    markdown = build_markdown(title, body, source=source, output_style=output_style)

    return ResearchReport(title=title, mode=normalized_mode, markdown=markdown)


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

    job = db.create_job(theme_id)
    job_id = job["job_id"]

    try:
        db.update_job(job_id, status="running")
        report = run_research(
            theme=theme_obj["theme"],
            direction=theme_obj.get("direction"),
            why_now=theme_obj.get("why_now"),
            mode=mode,
            output_style=output_style,
        )
        db.update_job(
            job_id,
            status="succeeded",
            generated_title=report.title,
            mode=report.mode,
            markdown=report.markdown,
        )
        logger.info("Research succeeded for theme '%s' (job=%s)", theme_obj["theme"], job_id)
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
                    ("サーバー再起動により中断", db.get_current_timestamp(), job_id)
                )
            if jobs:
                logger.info("Cleaned up %d stale jobs on startup", len(jobs))
    except Exception as exc:
        logger.exception("Failed to clean up stale jobs on startup")
    finally:
        conn.close()


def get_or_create_theme_and_job(
    theme: str,
    mode: str = "auto",
    context: Optional[str] = None,
    output_style: Optional[str] = None,
) -> tuple[dict, dict]:
    from obsidian_ai_hub.research import db

    if not theme or not theme.strip():
        raise ValueError("Theme must not be empty or blank")

    normalized = db.normalize_theme_key(theme)
    existing = db.find_exact_duplicate(normalized)

    if existing and existing.get("status") == "approved":
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
        )
        theme_id = theme_rec["theme_id"]

    job_rec = db.create_job(theme_id)

    theme_rec["latest_job"] = {
        "job_id": job_rec["job_id"],
        "status": job_rec["status"],
        "generated_title": job_rec.get("generated_title"),
        "mode": job_rec.get("mode"),
        "error": job_rec.get("error"),
        "started_at": job_rec.get("started_at"),
        "finished_at": job_rec.get("finished_at"),
    }

    return theme_rec, job_rec


def execute_research_job_sync(
    theme_id: str,
    job_id: str,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> dict:
    from obsidian_ai_hub.research import db

    db.update_job(job_id, status="running")

    theme_obj = db.get_theme(theme_id)
    if theme_obj is None:
        err_msg = f"Theme {theme_id} not found"
        logger.error(err_msg)
        db.update_job(job_id, status="failed", error=err_msg)
        return db.latest_job(theme_id)

    try:
        report = run_research(
            theme=theme_obj["theme"],
            direction=theme_obj.get("direction"),
            why_now=theme_obj.get("why_now"),
            mode=mode,
            output_style=output_style,
        )

        db.update_job(
            job_id,
            status="succeeded",
            generated_title=report.title,
            mode=report.mode,
            markdown=report.markdown,
        )
        logger.info("Research succeeded for theme '%s' (job=%s)", theme_obj["theme"], job_id)

        try:
            save_research_to_vault(theme_id)

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

    return db.latest_job(theme_id)


def submit_research_job_bg(
    theme_id: str,
    job_id: str,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> None:
    _research_executor.submit(
        execute_research_job_sync,
        theme_id,
        job_id,
        mode,
        output_style
    )


def save_research_to_vault(theme_id: str) -> Optional[Path]:
    from obsidian_ai_hub.research import db

    theme_obj = db.get_theme(theme_id)
    if theme_obj is None:
        logger.error("Theme not found: %s", theme_id)
        return None

    job = db.latest_job(theme_id)
    if job is None or job.get("status") != "succeeded" or not job.get("markdown"):
        logger.error("No successful research job for theme %s", theme_id)
        return None

    title = job.get("generated_title") or theme_obj["theme"]
    filename = make_research_filename(title)

    output_dir = config.RESEARCH_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    if output_path.exists():
        stem = output_path.stem
        suffix = output_path.suffix
        output_path = output_dir / f"{stem}_{theme_id}{suffix}"

    save_markdown(output_path, job["markdown"])
    logger.info("Saved research to Vault: %s", output_path)
    return output_path


def main(
    theme: Optional[str] = None,
    *,
    context: Optional[str] = None,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> ResearchRunResult:
    from obsidian_ai_hub.research import db

    result = ResearchRunResult()
    if theme is None:
        logger.error("--research-agent --theme <theme> is required (queue mode removed)")
        return result

    try:
        theme_rec, job_rec = get_or_create_theme_and_job(
            theme=theme,
            mode=mode,
            context=context,
            output_style=output_style,
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
