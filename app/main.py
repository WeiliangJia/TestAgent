from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router, store
from app.config import settings


def create_app() -> FastAPI:
    settings.ensure_dirs()
    store.initialize()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(router)
    return app


app = create_app()
