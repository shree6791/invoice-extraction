"""GET / — serve the demo frontend."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from backend.settings.config import STATIC_DIR

router = APIRouter(tags=["frontend"])


@router.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
