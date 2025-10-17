import asyncio
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from ..db import Session, PaperORM
from ..utils.pdf_tools import (
    render_first_page_thumbnail,
    system_abstract,
    extract_title_authors_year_from_bytes,
)

async def index_pdf(
    pdf_path: Path,
    relative_path: str,
    year: Optional[str] = None,
    authors: Optional[List[str]] = None,
    title: Optional[str] = None,
) -> str:
    """Insert/update DB for a single PDF path and return paper id."""
    sess = Session()
    try:
        data = pdf_path.read_bytes()
        file_hash = hashlib.md5(data).hexdigest()

        t2, a2, y2 = extract_title_authors_year_from_bytes(data)
        title_final = title or t2 or pdf_path.stem
        authors_final = authors or (a2 or [])
        year_final = year or (y2 or "")

        thumb = await asyncio.to_thread(render_first_page_thumbnail, pdf_path)
        abstract = await asyncio.to_thread(system_abstract, pdf_path)

        p = sess.query(PaperORM).filter_by(file_hash=file_hash).one_or_none()
        if not p:
            p = PaperORM(id=uuid.uuid4().hex)
            sess.add(p)

        p.file_hash = file_hash
        p.created_at = p.created_at or datetime.utcnow()
        p.title = title_final
        p.authors_json = json.dumps(authors_final or [])
        p.year = str(year_final) if year_final else ""
        p.abstract = abstract or ""
        p.abstract_source = "system" if abstract else "none"
        p.path = relative_path
        p.thumb_path = thumb or ""

        sess.commit()
        return p.id
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()