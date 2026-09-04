"""Lifespan worker manager: lock, startup/shutdown recovery, worker tasks."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from obsidian_ai_hub.runs.instance import RunWorkerLock, get_instance_id

logger = logging.getLogger(__name__)

_manager_lock: Optional[RunWorkerLock] = None
_manager_instance_id: Optional[str] = None
_worker_tasks: list[asyncio.Task] = []
_worker_stop: Optional[asyncio.Event] = None


def is_worker_owner() -> bool:
    return _manager_lock is not None and _manager_lock.is_held()


def current_instance_id() -> Optional[str]:
    return _manager_instance_id


def startup_recovery(instance_id: str) -> dict[str, Any]:
    """Interrupt前インスタンス所有の非終端run (lock取得成功時のみ呼ぶ)."""
    from obsidian_ai_hub.agents import store as agent_store
    from obsidian_ai_hub.coding import store as coding_store

    agent_count = 0
    coding_count = 0
    try:
        agent_count = agent_store.mark_other_instances_interrupted(instance_id)
    except Exception:
        logger.exception("Agent startup recovery failed")
    try:
        coding_count = coding_store.mark_other_instances_interrupted(instance_id)
    except Exception:
        logger.exception("Coding startup recovery failed")
    # 期限切れ terminal run の event log を掃除 (確定データは残す).
    try:
        agent_store.purge_old_run_events()
    except Exception:
        logger.exception("Agent event purge failed")
    try:
        coding_store.purge_old_run_events()
    except Exception:
        logger.exception("Coding event purge failed")
    return {"agent_interrupted": agent_count, "coding_interrupted": coding_count}


def shutdown_recovery(instance_id: str) -> dict[str, Any]:
    """自インスタンスの非終端runだけを interrupted 化し cancel 通知する."""
    from obsidian_ai_hub.agents import store as agent_store
    from obsidian_ai_hub.coding import store as coding_store

    # 明示 cancel 通知: coding の実行中 CLI へ cancel_event を立てる.
    try:
        from obsidian_ai_hub.coding import service as coding_service

        with coding_service._JOBS_GUARD:
            owned = [
                rid
                for rid, (_ev, _repo) in list(coding_service._RUNNING_JOBS.items())
            ]
        for rid in owned:
            try:
                with coding_service._JOBS_GUARD:
                    entry = coding_service._RUNNING_JOBS.get(rid)
                    if entry is not None:
                        entry[0].set()
            except Exception:
                pass
    except Exception:
        logger.exception("Coding cancel notify on shutdown failed")

    agent_count = 0
    coding_count = 0
    try:
        agent_count = agent_store.mark_runs_interrupted(
            only_mine=True, owner_instance_id=instance_id
        )
    except Exception:
        logger.exception("Agent shutdown recovery failed")
    try:
        coding_count = coding_store.mark_own_runs_interrupted(instance_id)
    except Exception:
        logger.exception("Coding shutdown recovery failed")
    return {"agent_interrupted": agent_count, "coding_interrupted": coding_count}


async def _start_workers(instance_id: str) -> None:
    global _worker_tasks, _worker_stop
    from obsidian_ai_hub.runs.agent_worker import agent_worker_loop
    from obsidian_ai_hub.runs.coding_worker import coding_worker_loop

    if _worker_tasks:
        return
    _worker_stop = asyncio.Event()
    _worker_tasks = [
        asyncio.create_task(agent_worker_loop(instance_id, _worker_stop), name="agent-run-worker"),
        asyncio.create_task(coding_worker_loop(instance_id, _worker_stop), name="coding-run-worker"),
    ]
    logger.info("Run workers started for instance %s", instance_id)


async def _stop_workers() -> None:
    global _worker_tasks, _worker_stop
    if _worker_stop is not None:
        _worker_stop.set()
    for task in list(_worker_tasks):
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        except (asyncio.CancelledError, Exception):
            pass
    _worker_tasks = []
    _worker_stop = None


@asynccontextmanager
async def run_worker_lifespan():
    """FastAPI lifespan: lock取得成功時のみ worker 起動 + recovery."""
    global _manager_lock, _manager_instance_id
    instance_id = get_instance_id()
    _manager_instance_id = instance_id
    lock = RunWorkerLock()
    acquired = await asyncio.to_thread(lock.acquire)
    if not acquired:
        # 生存中プロセスが lock 保持: worker 起動せず run 更新もしない.
        logger.warning(
            "Another app process holds the run-worker lock; workers disabled for %s",
            instance_id,
        )
        _manager_lock = None
        try:
            yield {"instance_id": instance_id, "worker_owner": False}
        finally:
            _manager_instance_id = None
        return

    _manager_lock = lock
    try:
        await asyncio.to_thread(startup_recovery, instance_id)
        await _start_workers(instance_id)
        try:
            yield {"instance_id": instance_id, "worker_owner": True}
        finally:
            await _stop_workers()
            await asyncio.to_thread(shutdown_recovery, instance_id)
    finally:
        try:
            await asyncio.to_thread(lock.release)
        except Exception:
            pass
        _manager_lock = None
        _manager_instance_id = None
