import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import BASE_DIR, DATA_DIR, UPLOADS_DIR, THUMBS_DIR, TEMPLATES_DIR
from .db import Session, PaperORM, init_db
from .services.indexer import index_pdf
from .utils.pdf_tools import file_safe, extract_title_authors_year_from_bytes

# Initialize DB
init_db()

app = FastAPI()
app.mount("/media", StaticFiles(directory=DATA_DIR), name="media")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = ""):
    sess = Session()
    try:
        if q:
            like = f"%{q.lower()}%"
            rows = (
                sess.query(PaperORM)
                .filter((PaperORM.title.ilike(like)) | (PaperORM.abstract.ilike(like)))
                .order_by(PaperORM.created_at.desc())
                .all()
            )
        else:
            rows = sess.query(PaperORM).order_by(PaperORM.created_at.desc()).all()
        for r in rows:
            try:
                r.authors = json.loads(r.authors_json or "[]")
            except Exception:
                r.authors = []
        return templates.TemplateResponse("index.html", {"request": request, "papers": rows, "q": q})
    finally:
        sess.close()

@app.get("/api/search")
def api_search(q: str = "", limit: int = 50, offset: int = 0):
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    sess = Session()
    try:
        base = sess.query(PaperORM)
        if q:
            like = f"%{q.lower()}%"
            base = base.filter((PaperORM.title.ilike(like)) | (PaperORM.abstract.ilike(like)))
        total = base.count()
        rows = base.order_by(PaperORM.created_at.desc()).offset(offset).limit(limit).all()
        results = []
        for r in rows:
            try:
                authors = json.loads(r.authors_json or "[]")
            except Exception:
                authors = []
            results.append({
                "id": r.id,
                "title": r.title,
                "authors": authors,
                "year": r.year or "",
                "abstract": r.abstract or "",
                "abstract_source": r.abstract_source or "none",
                "thumb_url": f"/media/{r.thumb_path}" if r.thumb_path else None,
                "file_url": f"/media/{r.path}" if r.path else None,
                "created_at": r.created_at.isoformat() if r.created_at else None
            })
        return {"total": total, "count": len(results), "limit": limit, "offset": offset, "results": results}
    finally:
        sess.close()

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        return JSONResponse({"error": "Only PDF supported."}, status_code=400)

    data = await file.read()

    # Filename from extracted metadata (title/authors/year)
    title, authors, year = extract_title_authors_year_from_bytes(data)
    authors = [a.strip() for a in (authors or []) if a.strip()]
    authors_display = ", ".join(authors) if authors else ""
    title_display = title or "untitled"

    parts = [file_safe(title_display)]
    if authors:
        parts.append("")
        parts.append(file_safe(authors_display, max_len=120))
    name_core = "_".join(parts) if len(parts) > 1 else parts[0]
    name_core = name_core[:140]
    year_part = f"_{year}" if year else ""
    hash8 = hashlib.md5(data).hexdigest()[:8]
    newname = f"{name_core}{year_part}_{hash8}.pdf"
    if authors_display:
        newname = newname.replace("__", "___")

    out = UPLOADS_DIR / newname
    out.write_bytes(data)
    relative_path = f"uploads/{newname}"

    pid = await index_pdf(out, relative_path, year=year, authors=authors, title=title)

    sess = Session()
    try:
        p = sess.query(PaperORM).filter_by(id=pid).one()
        authors_list = json.loads(p.authors_json or "[]")
        return {
            "id": p.id,
            "title": p.title,
            "authors": authors_list,
            "year": p.year,
            "abstract": p.abstract,
            "abstract_source": p.abstract_source,
            "thumb_url": f"/media/{p.thumb_path}" if p.thumb_path else None,
            "file_url": f"/media/{p.path}" if p.path else None,
            "created_at": p.created_at.isoformat() if p.created_at else None
        }
    finally:
        sess.close()

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