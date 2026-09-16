"""Deprecated research theme suggestion module.

The direct LLM candidate generation logic formerly in this module has been
replaced by the Task Agent intake flow (``--suggest-research-theme``) and the
``research_theme_propose`` capability.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_suggestions() -> list:
    logger.warning(
        "research.suggest.build_suggestions is deprecated; use Task Agent or research_theme_propose capability."
    )
    return []


def main() -> list:
    logger.warning(
        "research.suggest.main is deprecated; use --suggest-research-theme CLI flag."
    )
    return []
