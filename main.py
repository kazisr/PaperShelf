import hashlib
import json
import os
import re
import uuid
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

import fitz  # PyMuPDF
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine

# -----------------------------
# Paths / Folders
# -----------------------------
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
THUMBS_DIR = DATA_DIR / "thumbs"
for d in (DATA_DIR, UPLOADS_DIR, THUMBS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# -----------------------------
# FastAPI + Templates
# -----------------------------
app = FastAPI()
app.mount("/media", StaticFiles(directory=DATA_DIR), name="media")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# -----------------------------
# DB (SQLite)
# -----------------------------
Base = declarative_base()
engine = create_engine(f"sqlite:///{DATA_DIR / 'papers.db'}", future=True)
Session = sessionmaker(bind=engine)

class PaperORM(Base):
    __tablename__ = "papers"
    id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    file_hash = Column(String, index=True)
    title = Column(String)
    authors_json = Column(Text)               # JSON list[str]
    year = Column(String)
    abstract = Column(Text)
    abstract_source = Column(String)
    path = Column(String)                     # relative path under /media
    thumb_path = Column(String)               # relative path under /media

Base.metadata.create_all(engine)

# -----------------------------
# Utilities
# -----------------------------
def file_safe(s: str, max_len: int = 120) -> str:
    s = re.sub(r"[^\w\s\-\.,+()&]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "_")
    return s[:max_len] if max_len else s
import fitz  # PyMuPDF
import re
from typing import Tuple, List, Optional

HEADER_STOP_PREFIXES = re.compile(
    r"^(arxiv|preprint|manuscript|submitted|accepted|doi:|issn|icml|neurips|cvpr|eccv|"
    r"ieee|acm|springer|elsevier|proceedings|journal|transactions|vol\.|no\.)\b",
    re.I
)

def _title_score(line: str, idx: int) -> float:
    # Clean for signals
    raw = line.strip()
    if not raw:
        return -1e9
    # Length: prefer 30–150 chars
    L = len(raw)
    len_score = -abs(L - 80) / 80.0  # peak around 80 chars
    # Penalize lines ending with period (often sentences, not titles)
    period_penalty = -0.7 if raw.endswith(".") else 0.0
    # Uppercase penalty but not a hard skip
    upper_ratio = sum(ch.isupper() for ch in raw if ch.isalpha()) / max(
        1, sum(ch.isalpha() for ch in raw)
    )
    upper_penalty = -0.8 if upper_ratio > 0.85 else 0.0
    # Prefer capitalized words (Title Case-ish)
    words = [w for w in re.split(r"\s+", raw) if w]
    cap_words = sum(1 for w in words if re.match(r"^[A-Z][A-Za-z\-]*$", w))
    cap_ratio = cap_words / max(1, len(words))
    cap_bonus = 0.6 * cap_ratio
    # Weakly penalize “obvious header” phrases, but don’t zero it out
    header_penalty = -1.0 if HEADER_STOP_PREFIXES.search(raw[:40]) else 0.0
    # Early position bonus (so line 1 isn’t skipped by default!)
    pos_bonus = 0.4 * (1.0 / (1 + idx))
    return len_score + period_penalty + upper_penalty + cap_bonus + header_penalty + pos_bonus

def _maybe_join(next_line: str) -> bool:
    # Join if the current line likely continues: no terminal punctuation, next line not a header
    if not next_line:
        return False
    if HEADER_STOP_PREFIXES.search(next_line[:40]):
        return False
    return True

def extract_title_authors_year_from_bytes(data: bytes) -> Tuple[Optional[str], List[str], Optional[str]]:
    """
    Extract title/authors/year from the first page *text*, prioritizing the largest
    font lines near the top of the page. Falls back gracefully. Ignores PDF
    metadata title to avoid bad/empty metadata.
    """
    title, authors, year = None, [], None

    def _clean(s: str) -> str:
        s = re.sub(r"\s+", " ", s).strip()
        # keep common punctuation useful in titles
        s = re.sub(r"[^\w\s\-:()\[\],]+", "", s)
        return s

    try:
        doc = fitz.open(stream=data, filetype="pdf")
        if doc.page_count == 0:
            return None, [], None
        page = doc.load_page(0)

        # Use dict mode to get font sizes/positions
        pd = page.get_text("dict")
        # Build ordered candidate lines: (max_font, y0, text)
        candidates = []
        for b in pd.get("blocks", []):
            for l in b.get("lines", []):
                spans = l.get("spans", [])
                if not spans:
                    continue
                txt = _clean("".join(s.get("text", "") for s in spans))
                if not txt:
                    continue
                max_font = max(s.get("size", 0) for s in spans)
                y0 = min(s.get("origin", [0, 0])[1] for s in spans)
                candidates.append((max_font, y0, txt))

        # Sort by visual order (y0), but we'll score by font size primarily
        candidates.sort(key=lambda t: (t[1], -t[0]))

        # Filter out obvious non-title lines and compute a score
        scored = []
        for i, (fsize, y0, txt) in enumerate(candidates):
            if len(txt) < 8 or len(txt) > 180:
                continue
            # Skip obvious headers/footers/sections
            if HEADER_STOP_PREFIXES.search(txt[:40]):
                continue
            if re.search(r"^(abstract|summary|keywords?)\b", txt, re.I):
                continue
            if "@" in txt:  # email lines
                continue
            # Too many digits usually means IDs/DOIs etc
            if sum(ch.isdigit() for ch in txt) > 6:
                continue
            # Penalize SHOUTING lines (but don't drop them outright)
            letters = [c for c in txt if c.isalpha()]
            if letters:
                upper_ratio = sum(c.isupper() for c in letters) / len(letters)
            else:
                upper_ratio = 0.0

            # Score: big font + close to top + reasonable length + not all-caps
            len_score = -abs(len(txt) - 75) / 75.0
            pos_bonus = - (y0 / (page.rect.height or 1))  # nearer top is better (more negative)
            cap_penalty = -0.8 if upper_ratio > 0.9 else 0.0
            score = (fsize * 2.0) + len_score + pos_bonus + cap_penalty
            scored.append((score, i, fsize, y0, txt))

        chosen_idx = None
        if scored:
            scored.sort(reverse=True)  # best score first
            _, idx, _, _, seed = scored[0]
            chosen_idx = idx
            title = seed

            # Try to join the next line if it looks like a continuation (same area, no sentence end)
            if idx + 1 < len(candidates):
                _, y1, nxt = candidates[idx + 1]
                if abs(y1 - candidates[idx][1]) < 25 and not title.endswith((".", ":", "?", "!", ";")):
                    # Avoid joining if next is clearly a section or authors/affiliation
                    if not re.search(r"^(abstract|summary|keywords?)\b", nxt, re.I) and "@" not in nxt and not re.search(r"University|Department|Institute|Lab|College", nxt, re.I):
                        j = _clean(nxt)
                        if 8 <= len(title + " " + j) <= 200:
                            title = f"{title} {j}".strip()

        # --- Authors: scan lines after chosen title for likely names
        if chosen_idx is not None:
            # Build a flat ordered list of texts by visual order
            ordered_lines = [(y, t) for _, y, t in candidates]
            # Find chosen line's position (by text match with tolerance)
            t0 = candidates[chosen_idx][2]
            start = 0
            for k, (_, t) in enumerate(ordered_lines):
                if t0 in t or t in t0:
                    start = k
                    break
            possible = []
            for _, ln in ordered_lines[start + 1 : start + 10]:
                if re.match(r"^(abstract|summary|keywords?)\b", ln, re.I):
                    break
                if re.search(r"@|University|Department|Institute|Lab|College", ln, re.I):
                    break
                # Heuristic name detection
                if re.search(r"[A-Z][a-z]+\s+[A-Z][a-z]+", ln):
                    possible.append(ln)
            if possible:
                joined = " ".join(possible)
                parts = re.split(r"\s*,\s*|\s+and\s+|;", joined)
                authors = [a.strip() for a in parts if a.strip()]
                # prune obvious junk
                authors = [a for a in authors if re.search(r"[A-Z][a-z]+", a) and len(a) <= 60]
                # de-dup while preserving order
                seen = set()
                uniq = []
                for a in authors:
                    if a.lower() not in seen:
                        seen.add(a.lower())
                        uniq.append(a)
                authors = uniq[:10]

        # --- Year (first page preferred) ---
        try:
            first_text = page.get_text("text")
        except Exception:
            first_text = ""
        m = re.search(r"\b(19|20)\d{2}\b", first_text)
        if not m and doc.page_count > 1:
            try:
                second_text = doc.load_page(1).get_text("text")
                m = re.search(r"\b(19|20)\d{2}\b", second_text)
            except Exception:
                m = None
        if m:
            year = m.group(0)

    except Exception:
        pass

    # Final tidy
    if title:
        title = _clean(title)
        # avoid pathological ALL CAPS
        letters = [c for c in title if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.97:
            title = title.title()

    return title, authors, year

def render_first_page_thumbnail(pdf_path: Path) -> Optional[str]:
    """Generate a high‑quality thumbnail by preferring large embedded images; fallback to a high‑DPI render of page 1."""
    try:
        doc = fitz.open(pdf_path)
        best_pix = None
        best_score = 0

        # 1) Prefer large embedded images from the first few pages
        max_pages = min(5, doc.page_count)
        for page_index in range(max_pages):
            page = doc.load_page(page_index)
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    # Normalize to RGB if needed (e.g., CMYK)
                    if pix.n >= 5:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    w, h = pix.width, pix.height
                    area = w * h
                    # Robust thresholds: avoid tiny strips / artifacts
                    if w >= 300 and h >= 200 and area >= 250_000:
                        ar = w / h if h else 0.0
                        if 0.33 <= ar <= 3.0:
                            score = area
                            if score > best_score:
                                best_pix = pix
                                best_score = score
                except Exception:
                    # Skip problematic images gracefully
                    continue

        if best_pix:
            out_name = f"{pdf_path.stem[:60]}_{uuid.uuid4().hex[:8]}.png"
            out_path = THUMBS_DIR / out_name
            best_pix.save(out_path.as_posix())
            return f"thumbs/{out_name}"

        # 2) Fallback: render the TOP HALF of page 1 at higher resolution
        page = doc.load_page(0)
        try:
            rot = getattr(page, "rotation", 0) or 0
        except Exception:
            rot = 0
        zoom = 2.5  # ~240 DPI
        mat = fitz.Matrix(zoom, zoom).prerotate(rot)

        # Clip to the top half of the page
        full = page.rect
        top_half = fitz.Rect(full.x0, full.y0, full.x1, full.y0 + full.height / 2)

        pix = page.get_pixmap(matrix=mat, alpha=False, clip=top_half)
        out_name = f"{pdf_path.stem[:60]}_{uuid.uuid4().hex[:8]}.png"
        out_path = THUMBS_DIR / out_name
        pix.save(out_path.as_posix())
        return f"thumbs/{out_name}"

    except Exception:
        # Final safety fallback: try a minimal render without matrix
        try:
            doc = fitz.open(pdf_path)
            page = doc.load_page(0)
            pix = page.get_pixmap()
            out_name = f"{pdf_path.stem[:60]}_{uuid.uuid4().hex[:8]}.png"
            out_path = THUMBS_DIR / out_name
            pix.save(out_path.as_posix())
            return f"thumbs/{out_name}"
        except Exception:
            return None

def system_abstract(pdf_path: Path) -> Optional[str]:
    """Very simple abstract detection: look for 'Abstract' section near the beginning."""
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for pi in range(min(3, doc.page_count)):
            text += doc.load_page(pi).get_text("text") + "\n"
        # Look for Abstract header
        m = re.search(r"\bAbstract\b[:\s]*([\s\S]{0,3000})", text, flags=re.IGNORECASE)
        if m:
            # stop at common next headers
            body = m.group(1)
            body = re.split(r"\n\s*(Keywords?|Index Terms?|1\.\s*Introduction\b|I\.\s*INTRODUCTION\b)", body, maxsplit=1)[0]
            body = re.sub(r"\s+\n", "\n", body).strip()
            return body[:2000]
    except Exception:
        pass
    return None

async def index_pdf(pdf_path: Path, relative_path: str,
                    year: Optional[str] = None,
                    authors: Optional[List[str]] = None,
                    title: Optional[str] = None) -> str:
    """Insert/update DB for a single PDF path and return paper id."""
    sess = Session()
    try:
        data = pdf_path.read_bytes()
        file_hash = hashlib.md5(data).hexdigest()

        # reuse/extract metadata
        t2, a2, y2 = extract_title_authors_year_from_bytes(data)
        title_final = title or t2 or pdf_path.stem
        authors_final = authors or (a2 or [])
        year_final = year or (y2 or "")

        thumb = await asyncio.to_thread(render_first_page_thumbnail, pdf_path)
        abstract = await asyncio.to_thread(system_abstract, pdf_path)

        # upsert by file_hash
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
    except Exception as e:
        sess.rollback()
        raise
    finally:
        sess.close()

# -----------------------------
# Routes
# -----------------------------
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
        # Decode authors for template usage (so templates can iterate p.authors)
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

    # Name using metadata
    title, authors, year = extract_title_authors_year_from_bytes(data)
    # Ensure authors are always a clean list (avoid malformed strings)
    authors = [a.strip() for a in authors if a.strip()]
    authors_display = ", ".join(authors) if authors else ""
    parts = [file_safe(title_display := title or "untitled")]
    if authors:
        parts.append("")
        parts.append(file_safe(authors_display, max_len=120))
    name_core = "_".join(parts) if len(parts) > 1 else parts[0]
    # Hard cap to keep full filename well under macOS path limits (255 bytes)
    name_core = name_core[:140]
    year_part = f"_{year}" if year else ""
    hash8 = hashlib.md5(data).hexdigest()[:8]
    newname = f"{name_core}{year_part}_{hash8}.pdf"
    newname = newname.replace("__", "___") if authors_display else newname

    out = UPLOADS_DIR / newname
    out.write_bytes(data)
    relative_path = f"uploads/{newname}"

    pid = await index_pdf(out, relative_path, year=year, authors=authors, title=title)
    # return the indexed record as JSON
    sess = Session()
    try:
        p = sess.query(PaperORM).filter_by(id=pid).one()
        print(p.authors_json)
        authors_list = json.loads(p.authors_json or "[]")
        print(authors_list)
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
    for p in UPLOADS_DIR.glob("*.pdf"):
        p.unlink(missing_ok=True)
    for t in THUMBS_DIR.glob("*.png"):
        t.unlink(missing_ok=True)
    return RedirectResponse(url="/", status_code=303)