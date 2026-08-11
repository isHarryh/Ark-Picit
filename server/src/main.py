"""Server startup: assembles the FastAPI app, loads config, and runs uvicorn.

Settings come from ``config.toml`` in the server data directory (see
:mod:`server.src.config`); the server refuses to start without it. The package
is ``server.src`` (a unique namespace under the repo root), so the unified entry
point imports it via ``from server.src.main import run_server``.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

from .errors import register_error_handler
from .routers.api import announcement, explore, meta

app = FastAPI(title="Ark Picit Plaza", version="2")
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=1)
app.include_router(meta.router)
app.include_router(announcement.router)
app.include_router(explore.router)
register_error_handler(app)


def run_server() -> None:
    """Start the uvicorn server; blocks until shutdown."""
    import uvicorn

    from . import config, db

    settings = config.load_config()
    db.init_db(config.DATA_DIR / "server.db")

    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
