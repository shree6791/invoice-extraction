"""GET /api/samples"""

from __future__ import annotations

import json

from fastapi import APIRouter

from backend.dataset.loader import load_doc_meta
from backend.schemas.samples import SampleInfo, SamplesResponse
from backend.settings.config import TENANTS_DIR

router = APIRouter(tags=["samples"])


def _ids_for_company(company: str) -> list[str]:
    manifest = TENANTS_DIR / company / "manifest.json"
    if not manifest.exists():
        return []
    return json.loads(manifest.read_text()).get("doc_ids", [])


@router.get("/api/samples", response_model=SamplesResponse)
def list_samples(company: str | None = None) -> SamplesResponse:
    """?company=acme-corp → that company's 5 docs. No param → empty (UI always passes company)."""
    ids = _ids_for_company(company) if company else []
    samples: list[SampleInfo] = []
    for doc_id in ids:
        meta = load_doc_meta(doc_id)
        samples.append(SampleInfo(
            doc_id=doc_id,
            page_count=meta.page_count if meta else None,
            cluster_id=meta.cluster_id if meta else None,
            document_type=meta.document_type if meta else None,
        ))
    return SamplesResponse(samples=samples)
