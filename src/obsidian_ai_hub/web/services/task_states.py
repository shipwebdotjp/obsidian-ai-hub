from typing import Any, List


def list_task_states() -> List[dict[str, Any]]:
    from obsidian_ai_hub.utils import execution_logger

    return execution_logger.list_task_states()