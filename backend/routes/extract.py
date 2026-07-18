"""POST /api/extract"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas.extract import ExtractRequest
from backend.services.pipeline import run_pipeline

router = APIRouter(tags=["extract"])


@router.post("/api/extract")
def extract(req: ExtractRequest):
    try:
        result = run_pipeline(req.doc_id, for_eval=False, model=req.model)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return result.to_api_dict()
