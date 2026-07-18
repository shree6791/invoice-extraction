"""FastAPI application factory — lives at backend root."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.graph.graph import get_pipeline_graph
from backend.infra.cache import InMemoryCache
from backend.infra.jobs import InMemoryJobStore
from backend.infra.queue import InMemoryQueue
from backend.middleware.tenant import TenantMiddleware
from backend.routes import include_routers
from backend.settings.config import STATIC_DIR
from backend.workers.pipeline_worker import worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Compile LangGraph once at startup (not per request).
    get_pipeline_graph()

    # --- Scaled-arch mock: shared infra singletons ---
    # Swap these for real Kafka / Redis / PostgreSQL clients at scale.
    app.state.job_queue = InMemoryQueue()
    app.state.job_store = InMemoryJobStore()
    app.state.cache = InMemoryCache()

    # Single background worker. Scale by launching N workers or K8s pods.
    worker_task = asyncio.create_task(
        worker_loop(app.state.job_queue, app.state.job_store, app.state.cache)
    )

    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="Invoice Line-Item Extraction",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Tenant resolution: X-API-Key → Tenant injected into request.state.tenant.
    # Swap InMemoryControlPlane → PostgresControlPlane + Redis edge cache at scale.
    app.add_middleware(TenantMiddleware)
    include_routers(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
