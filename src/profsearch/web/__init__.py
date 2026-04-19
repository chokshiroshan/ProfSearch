"""ProfSearch internal web UI."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from profsearch.config import get_settings
from profsearch.db.session import create_session_factory, initialize_database
from profsearch.embedding.encoder import EmbeddingEncoder

_WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

_READ_ONLY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_READ_ONLY_ALLOWLIST = {"/prof/{professor_id}/draft-email"}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = get_settings()
    initialize_database(settings)
    app.state.settings = settings
    app.state.session_factory = create_session_factory(settings)
    app.state.encoder = EmbeddingEncoder(settings)
    yield


def create_app() -> FastAPI:
    read_only = os.environ.get("PROFSEARCH_READ_ONLY", "").strip() in {"1", "true", "yes"}

    app = FastAPI(title="ProfSearch", lifespan=_lifespan)
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

    if read_only:
        @app.middleware("http")
        async def read_only_guard(request: Request, call_next):
            if request.method in _READ_ONLY_METHODS:
                # Allow the email drafter (it's POST but read-only in effect)
                if request.url.path.endswith("/draft-email"):
                    return await call_next(request)
                return Response("Read-only mode: write operations are disabled.", status_code=403)
            return await call_next(request)

    from profsearch.web.routes import router

    app.include_router(router)
    return app
