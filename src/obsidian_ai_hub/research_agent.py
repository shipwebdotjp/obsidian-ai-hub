from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from obsidian_ai_hub.utils import config, llm_client

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

os.environ["RETRIEVER"] = "tavily,mcp"
os.environ["FAST_LLM"] = "openai:gpt-5.4"
os.environ["SMART_LLM"] = "openai:gpt-5.5"
os.environ["STRATEGIC_LLM"] = "openai:gpt-5.4"
os.environ["EMBEDDING"] = "huggingface:cl-nagoya/ruri-v3-70m"
os.environ["SMART_TOKEN_LIMIT"] = "16000"
os.environ["BROWSE_CHUNK_MAX_LENGTH"] = "8192"
os.environ["LANGUAGE"] = "japanese"

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

    return f"""あなたは調査ルーターです。
次のテーマを、内部知識だけで十分か、軽いWeb検索で足りるか、深い調査が必要かに分類してください。

判定基準:
- internal: 一般論、概念説明、既知知識で完結するもの
- web: 公式情報、料金、仕様、リリース、比較、ランキング、時点依存の事実を少数の検索結果で確認できるもの
- deep: 複数ソースの読み込み、背景整理、広い比較、論点整理、評価の深掘りが必要なもの

特に次は web を選んでください:
- 製品・モデル名の比較
- 価格/コスパ/料金比較
- 最新API、リリース、バージョン差分
- 実在するサービスの性能差や仕様差

特に次は deep を選んでください:
- 俯瞰的な調査や市場整理が必要なもの
- 論点が多く、要点の取捨選択が必要なもの
- 単なる事実確認ではなく、背景や解釈まで整理したいもの
- かなり幅広いソースをまたいで結論を作る必要があるもの

出力は次のいずれか1語だけ:
internal
web
deep

テーマ:
{theme}

調べたい理由:
{why_now_text}

背景・前提:
{context_text}
"""


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
            provider="openai",
            model=config.RESEARCH_ROUTER_MODEL,
            prompt=prompt,
            temperature=config.RESEARCH_ROUTER_TEMPERATURE,
            max_tokens=config.RESEARCH_ROUTER_MAX_TOKENS,
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
        from obsidian_ai_hub.handler.obsidian_vault_retriever import search_obsidian_vault_sync
        vault_search_results = search_obsidian_vault_sync.invoke({"query": theme, "k": 5})
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
        return f"""
あなたは調査アシスタントです。
このモードはDeepResearchではありません。
目的は、Web検索結果で最新性・公式性・出典を軽く確認しつつ、必要に応じて一般知識で補い、実用的で短めの回答を作ることです。
以下のテーマについて、Web検索結果、参考文脈、必要に応じた一般知識を使って回答してください。

## 情報源の優先順位
1. 公式・一次情報のWeb検索結果を最優先する
2. ユーザーの参考文脈・Vault検索結果は、ユーザー事情を補う情報として使ってよい
3. 検索結果だけでは不足する場合、一般的で時点依存しにくい知識に限り、内部知識で補ってよい
4. 地域固有・制度・数値・最新状況は、検索結果にない限り断定しない

## 追加検索の実行
提供された「検索結果」だけでは情報が不足している場合や、より具体的な事実確認が必要な場合は、
`web_search` ツールを使用して追加のWeb検索を行ってください。
ただし、際限なく検索を繰り返すのではなく、目的の回答を構成するのに十分な情報が得られた時点で回答をまとめてください。

## 回答の要件
- テーマが質問形式でない場合は、冒頭で「推測した調査意図」を1〜2文で示す
- 公式・一次情報・時点依存の事実を優先する
- 不確かな情報は断定しない
- 検索結果が不足している場合は、「検索結果だけでは不足している点」も最後に短く示す
- 回答の長さ:{output_style_text}

テーマ:
{theme}
{why_now_section}{context_section}
検索結果:
{search_results}

"""

    if normalized_mode == RESEARCH_MODE_DEEP:
        return f"""
テーマ:
{theme}
{why_now_section}{context_section}
想定する調査の粒度:
{output_style_text}

"""

    return f"""
あなたは調査アシスタントです。与えられたテーマについて、内部知識と参考文脈をもとに回答してください。

# 回答ルール
- 参考文脈は、ユーザーの状況理解のための補助情報として扱う。
- テーマと明確に関係する文脈だけ使う。
- 関係が弱い文脈は使わない。
- 参考文脈に書かれていることと、一般論を混同しない
- 一般論として述べる場合は、一般論であることが分かるように書く
- 時点依存・地域固有・法制度・医療・安全に関わることは、必要に応じてWeb確認を勧める
- 推測する場合は「可能性がある」「仮説として」と表現する
- ユーザーの個人的背景を過度に深読みしない

テーマ:
{theme}
{why_now_section}{context_section}
回答の長さ:
{output_style_text}

"""


