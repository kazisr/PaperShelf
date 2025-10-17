from __future__ import annotations
import re
from pathlib import Path
from typing import List, Tuple, Optional

import fitz  # PyMuPDF

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

# Heuristic stopwords for naive title detection
HEADER_STOP = re.compile(r"^\s*(introduction|background|related work|1\.\s|abstract|keywords)\b", re.I)

# Extra prefixes to ignore when scoring title candidates (from older heuristic)
HEADER_STOP_PREFIXES = re.compile(
    r"^(arxiv|preprint|manuscript|submitted|accepted|doi:|issn|icml|neurips|cvpr|eccv|"
    r"ieee|acm|springer|elsevier|proceedings|journal|transactions|vol\.|no\.)\b",
    re.I
)


def file_safe(name: str) -> str:
    """Light sanitizer for filenames."""
    s = re.sub(r"[^\w\-.]+", "_", name.strip())
    return s[:200] or "file"


def compose_data_source(*sources: Optional[str]) -> Optional[str]:
    """
    Merge one or more abstract sources into a single string separated by ' + '.
    - Preserves literal casing except normalizing 'system' → 'System'.
    - Skips empties/None, de-duplicates while preserving order.
    Examples:
        compose_abstract_source("System") -> "System"
        compose_abstract_source("System", "crossref-doi") -> "System + crossref-doi"
        compose_abstract_source(None, "arxiv-id", "arxiv-id") -> "arxiv-id"
    """
    seen = set()
    ordered: List[str] = []
    for s in sources:
        if not s:
            continue
        parts = [p.strip() for p in s.split("+") if p.strip()]
        for p in parts:
            normalized = "System" if p.lower() == "system" else p
            key = normalized.lower()
            if key not in seen:
                seen.add(key)
                ordered.append(normalized)
    return " + ".join(ordered) if ordered else None


