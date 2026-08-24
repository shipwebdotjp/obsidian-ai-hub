from fastapi import APIRouter

from obsidian_ai_hub.web.routes import (
    agents,
    dashboard,
    execution_logs,
    healthcare,
    hitl,
    line,
    memory,
    people,
    planner,
    projects,
    research,
    task_config,
    task_states,
    vault,
)

router = APIRouter(prefix="/api/v1")

router.include_router(agents.router)
router.include_router(line.router)
router.include_router(memory.router)
router.include_router(research.router)
router.include_router(vault.router)
router.include_router(dashboard.router)
router.include_router(projects.router)
router.include_router(people.router)
router.include_router(task_config.router)
router.include_router(execution_logs.router)
router.include_router(task_states.router)
router.include_router(hitl.router)
router.include_router(planner.router)
router.include_router(healthcare.router)
