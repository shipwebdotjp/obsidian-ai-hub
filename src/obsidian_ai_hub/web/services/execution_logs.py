from typing import Any, Optional


# --- Execution Log services ---

def list_execution_logs(
    kind: Optional[str] = None,
    status: Optional[str] = None,
    command: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    from obsidian_ai_hub.utils import execution_logger
    items, total = execution_logger.list_execution_logs(
        kind=kind,
        status=status,
        command=command,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


def get_command_run_detail(run_id: str) -> Optional[dict]:
    from obsidian_ai_hub.utils import execution_logger
    return execution_logger.get_command_run_detail(run_id)


def get_llm_call_detail(call_id: str) -> Optional[dict]:
    from obsidian_ai_hub.utils import execution_logger
    return execution_logger.get_llm_call_detail(call_id)
