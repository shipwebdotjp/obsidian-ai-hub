import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from obsidian_ai_hub.web.api import router as api_router

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# Populated at startup by main.py --serve. Default port/host are loopback.
HOST: str = DEFAULT_HOST
PORT: int = DEFAULT_PORT
TOKEN: str = os.getenv("OBSIDIAN_AI_HUB_API_TOKEN", "")

FRONTEND_DIST = Path(
    os.getenv(
        "OBSIDIAN_AI_HUB_FRONTEND_DIST",
        Path(__file__).resolve().parents[3] / "frontend" / "dist",
    )
)


def build_uvicorn_log_config() -> dict:
    """Uvicorn logging config with timestamps on access lines.

    The default access format carries no timestamp, which makes it impossible
    to tell pre-restart requests apart from current ones in the launchd logs
    (e.g. when dating a past 400). Imported lazily so module import never
    requires uvicorn.
    """
    import copy

    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    access_formatter = config["formatters"]["access"]
    access_formatter["fmt"] = (
        '%(asctime)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    )
    access_formatter["use_colors"] = False
    return config


def _configure_security(token: str) -> None:
    global TOKEN
    TOKEN = token
    if not TOKEN:
        raise RuntimeError(
            "OBSIDIAN_AI_HUB_API_TOKEN is required to serve the web API. "
            "Set it in the environment before launching. All API endpoints "
            "require bearer-token authentication."
        )


def create_app(
    host: str | None = None, port: int | None = None, token: str | None = None
) -> FastAPI:
    from obsidian_ai_hub.utils.config import (
        IS_TEST_ENV,
        TEST_WORKSPACE,
        _load_yaml_config,
        update_web_status,
        validate_vault_registry,
    )

    update_web_status("starting")
    try:
        current_config = _load_yaml_config()
        validate_vault_registry(
            current_config,
            is_test_env=IS_TEST_ENV,
            test_workspace=TEST_WORKSPACE if IS_TEST_ENV else None,
        )
    except Exception as exc:
        err_msg = str(exc)
        update_web_status("failed", error=err_msg)
        logger.error("Web server startup failed due to Vault Registry error: %s", err_msg)
        raise RuntimeError(f"Vault Registry validation failed: {err_msg}") from exc

    update_web_status("ready")

    if host is None:
        host = os.getenv("OBSIDIAN_AI_HUB_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.getenv("OBSIDIAN_AI_HUB_PORT", str(DEFAULT_PORT)))
    if token is None:
        token = os.getenv("OBSIDIAN_AI_HUB_API_TOKEN", "")
    _configure_security(token)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from obsidian_ai_hub.research.runner import cleanup_stale_jobs

        try:
            cleanup_stale_jobs()
        except Exception:
            logger.exception("Research stale-job cleanup failed")

        # Pytest isolation (ENV=test) must not start background workers nor
        # touch recovery; tests drive execute_* explicitly.
        try:
            from obsidian_ai_hub.utils import config as app_config

            is_test = bool(getattr(app_config, "IS_TEST_ENV", False))
        except Exception:
            is_test = False
        if is_test:
            yield
            return

        from obsidian_ai_hub.runs.manager import run_worker_lifespan

        async with run_worker_lifespan():
            yield

    app = FastAPI(
        title="obsidian-ai-hub Memory Review", version="0.1.0", lifespan=lifespan
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv(
            "OBSIDIAN_AI_HUB_CORS_ORIGINS", "http://127.0.0.1:5173"
        ).split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "auth_required": True,
        }

    if FRONTEND_DIST.exists():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/")
        def index():
            return FileResponse(FRONTEND_DIST / "index.html")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})

            dist_root = FRONTEND_DIST.resolve()
            try:
                target = (dist_root / full_path).resolve()
            except (OSError, RuntimeError):
                target = None
            if (
                target is not None
                and target.is_file()
                and target.is_relative_to(dist_root)
            ):
                return FileResponse(target)
            return FileResponse(FRONTEND_DIST / "index.html")
    else:

        @app.get("/")
        def index_missing():
            return JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "frontend is not built. Run `make build-web` (or "
                        "`cd frontend && npm ci && npm run build`) and try again."
                    )
                },
            )

    return app


def run() -> None:
    import uvicorn

    uvicorn.run(
        create_app(host=HOST, port=PORT, token=TOKEN),
        host=HOST,
        port=PORT,
        log_level="info",
        log_config=build_uvicorn_log_config(),
    )
