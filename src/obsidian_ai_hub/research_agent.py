from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from obsidian_ai_hub.utils import config, llm_client, prompt

logger = logging.getLogger(__name__)

INVALID_FILENAME_CHARS = '/\\:*?"<>|'
CHECKBOX_UNCHECKED = "- [ ]"
CHECKBOX_CHECKED = "- [x]"
MAX_FILENAME_BYTES = 120
RESEARCH_MODE_INTERNAL = "internal"
RESEARCH_MODE_WEB = "web"
RESEARCH_MODE_DEEP = "deep"
RESEARCH_MODE_ALIASES = {
    "quick-first": RESEARCH_MODE_INTERNAL,
    "web-first": RESEARCH_MODE_DEEP,
}

@dataclass(frozen=True)
class ResearchCandidate:
    line_index: int
    theme: str


@dataclass
class ResearchRunResult:
    success_count: int = 0
    error_count: int = 0
    error_topics: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if self.error_topics is None:
            self.error_topics = []


def read_lines(path: Path) -> List[str]:
    with path.open("r", encoding="utf-8") as f:
        return f.read().splitlines(keepends=True)


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


def parse_candidates(lines: Sequence[str]) -> List[ResearchCandidate]:
    candidates: List[ResearchCandidate] = []
    for index, line in enumerate(lines):
        if not line.startswith(CHECKBOX_UNCHECKED):
            continue
        payload = line[len(CHECKBOX_UNCHECKED):].strip()
        theme = payload.rsplit(" / ", 1)[0].strip()
        if theme:
            candidates.append(ResearchCandidate(line_index=index, theme=theme))
    return candidates


def mark_candidate_checked(lines: Sequence[str], line_index: int) -> List[str]:
    updated = list(lines)
    if line_index < 0 or line_index >= len(updated):
        raise IndexError(f"line_index out of range: {line_index}")
    line = updated[line_index]
    if line.startswith(CHECKBOX_UNCHECKED):
        updated[line_index] = CHECKBOX_CHECKED + line[len(CHECKBOX_UNCHECKED):]
    return updated


