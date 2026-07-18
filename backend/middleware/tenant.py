"""Tenant resolution middleware.

Reads X-API-Key header → resolves Tenant from control plane →
injects into request.state.tenant for all downstream handlers.

Production behaviour this mock demonstrates:
  - Every request is tenant-scoped before touching any infra
  - Unknown/missing key → demo tenant (not 401) for local dev friendliness
  - In production: unknown key → 401, invalid key → 403

Production swap:
    Replace InMemoryControlPlane with PostgresControlPlane + Redis edge cache.
    Add 401/403 enforcement once auth is wired up.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.infra.control_plane import InMemoryControlPlane, Tenant

_control_plane = InMemoryControlPlane()

API_KEY_HEADER = "X-API-Key"


class TenantMiddleware(BaseHTTPMiddleware):
    """Inject tenant context into every request before it hits a route."""

    async def dispatch(self, request: Request, call_next) -> Response:
        api_key = request.headers.get(API_KEY_HEADER)
        tenant: Tenant = _control_plane.get_tenant(api_key)
        request.state.tenant = tenant
        return await call_next(request)


def current_tenant(request: Request) -> Tenant:
    """FastAPI dependency — pull resolved tenant from request state.

    Usage:
        from backend.middleware.tenant import current_tenant
        from fastapi import Depends

        @router.post("/api/jobs")
        async def enqueue_job(req: ExtractRequest,
                              request: Request,
                              tenant: Tenant = Depends(current_tenant)):
            ...
    """
    return request.state.tenant
