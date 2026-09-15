"""CLI intake for the Task Agent: submit a request and return immediately."""

from __future__ import annotations

import os
from typing import Any, Optional

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.utils import config


def build_detail_url(
    task_id: str, host: Optional[str] = None, port: Optional[int] = None
) -> str:
    """Build the task detail URL, preferring the public web URL setting."""
    base = config.OBSIDIAN_AI_HUB_WEB_URL
    if not base:
        resolved_host = host or os.getenv("OBSIDIAN_AI_HUB_HOST", "127.0.0.1")
        resolved_port = port or int(os.getenv("OBSIDIAN_AI_HUB_PORT", "8765"))
        base = f"http://{resolved_host}:{resolved_port}"
    return f"{base}/task-agent/{task_id}"


def submit_request(
    prompt_text: str,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> dict[str, Any]:
    """Create a task in ``queued`` status and return its intake receipt."""
    if not prompt_text or not prompt_text.strip():
        raise ValueError("Task request must not be blank.")
    task = task_store.create_task(prompt_text)
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "detail_url": build_detail_url(task["task_id"], host, port),
    }


def main_task_agent(
    prompt_text: str,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> None:
    """CLI entry: print the intake receipt and exit."""
    receipt = submit_request(prompt_text, host, port)
    print(f"task_id: {receipt['task_id']}")
    print(f"status: {receipt['status']}")
    print(f"detail_url: {receipt['detail_url']}")