def extract_title_authors_year_from_bytes(pdf_bytes: bytes) -> Tuple[Optional[str], Optional[List[str]], Optional[str]]:
    """
    Improved heuristic using layout info (font sizes/positions) from page 1, with
    light fallbacks to plain text on pages 1–2.
    """
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    year: Optional[str] = None

    def _clean(s: str) -> str:
        s = re.sub(r"\s+", " ", s).strip()
        # keep common punctuation that appears in titles/authors
        s = re.sub(r"[^\w\s\-:()\[\],&.+/]+", "", s)
        return s

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if len(doc) == 0:
                return None, None, None

            page = doc[0]

            # Collect candidate lines with their max font size and top y
            pd = page.get_text("dict")
            candidates: List[Tuple[float, float, str]] = []  # (max_font, y0, text)
            for b in pd.get("blocks", []):
                for l in b.get("lines", []):
                    spans = l.get("spans", [])
                    if not spans:
                        continue
                    txt = _clean("".join(s.get("text", "") for s in spans))
                    if not txt:
                        continue
                    max_font = max(s.get("size", 0.0) for s in spans)
                    y0 = min((s.get("origin", [0.0, 0.0])[1] or 0.0) for s in spans)
                    candidates.append((max_font, y0, txt))

            # Sort by vertical position (top first), break ties by larger font
            candidates.sort(key=lambda t: (t[1], -t[0]))

            scored: List[Tuple[float, int, float, float, str]] = []
            for i, (fsize, y0, txt) in enumerate(candidates):
                # Length filters
                if len(txt) < 8 or len(txt) > 200:
                    continue
                # Skip clear non-title prefixes
                if HEADER_STOP.search(txt) or HEADER_STOP_PREFIXES.search(txt[:40]):
                    continue
                # Skip abstract/keywords or emails
                if re.search(r"^(abstract|summary|keywords?)\b", txt, re.I):
                    continue
                if "@" in txt:
                    continue
                # Too many digits → likely metadata
                if sum(ch.isdigit() for ch in txt) > 6:
                    continue

                # Penalize ALL-CAPS
                letters = [c for c in txt if c.isalpha()]
                upper_ratio = (sum(c.isupper() for c in letters) / len(letters)) if letters else 0.0

                len_score = -abs(len(txt) - 75) / 75.0
                pos_bonus = -(y0 / (page.rect.height or 1.0))  # prefer higher on page
                cap_penalty = -0.8 if upper_ratio > 0.9 else 0.0
                score = (fsize * 2.0) + len_score + pos_bonus + cap_penalty
                scored.append((score, i, fsize, y0, txt))

            chosen_idx: Optional[int] = None
            if scored:
                scored.sort(reverse=True)
                _, idx, _, _, seed = scored[0]
                chosen_idx = idx
                title = seed

                # Try to join the next line if it looks like a title continuation
                if idx + 1 < len(candidates):
                    _, y1, nxt = candidates[idx + 1]
                    same_band = abs(y1 - candidates[idx][1]) < 25
                    bad_next = (
                        re.search(r"^(abstract|summary|keywords?)\b", nxt, re.I)
                        or "@" in nxt
                        or re.search(r"\b(University|Department|Institute|Laboratory|College|School)\b", nxt, re.I)
                    )
                    if same_band and not bad_next and not title.endswith((".", ":", "?", "!", ";")):
                        j = _clean(nxt)
                        if 8 <= len(f"{title} {j}") <= 220:
                            title = f"{title} {j}".strip()

            # Authors: scan a few lines after the title band
            if chosen_idx is not None:
                ordered_lines = [(y, t) for _, y, t in candidates]
                seed_text = candidates[chosen_idx][2]
                start = 0
                for k, (_, t) in enumerate(ordered_lines):
                    if seed_text in t or t in seed_text:
                        start = k
                        break

                possible: List[str] = []
                for _, ln in ordered_lines[start + 1 : start + 10]:
                    if re.match(r"^(abstract|summary|keywords?)\b", ln, re.I):
                        break
                    if re.search(r"@|University|Department|Institute|Laboratory|College|School", ln, re.I):
                        break
                    # Look for Person Name patterns
                    if re.search(r"[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)+", ln):
                        possible.append(ln)

                if possible:
                    joined = " ".join(possible)

                    # Drop any leading non-name fragment (e.g., leftover title words before first proper name)
                    mfirst = re.search(r"[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)+", joined)
                    if mfirst:
                        joined = joined[mfirst.start():]

                    # Split on commas / "and" / semicolons
                    parts = re.split(r"\s*,\s*|\s+and\s+|;", joined)

                    cleaned: List[str] = []
                    for a in parts:
                        a = a.strip()
                        if not a:
                            continue
                        # remove numeric/superscript-like suffixes (e.g., "Ahmed1", "Saif2")
                        a = re.sub(r"\b\d+\b", "", a)
                        a = re.sub(r"([A-Za-z])\d+", r"\1", a)
                        # normalize spaces and strip trailing punctuation
                        a = re.sub(r"\s{2,}", " ", a)
                        a = a.strip(",; ").strip()
                        # must look like a person name (Firstname [M.] Lastname [Lastname...])
                        if not re.search(r"[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)+", a):
                            continue
                        # avoid common leftover title words erroneously captured as names
                        if re.match(r"^(Accidents|Paper|Study|Analysis|Investigation|Performance|Evaluation|Design|Development)\b", a, re.I):
                            continue
                        # keep
                        cleaned.append(a)

                    # Deduplicate (case-insensitive, alphas only) and cap to 10
                    seen: set[str] = set()
                    uniq: List[str] = []
                    for a in cleaned:
                        key = re.sub(r"[^a-z]", "", a.lower())
                        if key not in seen:
                            seen.add(key)
                            uniq.append(a)

                    authors = uniq[:10] or None

            # Year: search first two pages' plain text
            try:
                first_text = page.get_text("text")
            except Exception:
                first_text = ""
            m = re.search(r"\b(19|20)\d{2}\b", first_text)
            if not m and len(doc) > 1:
                try:
                    second_text = doc[1].get_text("text")
                    m = re.search(r"\b(19|20)\d{2}\b", second_text)
                except Exception:
                    m = None
            if m:
                year = m.group(0)

    except Exception:
        # Swallow and return partials if any
        pass

    # Normalize all-caps titles to Title Case (lightly)
    if title:
        t_letters = [c for c in title if c.isalpha()]
        if t_letters and (sum(c.isupper() for c in t_letters) / len(t_letters)) > 0.97:
            title = title.title()

    return title, authors, year


# ---------- Thumbnail helpers ----------

def _pixmap_to_pil(pix: fitz.Pixmap) -> "Image.Image":
    """Convert PyMuPDF Pixmap to a Pillow Image in RGB."""
    if not _HAS_PIL:
        raise RuntimeError("Pillow not available")
    mode = "RGB"
    if pix.n == 1:
        mode = "L"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    if mode != "RGB":
        img = img.convert("RGB")
    return img


def _save_low_quality(img: "Image.Image", out_path: Path, *, max_width: int = 400, jpeg_quality: int = 28) -> None:
    """
    Save very small thumbnail. If output suffix is .jpg/.jpeg => use JPEG.
    Otherwise save a tiny PNG fallback (quantized).
    """
    # Downscale keeping aspect
    w, h = img.size
    if w > max_width:
        new_h = int(h * (max_width / float(w)))
        img = img.resize((max_width, max(1, new_h)), Image.LANCZOS)

    suffix = out_path.suffix.lower()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if suffix in (".jpg", ".jpeg"):
        img.save(str(out_path), format="JPEG", quality=jpeg_quality, optimize=True, progressive=False)
    else:
        # Small PNG fallback: quantize heavily
        q = img.convert("P", palette=Image.ADAPTIVE, colors=64)
        q.save(str(out_path), format="PNG", optimize=True)


