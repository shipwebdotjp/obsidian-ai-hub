from __future__ import annotations

from pathlib import Path
from typing import Optional

from obsidian_ai_hub.utils import config, llm_client, prompt

from obsidian_ai_hub.research.runner import (
    RESEARCH_MODE_DEEP,
    RESEARCH_MODE_INTERNAL,
    RESEARCH_MODE_WEB,
    ResearchReport,
    ResearchRunResult,
    build_markdown,
    build_research_prompt,
    build_web_research_router_prompt,
    collect_research_context,
    conduct_research,
    generate_research_title,
    make_research_filename,
    route_research_topic,
    run_research,
    run_theme_research,
    save_markdown,
    save_research_to_vault,
    write_lines_atomic,
)
from obsidian_ai_hub.research.runner import main as _runner_main


def main(
    theme: Optional[str] = None,
    *,
    context: Optional[str] = None,
    mode: str = "auto",
    output_style: Optional[str] = None,
) -> ResearchRunResult:
    return _runner_main(theme=theme, context=context, mode=mode, output_style=output_style)
