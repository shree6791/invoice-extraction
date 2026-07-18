"""GET /api/page-image/{doc_id}"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.dataset.loader import pdf_path
from backend.services.layout import render_page_png

router = APIRouter(tags=["page-image"])


@router.get("/api/page-image/{doc_id}")
def page_image(doc_id: str, page: int = 0):
    pdf = pdf_path(doc_id)
    if not pdf.exists():
        raise HTTPException(404, f"PDF not found: {doc_id}")
    try:
        png = render_page_png(pdf, page_idx=page, dpi=140)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return Response(content=png, media_type="image/png")
