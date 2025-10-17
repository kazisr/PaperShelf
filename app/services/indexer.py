from __future__ import annotations

import hashlib
import json
import logging
import pathlib
from typing import Optional, List

import fitz  # PyMuPDF

from app.config import THUMBS_DIR
from app.db import Session, PaperORM
from app.utils.pdf_tools import (
    file_safe,
    extract_title_authors_year_from_bytes,
    render_thumbnail,   # image-first + very small
    system_abstract,
)
from app.services.metadata import autofetch_metadata

logger = logging.getLogger("papershelf")


def _md5(b: bytes) -> str:
    m = hashlib.md5()
    m.update(b)
    return m.hexdigest()


def _read_first_pages_text(pdf_bytes: bytes, max_pages: int = 3) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        n = min(max_pages, len(doc))
        return "\n\n".join(doc[i].get_text("text") for i in range(n))


async def index_pdf(
    pdf_path: pathlib.Path,
    relative_path: str,
    year_hint: Optional[str] = None,
    authors_hint: Optional[List[str]] = None,
    title_hint: Optional[str] = None,
) -> str:
    pdf_path = pathlib.Path(pdf_path)
    assert pdf_path.exists(), f"PDF missing: {pdf_path}"

    raw = pdf_path.read_bytes()
    file_hash = _md5(raw)
    paper_id = file_hash[:16]

    extracted_title, extracted_authors, extracted_year = extract_title_authors_year_from_bytes(raw)
    if not extracted_title:
        extracted_title = title_hint
    if not extracted_authors and authors_hint:
        extracted_authors = authors_hint
    if not extracted_year and year_hint:
        extracted_year = year_hint

    first_pages_text = _read_first_pages_text(raw, max_pages=3)
    abstract_text = system_abstract(first_pages_text)
    abstract_source = "system" if abstract_text else None

    meta = await autofetch_metadata(first_pages_text, extracted_title)

    final_title = (meta.get("title") if meta and meta.get("title") else extracted_title) or "Untitled"
    final_authors = (meta.get("authors") if meta and meta.get("authors") else extracted_authors) or []
    final_year = (meta.get("year") if meta and meta.get("year") else extracted_year) or None
    if not abstract_text and meta and meta.get("abstract"):
        abstract_text = meta["abstract"]
        abstract_source = abstract_source or "external"

    # -------- Thumbnail (prefer embedded image; else top half) --------
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    thumb_name = f"{file_safe(pdf_path.stem)}.png"  # keep .png to avoid breaking frontend
    thumb_path = THUMBS_DIR / thumb_name
    try:
        thumb_path.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        render_thumbnail(
            raw,
            thumb_path,
            search_pages=5,          # more permissive, find images better
            min_image_pixels=150*150,
            zoom=1.5,
            top_ratio=0.5,
            max_width=400,           # very small
            jpeg_quality=28,         # used if suffix is .jpg; PNG fallback quantized
        )
        logger.info(f"Thumbnail written: {thumb_path}")
        thumb_rel = f"thumbs/{thumb_name}"
    except Exception:
        logger.exception("Thumbnail render failed")
        thumb_rel = None

    # -------- Persist --------
    with Session() as s:
        existing = s.get(PaperORM, paper_id)
        if existing:
            paper = existing
        else:
            paper = PaperORM(id=paper_id)

        paper.file_hash = file_hash
        paper.title = final_title
        paper.authors_json = json.dumps(final_authors or [], ensure_ascii=False)
        paper.year = str(final_year) if final_year else None
        paper.abstract = abstract_text
        paper.abstract_source = abstract_source
        paper.path = relative_path
        paper.thumb_path = thumb_rel

        if meta:
            paper.doi = meta.get("doi") or paper.doi
            paper.arxiv_id = meta.get("arxiv_id") or paper.arxiv_id
            paper.venue = meta.get("venue") or paper.venue
            paper.published_at = meta.get("published_at") or paper.published_at
            paper.url = meta.get("url") or paper.url

        s.add(paper)
        s.commit()

    logger.info(f"Indexed paper id={paper_id} title={final_title!r} path={relative_path}")
    return paper_id