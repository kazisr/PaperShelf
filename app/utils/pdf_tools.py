import re
from pathlib import Path
from typing import Optional, Tuple, List
from app.config import THUMBS_DIR
import fitz, uuid

# ---------- Simple utility (kept here to avoid extra file) ----------
def file_safe(s: str, max_len: int = 120) -> str:
    s = re.sub(r"[^\w\s\-\.,+()&]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "_")
    return s[:max_len] if max_len else s

HEADER_STOP_PREFIXES = re.compile(
    r"^(arxiv|preprint|manuscript|submitted|accepted|doi:|issn|icml|neurips|cvpr|eccv|"
    r"ieee|acm|springer|elsevier|proceedings|journal|transactions|vol\.|no\.)\b",
    re.I
)

# ---------- Extractors ----------
def extract_title_authors_year_from_bytes(data: bytes) -> Tuple[Optional[str], List[str], Optional[str]]:
    """
    Extract title/authors/year from the first page *text*, prioritizing the largest
    font lines near the top of the page. Ignores metadata; falls back gracefully.
    """
    title, authors, year = None, [], None

    def _clean(s: str) -> str:
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"[^\w\s\-:()\[\],]+", "", s)
        return s

    try:
        doc = fitz.open(stream=data, filetype="pdf")
        if doc.page_count == 0:
            return None, [], None
        page = doc.load_page(0)

        pd = page.get_text("dict")
        candidates = []  # (max_font, y0, text)
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

        candidates.sort(key=lambda t: (t[1], -t[0]))

        scored = []
        for i, (fsize, y0, txt) in enumerate(candidates):
            if len(txt) < 8 or len(txt) > 180:
                continue
            if HEADER_STOP_PREFIXES.search(txt[:40]):
                continue
            if re.search(r"^(abstract|summary|keywords?)\b", txt, re.I):
                continue
            if "@" in txt:
                continue
            if sum(ch.isdigit() for ch in txt) > 6:
                continue

            letters = [c for c in txt if c.isalpha()]
            upper_ratio = (sum(c.isupper() for c in letters) / len(letters)) if letters else 0.0

            len_score = -abs(len(txt) - 75) / 75.0
            pos_bonus = - (y0 / (page.rect.height or 1))
            cap_penalty = -0.8 if upper_ratio > 0.9 else 0.0
            score = (fsize * 2.0) + len_score + pos_bonus + cap_penalty
            scored.append((score, i, fsize, y0, txt))

        chosen_idx = None
        if scored:
            scored.sort(reverse=True)
            _, idx, _, _, seed = scored[0]
            chosen_idx = idx
            title = seed
            if idx + 1 < len(candidates):
                _, y1, nxt = candidates[idx + 1]
                if abs(y1 - candidates[idx][1]) < 25 and not title.endswith((".", ":", "?", "!", ";")):
                    if not re.search(r"^(abstract|summary|keywords?)\b", nxt, re.I) and "@" not in nxt and not re.search(
                        r"University|Department|Institute|Lab|College", nxt, re.I
                    ):
                        j = _clean(nxt)
                        if 8 <= len(title + " " + j) <= 200:
                            title = f"{title} {j}".strip()

        if chosen_idx is not None:
            ordered_lines = [(y, t) for _, y, t in candidates]
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
                if re.search(r"[A-Z][a-z]+\s+[A-Z][a-z]+", ln):
                    possible.append(ln)

            if possible:
                joined = " ".join(possible)
                parts = re.split(r"\s*,\s*|\s+and\s+|;", joined)
                authors = [a.strip() for a in parts if a.strip()]
                authors = [a for a in authors if re.search(r"[A-Z][a-z]+", a) and len(a) <= 60]
                seen = set()
                uniq = []
                for a in authors:
                    key = a.lower()
                    if key not in seen:
                        seen.add(key)
                        uniq.append(a)
                authors = uniq[:10]

        # Year
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

    if title:
        title = re.sub(r"\s+", " ", title).strip()
        letters = [c for c in title if c.isalpha()]
        if letters and (sum(c.isupper() for c in letters) / len(letters)) > 0.97:
            title = title.title()

    return title, authors, year

def render_first_page_thumbnail(pdf_path: Path) -> Optional[str]:
    """
    Prefer large embedded images (first few pages). If none, render the TOP HALF of page 1.
    Returns relative path like 'thumbs/<uuid>.png'
    """
    try:
        doc = fitz.open(pdf_path)
        best_pix = None
        best_score = 0

        # Prefer large embedded images from first few pages
        max_pages = min(5, doc.page_count)
        for page_index in range(max_pages):
            page = doc.load_page(page_index)
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n >= 5:  # CMYK → RGB
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    w, h = pix.width, pix.height
                    area = w * h
                    if w >= 300 and h >= 200 and area >= 250_000:
                        ar = w / h if h else 0.0
                        if 0.33 <= ar <= 3.0:
                            if area > best_score:
                                best_pix = pix
                                best_score = area
                except Exception:
                    continue

        # Fallback — top half of page 1 render
        if not best_pix:
            page = doc.load_page(0)
            zoom = 2.5  # ~240 DPI
            mat = fitz.Matrix(zoom, zoom)
            full = page.rect
            # Clip to top half
            clip = fitz.Rect(full.x0, full.y0, full.x1, full.y0 + full.height / 2)
            best_pix = page.get_pixmap(matrix=mat, alpha=False, clip=clip)

        # Save to thumbs/
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        out_name = f"{pdf_path.stem[:60]}_{uuid.uuid4().hex[:8]}.png"
        out_path = THUMBS_DIR / out_name
        best_pix.save(out_path.as_posix())

        return f"thumbs/{out_name}"

    except Exception as e:
        print(f"[Thumbnail Error] {e}")
        return None

def system_abstract(pdf_path: Path) -> Optional[str]:
    """Very simple abstract detection: look for 'Abstract' near the beginning."""
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for pi in range(min(3, doc.page_count)):
            text += doc.load_page(pi).get_text("text") + "\n"
        m = re.search(r"\bAbstract\b[:\s]*([\s\S]{0,3000})", text, flags=re.IGNORECASE)
        if m:
            body = m.group(1)
            body = re.split(
                r"\n\s*(Keywords?|Index Terms?|1\.\s*Introduction\b|I\.\s*INTRODUCTION\b)",
                body,
                maxsplit=1,
            )[0]
            body = re.sub(r"\s+\n", "\n", body).strip()
            return body[:2000]
    except Exception:
        pass
    return None