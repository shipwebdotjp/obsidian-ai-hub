"""Test utilities for E2E and exploration environments.

All functions in this package raise RuntimeError when called outside test mode
(ENV=test or OBSIDIAN_AI_HUB_TESTING=1).
"""

import os


def ensure_test_mode() -> None:
    if os.environ.get("ENV", "").lower() != "test" and os.environ.get(
        "OBSIDIAN_AI_HUB_TESTING"
    ) != "1":
        raise RuntimeError(
            "obsidian_ai_hub.testing is only usable with ENV=test or "
            "OBSIDIAN_AI_HUB_TESTING=1"
        )
