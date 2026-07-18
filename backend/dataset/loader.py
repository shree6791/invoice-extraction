"""DocILE path helpers and annotation I/O."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.settings.config import DOCILE_ROOT


@dataclass
class DocMeta:
    doc_id: str
    cluster_id: int
    page_count: int
    document_type: str
    has_fields: bool


def load_split_ids(split: str = "trainval") -> list[str]:
    path = DOCILE_ROOT / f"{split}.json"
    return json.loads(path.read_text())


def annotation_path(doc_id: str) -> Path:
    return DOCILE_ROOT / "annotations" / f"{doc_id}.json"


def pdf_path(doc_id: str) -> Path:
    return DOCILE_ROOT / "pdfs" / f"{doc_id}.pdf"


def load_annotation(doc_id: str) -> dict[str, Any]:
    return json.loads(annotation_path(doc_id).read_text())


def load_doc_meta(doc_id: str) -> DocMeta | None:
    path = annotation_path(doc_id)
    if not path.exists() or not pdf_path(doc_id).exists():
        return None
    ann = json.loads(path.read_text())
    meta = ann.get("metadata", {})
    has_fields = bool(ann.get("field_extractions")) or bool(
        ann.get("line_item_extractions")
    )
    if not has_fields:
        return None
    return DocMeta(
        doc_id=doc_id,
        cluster_id=int(meta.get("cluster_id", -1)),
        page_count=int(meta.get("page_count", 1)),
        document_type=str(meta.get("document_type", "")),
        has_fields=True,
    )
