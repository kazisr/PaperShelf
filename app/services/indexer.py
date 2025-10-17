from __future__ import annotations

import hashlib
import json
import logging
import pathlib
from typing import Optional, List
from datetime import date

import fitz  # PyMuPDF

from app.config import THUMBS_DIR
from app.db import Session, PaperORM
from app.utils.pdf_tools import (
    file_safe,
    extract_title_authors_year_from_bytes,
    render_thumbnail,
    system_abstract,
)
from app.services.metadata import autofetch_metadata

logger = logging.getLogger("papershelf")


def _md5(b: bytes) -> str:
    m = hashlib.md5(); m.update(b); return m.hexdigest()


def _read_first_pages_text(pdf_bytes: bytes, max_pages: int = 3) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        n = min(max_pages, len(doc))
        return "\n\n".join(doc[i].get_text("text") for i in range(n))


def _coerce_date_like(val: Optional[str]) -> Optional[date]:
    """
    Accepts 'YYYY', 'YYYY-MM', or 'YYYY-MM-DD' (also tolerates 'YYYY-M' or 'YYYY-M-D')
    and returns a date object. Missing month/day default to 1.
    Returns None if not parsable.
    """
    if not val:
        return None
    s = str(val).strip()
    # Normalize separators and strip trailing junk
    s = s.replace("/", "-").replace(".", "-")
    # Accept 'YYYY', 'YYYY-MM', 'YYYY-MM-DD'
    parts = s.split("-")
    try:
        if len(parts) == 1 and len(parts[0]) == 4:
            y = int(parts[0]); return date(y, 1, 1)
        elif len(parts) == 2:
            y = int(parts[0]); m = int(parts[1]); return date(y, max(1, m), 1)
        elif len(parts) >= 3:
            y = int(parts[0]); m = int(parts[1]); d = int(parts[2])
            return date(y, max(1, m), max(1, d))
    except Exception:
        return None
    return None


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

    # heuristics from PDF text
    extracted_title, extracted_authors, extracted_year = extract_title_authors_year_from_bytes(raw)
    if not extracted_title:
        extracted_title = title_hint
    if not extracted_authors and authors_hint:
        extracted_authors = authors_hint
    if not extracted_year and year_hint:
        extracted_year = year_hint

    print(extracted_title, extracted_authors, extracted_year)

    first_pages_text = _read_first_pages_text(raw, max_pages=3)
    abstract_text = system_abstract(first_pages_text)

    # external metadata — tolerate failures
    meta = None
    try:
        meta = await autofetch_metadata(first_pages_text, extracted_title or title_hint)
    except Exception as e:
        logger.exception("autofetch_metadata failed: %s", e)

    # merged values (priority handled in autofetch)
    final_title = (meta.get("title") if meta and meta.get("title") else extracted_title) or "Untitled"
    final_authors = (meta.get("authors") if meta and meta.get("authors") else extracted_authors) or []
    final_year = (meta.get("year") if meta and meta.get("year") else extracted_year) or None
    # print("META ->",meta)
    if meta and meta.get("abstract") and meta.get("title") and meta.get("authors") and meta.get("year"):
        data_src = "external"
        abstract_text = meta.get("abstract")

    if meta.get("abstract") or meta.get("title") or meta.get("year") or meta.get("authors"):
        data_src =  "system and external"
    else: data_src = "system"

    # -------- Thumbnail (prefer embedded image; else top half) --------
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    thumb_name = f"{file_safe(pdf_path.stem)}.png"  # keep .png to avoid breaking frontend paths
    thumb_path = THUMBS_DIR / thumb_name
    try:
        thumb_path.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        render_thumbnail(
            raw, thumb_path,
            search_pages=5,           # scan more pages for images
            min_image_pixels=150*150, # permissive to catch more images
            zoom=1.5,
            top_ratio=0.5,
            max_width=400,            # small
            jpeg_quality=28,          # used only if saving JPEG; PNG is quantized in utils
        )
        thumb_rel = f"thumbs/{thumb_name}"
        logger.info("Thumbnail written: %s", thumb_path)
    except Exception:
        logger.exception("Thumbnail render failed")
        thumb_rel = None

    # -------- Persist --------
    with Session() as s:
        paper = s.get(PaperORM, paper_id) or PaperORM(id=paper_id)
        paper.file_hash = file_hash
        paper.title = final_title
        paper.authors_json = json.dumps(final_authors or [], ensure_ascii=False)
        paper.year = str(final_year) if final_year else None
        paper.abstract = abstract_text
        paper.data_src = data_src
        paper.path = relative_path
        paper.thumb_path = thumb_rel

        # handle DOI/arXiv/etc from meta
        if meta:
            paper.doi = meta.get("doi") or paper.doi
            paper.arxiv_id = meta.get("arxiv_id") or paper.arxiv_id
            paper.venue = meta.get("venue") or paper.venue

            # ---- FIX: coerce published_at to a Python date ----
            publ = meta.get("published_at")
            publ_date = _coerce_date_like(publ)
            paper.published_at = publ_date  # Date column expects date or None

            paper.url = meta.get("url") or paper.url

        s.add(paper)
        s.commit()

    logger.info("Indexed paper id=%s title=%r path=%s", paper_id, final_title, relative_path)
    return paper_id