def make_research_filename(theme: str) -> str:
    safe = theme.translate({ord(char): "_" for char in INVALID_FILENAME_CHARS})
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
    prompt = build_web_research_router_prompt(
        theme,
        context=context,
        why_now=why_now,
    )
    try:
        response = llm_client.generate_llm_response(
            provider=config.RESEARCH_ROUTER_PROVIDER,
            model=config.RESEARCH_ROUTER_MODEL,
            prompt=prompt,
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


def needs_web_research(
    theme: str,
    *,
    context: Optional[str] = None,
    why_now: Optional[str] = None,
) -> bool:
    return route_research_topic(
        theme,
        context=context,
        why_now=why_now,
    ) != RESEARCH_MODE_INTERNAL


def _load_recent_note_context() -> str:
    from obsidian_ai_hub import suggest_research_theme

    try:
        notes = suggest_research_theme._load_recent_notes(
            days=config.RESEARCH_CONTEXT_LOOKBACK_DAYS,
        )
    except Exception:
        logger.exception("Failed to load recent notes for research context")
        return ""

    if not notes:
        return ""

    return suggest_research_theme._build_context_pack(
        notes[:config.RESEARCH_CONTEXT_MAX_NOTES],
    ).strip()


def _load_existing_candidate_context() -> str:
    candidate_path = config.RESEARCH_CANDIDATE_THEME_LIST_PATH
    if not candidate_path.exists():
        return ""

    try:
        lines = read_lines(candidate_path)
    except Exception:
        logger.exception("Failed to load research candidate themes")
        return ""

    themes = [candidate.theme for candidate in parse_candidates(lines)[:20]]
    if not themes:
        return ""

    return "\n".join(f"- {theme}" for theme in themes)


def collect_research_context(theme: str, explicit_context: Optional[str] = None) -> str:
    sections: List[str] = []

    explicit_text = _normalize_optional_text(explicit_context)
    if explicit_text:
        sections.append("## ユーザーの補足\n" + explicit_text)

    recent_notes_text = _load_recent_note_context()
    if recent_notes_text:
        sections.append("## 最近のノート\n" + recent_notes_text)

    existing_candidates_text = _load_existing_candidate_context()
    if existing_candidates_text:
        sections.append("## 既存の調査候補\n" + existing_candidates_text)

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
    # オプションセクションを事前に組み立てる
    why_now_section = f"\n## 調べたい背景:\n{why_now_text}\n" if why_now_text else ""
    context_section = f"\n## 参考文脈:\n{context_text}\n" if context_text else ""

    output_style_text = _normalize_optional_text(output_style) or config.RESEARCH_DEFAULT_OUTPUT_STYLE
    normalized_mode = _normalize_research_mode(mode)

    if normalized_mode == RESEARCH_MODE_WEB:
        # Tavilyの検索結果をここで埋め込む
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


def expand_topic_prompt(
    theme: str,
    *,
    mode: str = RESEARCH_MODE_INTERNAL,
    context: Optional[str] = None,
    output_style: Optional[str] = None,
    why_now: Optional[str] = None,
) -> str:
    return build_research_prompt(
        theme,
        mode=mode,
        context=context,
        output_style=output_style,
        why_now=why_now,
    ).strip()

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
    """Expose config.yml's deep-research settings only while GPT Researcher runs."""
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
        from gpt_researcher import GPTResearcher  # type: ignore
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
    """
    Generates a web search query from a theme using an LLM, then executes the search.
    """
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


def _truncate_text(text: str, *, limit: int = 12000) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "\n...(truncated)"


def _build_web_synthesis_prompt(query: str, search_results: str, output_style: str) -> str:
    return f"""
"""


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


def build_research_body(
    expanded_prompt: str,
    report: str,
    *,
    prompt_label: str = "調査用プロンプト",
) -> str:
    prompt_text = expanded_prompt.rstrip()
    report_text = report.strip()
    if prompt_text and report_text:
        return f"## {prompt_label}\n{prompt_text}\n\n## 調査結果レポート\n{report_text}"
    if prompt_text:
        return prompt_text
    return report_text


def save_markdown(path: Path, content: str) -> None:
    write_lines_atomic(path, [content])


def process_candidate(
    candidate: ResearchCandidate,
    *,
    context: Optional[str] = None,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> Tuple[Path, str]:
    return process_theme(
        candidate.theme,
        context=context,
        mode=mode,
        output_style=output_style,
    )


def process_theme(
    theme: str,
    *,
    context: Optional[str] = None,
    mode: str = "auto",
    output_style: Optional[str] = None,
    why_now: Optional[str] = None,
) -> Tuple[Path, str]:
    combined_context = collect_research_context(theme,context)
    resolved_mode = mode
    if mode == "auto":
        resolved_mode = route_research_topic(
            theme,
            context=combined_context,
            why_now=why_now,
        )
    normalized_mode = _normalize_research_mode(resolved_mode)
    logger.info("Resolved research mode for theme '%s': %s", theme, normalized_mode)
    prompt = expand_topic_prompt(
        theme,
        mode=resolved_mode,
        context=combined_context,
        output_style=output_style,
        why_now=why_now,
    )
    title = generate_research_title(theme, prompt)
    report = conduct_research(prompt, mode=resolved_mode, output_style=output_style)
    output_path = config.RESEARCH_OUTPUT_DIR / make_research_filename(title)
    source = {
        RESEARCH_MODE_INTERNAL: "internal-llm",
        RESEARCH_MODE_WEB: "tavily-search",
        RESEARCH_MODE_DEEP: "gpt-researcher",
    }.get(normalized_mode, "internal-llm")
    markdown = build_markdown(
        title,
        build_research_body(
            theme,
            report,
            prompt_label="テーマ",
        ),
        source=source,
        output_style=output_style,
    )
    save_markdown(output_path, markdown)
    return output_path, markdown


def _run_queue_mode(
    *,
    context: Optional[str] = None,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> ResearchRunResult:
    result = ResearchRunResult()

    candidate_path = config.RESEARCH_CANDIDATE_THEME_LIST_PATH
    output_dir = config.RESEARCH_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if not candidate_path.exists():
        raise FileNotFoundError(f"Candidate theme list not found: {candidate_path}")

    lines = read_lines(candidate_path)
    candidates = parse_candidates(lines)

    for candidate in candidates:
        try:
            logger.info("Processing research topic: %s", candidate.theme)
            process_candidate(
                candidate,
                context=context,
                mode=mode,
                output_style=output_style,
            )
            updated_lines = mark_candidate_checked(lines, candidate.line_index)
            write_lines_atomic(candidate_path, updated_lines)
            lines = updated_lines
            result.success_count += 1
        except Exception as exc:
            logger.exception("Failed to process research topic: %s", candidate.theme)
            result.error_count += 1
            result.error_topics.append(candidate.theme)
            continue

    logger.info(
        "Research agent finished: success=%s error=%s",
        result.success_count,
        result.error_count,
    )
    if result.error_topics:
        logger.info("Failed topics: %s", ", ".join(result.error_topics))

    return result


def _run_single_theme_mode(
    theme: str,
    *,
    context: Optional[str] = None,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> ResearchRunResult:
    result = ResearchRunResult()
    output_dir = config.RESEARCH_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("Processing research topic: %s", theme)
        process_theme(
            theme,
            context=context,
            mode=mode,
            output_style=output_style,
        )
        result.success_count += 1
    except Exception:
        logger.exception("Failed to process research topic: %s", theme)
        result.error_count += 1
        result.error_topics.append(theme)

    logger.info(
        "Research agent finished: success=%s error=%s",
        result.success_count,
        result.error_count,
    )
    if result.error_topics:
        logger.info("Failed topics: %s", ", ".join(result.error_topics))

    return result


def main(
    theme: Optional[str] = None,
    *,
    context: Optional[str] = None,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> ResearchRunResult:
    if theme is None:
        return _run_queue_mode(context=context, mode=mode, output_style=output_style)
    return _run_single_theme_mode(theme, context=context, mode=mode, output_style=output_style)