def _best_image_pixmap(doc: fitz.Document, page: fitz.Page, min_pixels: int = 150 * 150) -> Optional[fitz.Pixmap]:
    """
    Return the largest embedded raster image on the page as Pixmap, normalized to RGB.
    More permissive thresholds to catch more images.
    """
    best = None
    best_area = 0

    for info in page.get_images(full=True):
        xref = info[0]
        try:
            pix = fitz.Pixmap(doc, xref)
        except Exception:
            continue

        area = pix.width * pix.height
        if area < min_pixels:
            continue

        # Normalize to RGB without alpha (smaller, more compatible)
        try:
            if pix.colorspace is not None and getattr(pix.colorspace, "n", 3) > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            elif pix.alpha:
                pix = fitz.Pixmap(fitz.csRGB, pix)
        except Exception:
            pass

        if area > best_area:
            best = pix
            best_area = area

    return best


def _render_top_half(page: fitz.Page, *, zoom: float = 1.5, top_ratio: float = 0.5) -> fitz.Pixmap:
    """Render only the top portion of the page to a Pixmap."""
    rect = page.rect
    clip = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + rect.height * top_ratio)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    return pix


def render_thumbnail(
    pdf_bytes: bytes,
    out_path: Path,
    *,
    search_pages: int = 5,          # scan more pages for images
    min_image_pixels: int = 150 * 150,
    zoom: float = 1.5,              # lower zoom for speed/smaller fallback
    top_ratio: float = 0.5,
    max_width: int = 400,
    jpeg_quality: int = 28,         # very low
) -> None:
    """
    Preferred thumbnail generator:
      1) Try to extract the largest embedded image from the first `search_pages` pages.
      2) If none found, render the TOP portion (top_ratio) of the first page.
      3) Save aggressively small (JPEG if possible, else quantized PNG).
    """
    if not (0 < top_ratio <= 1):
        raise ValueError("top_ratio must be within (0, 1].")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        if len(doc) == 0:
            raise ValueError("Empty PDF")

        # 1) Try embedded images
        pages_to_scan = min(search_pages, len(doc))
        best_pix: Optional[fitz.Pixmap] = None
        best_area = 0
        for i in range(pages_to_scan):
            page = doc[i]
            pix = _best_image_pixmap(doc, page, min_pixels=min_image_pixels)
            if pix is None:
                continue
            area = pix.width * pix.height
            if area > best_area:
                best_pix = pix
                best_area = area

        if best_pix is None:
            # 2) Fallback: top-half render of page 1
            best_pix = _render_top_half(doc[0], zoom=zoom, top_ratio=top_ratio)

    # 3) Save small
    if _HAS_PIL:
        img = _pixmap_to_pil(best_pix)
        _save_low_quality(img, out_path, max_width=max_width, jpeg_quality=jpeg_quality)
    else:
        # Fallback without Pillow: just downscale via PyMuPDF by re-rendering at lower zoom if possible
        # Already low zoom for fallback; ensure final size not huge by re-saving the pixmap.
        best_pix.save(str(out_path))


def render_first_page_thumbnail(pdf_bytes: bytes, out_path: Path, zoom: float = 1.5, top_ratio: float = 0.5) -> None:
    """
    Backward-compat wrapper — renders TOP portion of page 1, saved small.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        if len(doc) == 0:
            raise ValueError("Empty PDF")
        pix = _render_top_half(doc[0], zoom=zoom, top_ratio=top_ratio)

    if _HAS_PIL:
        img = _pixmap_to_pil(pix)
        _save_low_quality(img, out_path, max_width=400, jpeg_quality=28)
    else:
        pix.save(str(out_path))


def system_abstract_source(text_first_pages: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract an 'Abstract' block if present in the given text (first pages) AND
    return a source tag. Source is 'System' when extracted locally.
    Returns: (abstract_text or None, abstract_source or None)
    """
    if not text_first_pages:
        return None, None

    # Find 'Abstract' case-insensitive
    m = re.search(r"\babstract\b[:\s]*", text_first_pages, re.I)
    if not m:
        return None, None

    start = m.end()
    # Stop at common next section headers
    stop = re.search(
        r"\n\s*(keywords|index terms|introduction|1\.\s|background|related work|methods?)\b",
        text_first_pages[start:],
        re.I,
    )
    end = start + (stop.start() if stop else 1200)  # cap length
    abstract = text_first_pages[start:end].strip()

    # Clean up excessive whitespace
    abstract = re.sub(r"[ \t]{2,}", " ", abstract)
    abstract = re.sub(r"\n{2,}", "\n", abstract)

    abstract = abstract[:4000] if abstract else None
    if abstract:
        return abstract, "System"
    return None, None


def system_abstract(text_first_pages: str) -> Optional[str]:
    """
    Backward-compat wrapper: return only abstract text (no source).
    Prefer system_abstract_source(...) if you need the source tag.
    """
    abs_text, _src = system_abstract_source(text_first_pages)
    return abs_text