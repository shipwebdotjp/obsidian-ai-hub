from __future__ import annotations

import subprocess
import sys

import pytest

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.main import register_hitl_handlers
from obsidian_ai_hub.hitl.dispatcher import get_handler


def test_hitl_package_does_not_import_research_at_import_time():
    """The obsidian_ai_hub.hitl package must remain free of domain imports."""
    script = (
        "import obsidian_ai_hub.hitl as h; "
        "import sys; "
        "names = sorted(m for m in sys.modules if m.startswith('obsidian_ai_hub.')); "
        "research_modules = [n for n in names if ('research' in n or 'handler' in n)]; "
        "import json; "
        "print(json.dumps({'all': names, 'research': research_modules}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr

    import json as _json
    data = _json.loads(result.stdout)
    research = data.get("research", [])
    assert research == [], f"Unexpected domain imports in hitl: {research}"


def test_task_runner_preset_contains_hitl_dispatch():
    """The task runner preset dictionary must include --hitl-dispatch."""
    from obsidian_ai_hub.task_runner import PRESET_FLAGS

    assert "--hitl-dispatch" in PRESET_FLAGS, (
        "PRESET_FLAGS must contain --hitl-dispatch key"
    )
    assert PRESET_FLAGS["--hitl-dispatch"] is not None, (
        "PRESET_FLAGS['--hitl-dispatch'] must have a non-None description"
    )


def test_register_hitl_handlers_registers_research_handler(test_memory_db_path):
    """register_hitl_handlers() must register the research.run_approved_suggestion handler."""
    register_hitl_handlers()

    handler = get_handler("research.run_approved_suggestion")
    assert handler is not None, (
        "research.run_approved_suggestion handler must be registered by register_hitl_handlers"
    )
