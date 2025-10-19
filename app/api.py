from __future__ import annotations

import json
import os
import pathlib
from typing import Optional

import fitz
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy import select, or_

from app.config import DATA_DIR, UPLOADS_DIR, THUMBS_DIR, TEMPLATES_DIR
from app.db import Session, PaperORM, init_db
from app.utils.pdf_tools import file_safe
from app.services.indexer import index_pdf
from app.services.metadata import autofetch_metadata

app = FastAPI(title="PaperShelf")


# Serve static assets (e.g., favicon, logos)
STATIC_DIR = pathlib.Path(__file__).resolve().parents[1] / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")

# Serve the data dir (pdfs/thumbs) without changing any template paths
DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=DATA_DIR, html=False), name="media")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Init DB (no UI change)
init_db()


# -------------------------
# Helpers (no UI change)
# -------------------------
def _row_to_view(p: PaperORM) -> dict:
    """Return a dict that is friendly to both old and new frontends."""
    authors_list = json.loads(p.authors_json or "[]")
    authors_str = ", ".join(authors_list) if isinstance(authors_list, list) else str(authors_list or "")
    return {
        # core
        "id": p.id,
        "title": p.title,
        "authors": authors_list,        # list form
        "authors_str": authors_str,     # string form (compat)
        "year": p.year,
        "abstract": p.abstract,
        "path": p.path,
        "thumb_path": p.thumb_path,
        "thumbnail": p.thumb_path,      # alias (compat)
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "venue": p.venue,
        "url": p.url,
        "data_src": p.data_src,

        # extra aliases some UIs use
        "file": p.path,
        "thumb": p.thumb_path,
    }


def _query_items(q: Optional[str]) -> list[dict]:
    q = (q or "").strip()
    with Session() as s:
        stmt = select(PaperORM).order_by(PaperORM.created_at.desc())
        if q:
            like = f"%{q}%"
            stmt = (
                select(PaperORM)
                .where(
                    or_(
                        PaperORM.title.ilike(like),
                        PaperORM.abstract.ilike(like),
                        PaperORM.authors_json.ilike(like),
                        PaperORM.venue.ilike(like),
                        PaperORM.doi.ilike(like),
                        PaperORM.arxiv_id.ilike(like),
                    )
                )
                .order_by(PaperORM.created_at.desc())
            )
        rows = s.execute(stmt).scalars().all()
    return [_row_to_view(r) for r in rows]


# -------------------------
# PAGES (keeps your template as-is)
# -------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: Optional[str] = None):
    """
    Minimal change: we keep rendering your current index.html.
    We also pass variables many UIs expect, but if your template doesn't use them,
    nothing changes visually.
    """
    items = _query_items(q)
    # We pass multiple names for compatibility; your template can ignore them.
    context = {
        "request": request,
        "items": items,           # common name
        "papers": items,          # alias some templates used
        "results": items,         # another alias just in case
        "q": q or "",
        "count": len(items),
    }
    return templates.TemplateResponse("index.html", context)


# -------------------------
# API: SEARCH (JSON) — unchanged, now with aliases for old UIs
# -------------------------
@app.get("/api/search")
def api_search(q: Optional[str] = None):
    items = _query_items(q)
    # Provide multiple keys so older frontend code can bind to whichever it used.
    return {
        "items": items,
        "papers": items,   # alias (compat)
        "results": items,  # alias (compat)
        "count": len(items),
        "q": q or "",
    }


# -------------------------
# API: simple list (JSON) — optional helper many UIs call
# -------------------------
@app.get("/api/papers")
def api_papers():
    items = _query_items(None)
    return {"items": items, "papers": items, "results": items, "count": len(items)}


