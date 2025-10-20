from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Optional

import fitz
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, or_, and_

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

# Init DB
init_db()

# -------------------------
# Helpers
# -------------------------
def _row_to_view(p: PaperORM) -> dict:
    authors_list = json.loads(p.authors_json or "[]")
    authors_str = ", ".join(authors_list) if isinstance(authors_list, list) else str(authors_list or "")
    return {
        "id": p.id,
        "title": p.title,
        "authors": authors_list,
        "authors_str": authors_str,
        "year": p.year,
        "abstract": p.abstract,
        "path": p.path,
        "thumb_path": p.thumb_path,
        "thumbnail": p.thumb_path,
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "venue": p.venue,
        "url": p.url,
        "data_src": p.data_src,
        "file": p.path,
        "thumb": p.thumb_path,
    }

TOKEN_RE = re.compile(r'(?P<key>author|year|venue):(?P<val>"[^"]+"|\S+)', re.I)

def parse_search(q: Optional[str]):
    """
    Supports tokens inside q like:
      author:"Geoffrey Hinton"  year:2021  venue:ICLR  year:2020-2022
    Returns (clean_q, filters_dict)
    """
    if not q:
        return "", {}
    filters = {"author": [], "year": [], "venue": []}

    def unquote(s: str) -> str:
        return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s

    for m in TOKEN_RE.finditer(q):
        key = m.group("key").lower()
        val = unquote(m.group("val")).strip()
        if val:
            filters[key].append(val)

    rest = TOKEN_RE.sub("", q).strip()
    for k in list(filters.keys()):
        if not filters[k]:
            filters[k] = None
    return rest, filters

def _query_items(
    q: Optional[str],
    author: Optional[str | list[str]] = None,
    year: Optional[str | list[str]] = None,
    venue: Optional[str | list[str]] = None,
) -> list[dict]:
    """
    Unified search with optional filters.
    - author: matches substring inside authors_json
    - year: exact 4-digit year OR range YYYY-YYYY
    - venue: substring in venue
    """
    q = (q or "").strip()

    # normalize lists (also accept comma-separated string)
    def norm(x):
        if x is None:
            return None
        if isinstance(x, (list, tuple)):
            return [str(v).strip() for v in x if str(v).strip()]
        return [p for p in (s.strip() for s in str(x).split(",")) if p]

    author = norm(author)
    year   = norm(year)
    venue  = norm(venue)

    with Session() as s:
        clauses = []

        if q:
            like = f"%{q}%"
            clauses.append(or_(
                PaperORM.title.ilike(like),
                PaperORM.abstract.ilike(like),
                PaperORM.authors_json.ilike(like),
                PaperORM.venue.ilike(like),
                PaperORM.doi.ilike(like),
                PaperORM.arxiv_id.ilike(like),
                PaperORM.year.ilike(like),
            ))

        if author:
            clauses.append(or_(*[PaperORM.authors_json.ilike(f"%{a}%") for a in author]))

        if year:
            y_ors = []
            for y in year:
                if re.match(r"^\d{4}-\d{4}$", y):
                    y1, y2 = y.split("-")
                    y_ors.append(and_(PaperORM.year >= y1, PaperORM.year <= y2))
                else:
                    y_ors.append(PaperORM.year == y)
            clauses.append(or_(*y_ors))

        if venue:
            clauses.append(or_(*[PaperORM.venue.ilike(f"%{v}%") for v in venue]))

        stmt = select(PaperORM)
        if clauses:
            stmt = stmt.where(and_(*clauses))
        stmt = stmt.order_by(PaperORM.created_at.desc())

        rows = s.execute(stmt).scalars().all()

    return [_row_to_view(r) for r in rows]

# -------------------------
# PAGES
# -------------------------
@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    q: Optional[str] = None,
    author: Optional[str] = None,
    year: Optional[str] = None,
    venue: Optional[str] = None,
):
    # Parse tokens from q, let explicit params win
    clean_q, tokens = parse_search(q)
    a = author or tokens.get("author")
    y = year   or tokens.get("year")
    v = venue  or tokens.get("venue")

    items = _query_items(clean_q, author=a, year=y, venue=v)
    context = {
        "request": request,
        "items": items,
        "papers": items,
        "results": items,
        "q": q or "",
        "author": author or "",
        "year": year or "",
        "venue": venue or "",
        "count": len(items),
    }
    return templates.TemplateResponse("index.html", context)

# -------------------------
# API: SEARCH (JSON)
# -------------------------
@app.get("/api/search")
def api_search(
    q: Optional[str] = None,
    author: Optional[str] = None,
    year: Optional[str] = None,
    venue: Optional[str] = None,
):
    clean_q, tokens = parse_search(q)
    a = author or tokens.get("author")
    y = year   or tokens.get("year")
    v = venue  or tokens.get("venue")

    items = _query_items(clean_q, author=a, year=y, venue=v)
    return {
        "items": items,
        "papers": items,
        "results": items,
        "count": len(items),
        "q": q or "",
        "filters": {"author": a, "year": y, "venue": v},
    }

# -------------------------
# API: list (JSON)
# -------------------------
@app.get("/api/papers")
def api_papers():
    items = _query_items(None)
    return {"items": items, "papers": items, "results": items, "count": len(items)}

# -------------------------
# API: upload
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
    return {"id": paper_id, "path": relative_path}

# -------------------------
# API: dev clean
# -------------------------
@app.post("/dev/clean")
def dev_clean():
    sess = Session()
    try:
        sess.query(PaperORM).delete()
        sess.commit()
    finally:
        sess.close()

    for p in UPLOADS_DIR.glob("*.pdf"):
        p.unlink(missing_ok=True)
    for t in THUMBS_DIR.glob("*.png"):
        t.unlink(missing_ok=True)
    return RedirectResponse(url="/", status_code=303)

# -------------------------
# API: refresh metadata
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

# -------------------------
# Debug endpoints
# -------------------------
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