def build_title_prompt(theme: str, expanded_prompt: str) -> str:
    return f"""あなたはObsidianの保存用タイトルを作る編集者です。
以下のテーマと調査用プロンプトに基づいて、Markdownファイル名に使いやすい短い日本語タイトルを1つだけ返してください。

要件:
- 50文字前後を目安にする
- 100文字を超えない
- 余計な説明、番号、箇条書き、引用符を付けない
- ファイル名に使う前提なので、できるだけ簡潔にする

テーマ:
{theme}

調査用プロンプト:
{expanded_prompt}
"""


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
    # return llm_client.generate_llm_response(
    #     provider="openai",
    #     model=config.RESEARCH_PROMPT_MODEL,
    #     prompt=build_research_prompt(
    #         theme,
    #         mode=mode,
    #         context=context,
    #         output_style=output_style,
    #         why_now=why_now,
    #     ),
    #     temperature=config.RESEARCH_PROMPT_TEMPERATURE,
    #     max_tokens=config.RESEARCH_PROMPT_MAX_TOKENS,
    # ).strip()


def generate_research_title(theme: str, expanded_prompt: str) -> str:
    title = llm_client.generate_llm_response(
        provider="openai",
        model=config.RESEARCH_PROMPT_MODEL,
        prompt=build_title_prompt(theme, expanded_prompt),
        temperature=0.0,
        max_tokens=64,
    ).strip()
    title = title.strip().strip('"').strip("'")
    if not title:
        title = theme
    return title


async def _run_gpt_researcher(query: str) -> str:
    try:
        from gpt_researcher import GPTResearcher  # type: ignore
    except Exception as exc:
        raise RuntimeError("gpt_researcher package is required for research agent") from exc

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
    query_generation_prompt = f"""
あなたはTavily検索用の短い検索クエリを作成するアシスタントです。
ユーザーから提供されたテーマに基づいて、最も関連性の高い情報を取得するための1行の検索クエリだけを返してください。
余計な説明や前置き、コードフェンスは禁止です。

テーマ:
{theme}

出力例:
OpenAI GPT-5.5 最新情報
"""
    search_query = llm_client.generate_llm_response(
        provider="openai",
        model=config.RESEARCH_ROUTER_MODEL,
        prompt=query_generation_prompt,
        temperature=config.RESEARCH_ROUTER_TEMPERATURE,
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
            provider="openai",
            model=config.RESEARCH_SMART_MODEL,
            prompt=prompt,
            temperature=config.RESEARCH_PROMPT_TEMPERATURE,
            max_tokens=config.RESEARCH_PROMPT_MAX_TOKENS,
        ).strip()

    if normalized_mode == RESEARCH_MODE_WEB:
        from obsidian_ai_hub.handler.web_search import web_search
        from obsidian_ai_hub.handler.web_extract import web_extract
        return llm_client.generate_llm_response_with_tools(
            provider="openai",
            model=config.RESEARCH_SMART_MODEL,
            prompt=prompt,
            tools=[web_search, web_extract],
            temperature=config.RESEARCH_PROMPT_TEMPERATURE,
            max_tokens=config.RESEARCH_PROMPT_MAX_TOKENS,
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