# -------------------------
# API: UPLOAD (unchanged behavior)
# -------------------------
@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    year: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = file_safe(file.filename)
    dest = UPLOADS_DIR / safe_name

    raw = await file.read()
    dest.write_bytes(raw)

    relative_path = f"uploads/{safe_name}"
    paper_id = await index_pdf(dest, relative_path, year_hint=year, title_hint=title)
    # Preserve existing response shape
    return {"id": paper_id, "path": relative_path}


# -------------------------
# API: DEV CLEAN (unchanged behavior)
# -------------------------
@app.post("/dev/clean")
def dev_clean():
    # wipe DB + uploads + thumbs
    sess = Session()
    try:
        sess.query(PaperORM).delete()
        sess.commit()
    finally:
        sess.close()

    for p in (UPLOADS_DIR.glob("*.pdf")):
        p.unlink(missing_ok=True)
    for t in (THUMBS_DIR.glob("*.png")):
        t.unlink(missing_ok=True)
    return RedirectResponse(url="/", status_code=303)

# -------------------------
# API: MANUAL METADATA REFRESH (unchanged behavior)
# -------------------------
@app.post("/api/papers/{paper_id}/refresh_metadata")
async def refresh_metadata(paper_id: str):
    with Session() as s:
        paper = s.get(PaperORM, paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        pdf_path = pathlib.Path(DATA_DIR) / (paper.path or "")
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file missing on disk")

        with fitz.open(pdf_path) as doc:
            pages = min(3, len(doc))
            text = "\n\n".join(doc[i].get_text("text") for i in range(pages))

        meta = await autofetch_metadata(text, paper.title)
        if not meta:
            return {"updated": False}

        changed = False
        if meta.get("title") and meta["title"] != (paper.title or ""):
            paper.title = meta["title"]; changed = True
        if meta.get("authors"):
            authors_json = json.dumps(meta["authors"], ensure_ascii=False)
            if authors_json != (paper.authors_json or "[]"):
                paper.authors_json = authors_json; changed = True
        if meta.get("year") and meta["year"] != (paper.year or ""):
            paper.year = meta["year"]; changed = True
        if meta.get("abstract") and not paper.abstract:
            paper.abstract = meta["abstract"]; changed = True
        if meta.get("doi") and meta["doi"] != (paper.doi or ""):
            paper.doi = meta["doi"]; changed = True
        if meta.get("arxiv_id") and meta["arxiv_id"] != (paper.arxiv_id or ""):
            paper.arxiv_id = meta["arxiv_id"]; changed = True
        if meta.get("venue") and meta["venue"] != (paper.venue or ""):
            paper.venue = meta["venue"]; changed = True
        if meta.get("published_at") and meta["published_at"] != getattr(paper, "published_at", None):
            paper.published_at = meta["published_at"]; changed = True
        if meta.get("url") and meta["url"] != (paper.url or ""):
            paper.url = meta["url"]; changed = True

        if changed:
            s.commit()
        return {"updated": changed}


# ---------- Optional debug helpers (no UI change) ----------
@app.get("/api/debug/paths")
def debug_paths():
    from app.config import ROOT_DIR, DATA_DIR, UPLOADS_DIR, THUMBS_DIR, TEMPLATES_DIR
    return {
        "cwd": str(os.getcwd()),
        "ROOT_DIR": str(ROOT_DIR),
        "DATA_DIR": str(DATA_DIR),
        "UPLOADS_DIR_exists": UPLOADS_DIR.exists(),
        "THUMBS_DIR_exists": THUMBS_DIR.exists(),
        "TEMPLATES_DIR": str(TEMPLATES_DIR),
    }

@app.get("/api/debug/status")
def debug_status():
    from app.config import UPLOADS_DIR, THUMBS_DIR
    with Session() as s:
        count = s.query(PaperORM).count()
    uploads = sorted([p.name for p in UPLOADS_DIR.glob("*.pdf")])
    thumbs = sorted([p.name for p in THUMBS_DIR.glob("*.png")])
    return {"db_count": count, "uploads": uploads, "thumbs": thumbs}