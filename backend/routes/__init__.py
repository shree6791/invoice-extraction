"""Register all HTTP route modules."""

from __future__ import annotations

from fastapi import FastAPI

from backend.routes import chat, extract, frontend, health, jobs, page_image, samples, tenants


def include_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(tenants.router)
    app.include_router(samples.router)
    app.include_router(page_image.router)
    app.include_router(extract.router)
    app.include_router(jobs.router)
    app.include_router(chat.router)
    app.include_router(frontend.router)
