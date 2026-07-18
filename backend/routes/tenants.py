"""GET /api/tenants — list mock companies for the demo UI."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from backend.settings.config import ROOT

router = APIRouter(tags=["tenants"])

TENANTS_DIR = ROOT / "data" / "tenants"


@router.get("/api/tenants")
def list_tenants():
    """Return all mock tenant companies with their metadata."""
    tenants = []
    if not TENANTS_DIR.exists():
        return {"tenants": []}
    for folder in sorted(TENANTS_DIR.iterdir()):
        manifest_path = folder / "manifest.json"
        if folder.is_dir() and manifest_path.exists():
            m = json.loads(manifest_path.read_text())
            tenants.append({
                "slug": m["slug"],
                "tier": m["tier"],
                "region": m["region"],
                "doc_count": len(m.get("doc_ids", [])),
            })
    return {"tenants": tenants}
