"""Reconnectable run execution + SSE delivery (docs/run-sse).

Thin package root: application logic lives in submodules.
"""

from obsidian_ai_hub.runs.instance import get_instance_id

__all__ = ["get_instance_id"]
