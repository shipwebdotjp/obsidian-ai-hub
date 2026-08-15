"""Exploration server for E2E testing.

Creates an isolated temporary workspace, seeds demo data, and serves the
FastAPI app on a loopback address.

Usage:
    make e2e-serve

Or directly:
    uv run python -m obsidian_ai_hub.testing.e2e_server [--host HOST] [--port PORT]
"""

import os
import sys

# Must be set before any application import so config.py enters test mode.
# Force ENV=test so it never inherits any external ENV like jules.
os.environ["ENV"] = "test"

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


E2E_SERVER_TOKEN = "test-api-token"


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E exploration server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--seed",
        default="demo",
        help="Seed scenario to load (demo, …)",
    )
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "::1", "localhost"):
        print("E2E server must bind to a loopback address only.", file=sys.stderr)
        sys.exit(1)

    # Verify frontend build before seeding (fast failure).
    frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if not (frontend_dist / "index.html").exists():
        print(
            "frontend/dist/index.html not found. Run: make build-web",
            file=sys.stderr,
        )
        sys.exit(1)

    # Now safe to import application modules — config.py already read ENV=test.
    import uvicorn
    from obsidian_ai_hub.testing.seed import seed_memory_demo_data, seed_hitl_demo_data
    from obsidian_ai_hub.utils import config as app_config
    from obsidian_ai_hub.web.app import create_app

    if app_config.IS_TEST_ENV:
        print(f"Test workspace: {app_config.TEST_WORKSPACE}", flush=True)
        print("Will be cleaned up on exit.", flush=True)

    if args.seed == "demo":
        seed_memory_demo_data()
        seed_hitl_demo_data()
        print("Seeded demo data.", flush=True)
    else:
        print(f"Unknown seed scenario: {args.seed}", file=sys.stderr)
        sys.exit(1)

    app = create_app(host=args.host, port=args.port, token=E2E_SERVER_TOKEN)

    print(f"\nE2E server: http://{args.host}:{args.port}", flush=True)
    print(f"Bearer token: {E2E_SERVER_TOKEN}", flush=True)
    print("Press Ctrl-C to stop.\n", flush=True)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
