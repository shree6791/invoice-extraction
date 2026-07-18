"""Control plane — tenant registry mock.

In production this is a globally replicated PostgreSQL table + CDN edge cache
(60s TTL). Every inbound request resolves: API key → tenant context.

Production swap:
    class PostgresControlPlane:
        async def get_tenant(self, api_key: str) -> Tenant | None:
            row = await conn.fetchrow(
                "SELECT * FROM tenants WHERE api_key = $1", api_key
            )
            return Tenant(**row) if row else None
        # + Redis edge cache layer in front (60s TTL)

Limitation of this mock: tenant registry is hardcoded at startup.
Changes require a server restart — no dynamic provisioning.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    slug: str           # human-readable name  e.g. "acme-corp"
    tier: str           # free | professional | enterprise
    region: str         # us-east-1 | eu-west-1 | ap-southeast-1
    shard_id: str       # shard-us-01 | shard-eu-01 ...
    quota_rps: int      # requests per second allowed


# Pre-seeded tenants — swap this for a DB lookup in production.
# Key = API key the client sends in X-API-Key header.
_REGISTRY: dict[str, Tenant] = {
    "demo-key-free": Tenant(
        tenant_id="t-001",
        slug="demo-free",
        tier="free",
        region="us-east-1",
        shard_id="shard-us-01",
        quota_rps=5,
    ),
    "demo-key-pro": Tenant(
        tenant_id="t-002",
        slug="demo-professional",
        tier="professional",
        region="us-east-1",
        shard_id="shard-us-01",
        quota_rps=100,
    ),
    "demo-key-enterprise": Tenant(
        tenant_id="t-003",
        slug="acme-corp",
        tier="enterprise",
        region="eu-west-1",
        shard_id="shard-eu-01",
        quota_rps=1000,
    ),
}

# Default tenant for requests with no API key (UI demo, local dev).
_DEMO_TENANT = Tenant(
    tenant_id="t-000",
    slug="demo",
    tier="free",
    region="us-east-1",
    shard_id="shard-us-01",
    quota_rps=10,
)


class InMemoryControlPlane:
    """In-memory tenant registry — mock of the global control-plane DB.

    Production swap: PostgresControlPlane with Redis edge cache.
    """

    def get_tenant(self, api_key: str | None) -> Tenant:
        """Resolve API key → Tenant. Returns demo tenant if key absent/unknown."""
        if not api_key:
            return _DEMO_TENANT
        return _REGISTRY.get(api_key, _DEMO_TENANT)

    def all_tenants(self) -> list[Tenant]:
        return list(_REGISTRY.values())
