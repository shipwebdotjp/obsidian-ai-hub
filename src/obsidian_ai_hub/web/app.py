import logging
import os
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
    if host is None:
        host = os.getenv("OBSIDIAN_AI_HUB_HOST", DEFAULT_HOST)
    if port is None:
        port = int(os.getenv("OBSIDIAN_AI_HUB_PORT", str(DEFAULT_PORT)))
    if token is None:
        token = os.getenv("OBSIDIAN_AI_HUB_API_TOKEN", "")
    _configure_security(token)

    app = FastAPI(title="obsidian-ai-hub Memory Review", version="0.1.0")
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

    @app.on_event("startup")
    def on_startup():
        from obsidian_ai_hub.research.runner import cleanup_stale_jobs
        from obsidian_ai_hub.coding.store import mark_interrupted_runs_on_startup

        cleanup_stale_jobs()
        mark_interrupted_runs_on_startup()

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
    )
