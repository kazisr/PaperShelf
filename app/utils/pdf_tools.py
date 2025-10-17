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


def file_safe(name: str) -> str:
    """Light sanitizer for filenames."""
    s = re.sub(r"[^\w\-.]+", "_", name.strip())
    return s[:200] or "file"


def extract_title_authors_year_from_bytes(pdf_bytes: bytes) -> Tuple[Optional[str], Optional[List[str]], Optional[str]]:
    """
    Very simple heuristics: look at first 1–3 pages text; guess title/authors/year.
    """
    title, authors, year = None, [], None
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = ""
        for i in range(min(3, len(doc))):
            text += "\n" + doc[i].get_text("text")

    # Title: first non-empty line before common headers
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:30]:
        if HEADER_STOP.search(ln):
            break
        if 6 < len(ln) < 220:
            title = title or ln

    # Authors: naive split by commas on the next line(s)
    if title and title in lines:
        idx = lines.index(title)
        candidate = " ".join(lines[idx + 1 : idx + 4])
        candidate = re.sub(r"\S+@\S+", "", candidate)
        parts = [p.strip() for p in re.split(r",| and ", candidate) if 1 < len(p.strip()) < 80]
        authors = [p for p in parts if not re.search(r"\d|section|university|department", p, re.I)]
        if not authors:
            authors = None
    else:
        authors = None

    # Year: first 19xx/20xx
    m = re.search(r"\b(19|20)\d{2}\b", text)
    if m:
        year = m.group(0)

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


def system_abstract(text_first_pages: str) -> Optional[str]:
    """
    Extract an 'Abstract' block if present in the given text (first pages).
    """
    if not text_first_pages:
        return None

    # Find 'Abstract' case-insensitive
    m = re.search(r"\babstract\b[:\s]*", text_first_pages, re.I)
    if not m:
        return None

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

    return abstract[:4000] if abstract else None