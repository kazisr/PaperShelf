# app/services/metadata.py
from __future__ import annotations

import asyncio
import html
import math
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

# You can tweak these without changing other code.
USER_AGENT = "PaperShelf/1.0 (+https://example.com; mailto:you@example.com)"
HTTP_TIMEOUT_S = 8.0
RETRIES = 3                      # per request
INITIAL_BACKOFF_S = 0.6          # exponential backoff base
JITTER_S = 0.25                  # add a little randomness to avoid thundering herd

# ---------- detection ----------

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)

# arXiv: modern 1901.01234[v2] or legacy cs/0301001
_ARXIV_ID_RE = re.compile(
    r"\b(?:arXiv:)?((\d{4}\.\d{4,5})(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})\b",
    re.I,
)

def _clean_trailing_punct(s: str) -> str:
    return s.rstrip(").,;:]}>")


def detect_doi(text: str) -> Optional[str]:
    if not text:
        return None
    m = _DOI_RE.search(text)
    if not m:
        return None
    return _clean_trailing_punct(m.group(1))


def detect_arxiv_id(text: str) -> Optional[str]:
    if not text:
        return None
    m = _ARXIV_ID_RE.search(text)
    if not m:
        return None
    return m.group(1)  # normalized, without "arXiv:"


# ---------- http helpers (with retry/backoff) ----------

async def _get_json(url: str, params: dict | None = None) -> Tuple[Optional[dict], Optional[int]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(RETRIES):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, headers=headers) as client:
                r = await client.get(url, params=params)
            if r.status_code == 200:
                try:
                    return r.json(), 200
                except Exception:
                    return None, 200
            # Retry on 429/5xx; otherwise stop.
            if r.status_code in (429, 500, 502, 503, 504):
                # fallthrough to backoff
                pass
            else:
                return None, r.status_code
        except httpx.TimeoutException:
            # retry
            pass
        except Exception:
            # transient network issues; retry
            pass

        # backoff
        delay = (INITIAL_BACKOFF_S * (2 ** attempt)) + random.uniform(0, JITTER_S)
        await asyncio.sleep(delay)

    return None, None


async def _get_text(url: str, params: dict | None = None, accept: str = "application/atom+xml") -> Tuple[Optional[str], Optional[int]]:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    for attempt in range(RETRIES):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, headers=headers) as client:
                r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.text, 200
            if r.status_code in (429, 500, 502, 503, 504):
                pass
            else:
                return None, r.status_code
        except httpx.TimeoutException:
            pass
        except Exception:
            pass

        delay = (INITIAL_BACKOFF_S * (2 ** attempt)) + random.uniform(0, JITTER_S)
        await asyncio.sleep(delay)

    return None, None


# ---------- fetchers ----------

async def fetch_crossref_by_doi(doi: str) -> Optional[dict]:
    if not doi:
        return None
    url = f"https://api.crossref.org/works/{doi}"
    data, _ = await _get_json(url)
    if not data or "message" not in data:
        return None
    return data["message"]


async def fetch_crossref_by_title(title: str) -> Optional[dict]:
    if not title:
        return None
    params = {"query.title": title, "rows": 1}
    data, _ = await _get_json("https://api.crossref.org/works", params=params)
    if not data or "message" not in data:
        return None
    items = (data.get("message") or {}).get("items") or []
    return items[0] if items else None


async def fetch_arxiv_by_id(arxiv_id: str) -> Optional[dict]:
    # ArXiv Atom feed; robust light parsing
    if not arxiv_id:
        return None
    text, _ = await _get_text(
        "http://export.arxiv.org/api/query",
        params={"id_list": arxiv_id},
        accept="application/atom+xml",
    )
    if not text:
        return None

    def tag(name: str) -> str:
        return rf"<{name}[^>]*>(.*?)</{name}>"

    entry_m = re.search(r"<entry>([\s\S]*?)</entry>", text, re.I)
    if not entry_m:
        return None
    entry = entry_m.group(1)

    title = None
    tm = re.search(tag("title"), entry, re.I)
    if tm:
        title = html.unescape(re.sub(r"\s+", " ", tm.group(1)).strip())

    abstract = None
    sm = re.search(tag("summary"), entry, re.I)
    if sm:
        abstract = html.unescape(re.sub(r"\s+", " ", sm.group(1)).strip())

    authors: List[str] = []
    for am in re.finditer(r"<author>([\s\S]*?)</author>", entry, re.I):
        nm = re.search(tag("name"), am.group(1), re.I)
        if nm:
            authors.append(html.unescape(nm.group(1)).strip())

    published_at = None
    year = None
    pm = re.search(tag("published"), entry, re.I)
    if pm:
        published_at = pm.group(1).strip()
        ym = re.match(r"(\d{4})", published_at)
        if ym:
            year = ym.group(1)

    url = None
    link_pdf = re.search(r'<link[^>]+type="application/pdf"[^>]+href="([^"]+)"', entry, re.I)
    link_abs = re.search(r'<link[^>]+rel="alternate"[^>]+href="([^"]+)"', entry, re.I)
    if link_pdf:
        url = link_pdf.group(1)
    elif link_abs:
        url = link_abs.group(1)

    return {
        "title": title,
        "abstract": abstract,
        "authors": authors or None,
        "year": year,
        "published_at": published_at,
        "url": url,
        "arxiv_id": arxiv_id,
        "venue": "arXiv",
        "source": "arxiv",
    }


# ---------- normalization ----------

def _norm_crossref(msg: dict) -> dict:
    if not msg:
        return {}

    # title
    title = None
    t = msg.get("title")
    if isinstance(t, list) and t:
        title = t[0]
    elif isinstance(t, str):
        title = t

    # authors
    authors: List[str] = []
    for a in msg.get("author", []) or []:
        name = " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
        if not name:
            name = (a.get("name") or "").strip()
        if name:
            authors.append(name)

    # date
    year = None
    published_at = None
    for key in ("published-print", "published-online", "issued"):
        part = msg.get(key)
        if part and "date-parts" in part and part["date-parts"]:
            dp = part["date-parts"][0]
            if dp:
                year = str(dp[0])
                published_at = "-".join(map(str, dp))
                break

    doi = msg.get("DOI")
    url = msg.get("URL")

    # venue
    venue = None
    ct = msg.get("container-title")
    if isinstance(ct, list) and ct:
        venue = ct[0]
    elif isinstance(ct, str):
        venue = ct

    # abstract (may be JATS)
    abstract = None
    if isinstance(msg.get("abstract"), str):
        abstract = re.sub(r"<[^>]+>", "", msg["abstract"])
        abstract = re.sub(r"\s+", " ", abstract).strip() or None

    return {
        "title": title,
        "authors": authors or None,
        "year": year,
        "published_at": published_at,
        "doi": doi,
        "url": url,
        "venue": venue,
        "abstract": abstract,
        "source": "crossref",
    }


def _merge_priority(primary: dict, secondary: dict) -> dict:
    """Primary wins; fill blanks from secondary."""
    out = dict(primary)
    for k, v in (secondary or {}).items():
        if out.get(k) in (None, "", [], {}):
            out[k] = v
    return out


def _as_list(x) -> Optional[List[str]]:
    if not x:
        return None
    if isinstance(x, list):
        return x
    return [str(x)]


# ---------- main entry ----------

async def autofetch_metadata(text_first_pages: str, title_hint: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Merge priority: Crossref (via DOI) > arXiv (via id) > Crossref (title search).
    All network calls are resilient; partial results are returned when available.
    """
    text = text_first_pages or ""
    doi = detect_doi(text)
    arxiv_id = detect_arxiv_id(text)

    # schedule fetches
    tasks: List[asyncio.Task] = []
    order: List[str] = []
    if doi:
        tasks.append(asyncio.create_task(fetch_crossref_by_doi(doi)))
        order.append("crossref-doi")
    if arxiv_id:
        tasks.append(asyncio.create_task(fetch_arxiv_by_id(arxiv_id)))
        order.append("arxiv-id")
    if not doi and title_hint and len(title_hint) > 6:
        tasks.append(asyncio.create_task(fetch_crossref_by_title(title_hint)))
        order.append("crossref-title")

    # collect (don’t fail hard if one source errors)
    results: Dict[str, Any] = {}
    if tasks:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
        # map back in scheduled order
        idx = 0
        for t in tasks:
            label = order[idx]; idx += 1
            try:
                results[label] = t.result()
            except Exception:
                results[label] = None
    else:
        results = {}

    # normalize pieces
    meta_crossref_doi = _norm_crossref(results.get("crossref-doi")) if results.get("crossref-doi") else None
    meta_arxiv = results.get("arxiv-id") or None
    meta_crossref_title = _norm_crossref(results.get("crossref-title")) if results.get("crossref-title") else None

    # inject IDs if missing
    if meta_crossref_doi and doi and not meta_crossref_doi.get("doi"):
        meta_crossref_doi["doi"] = doi
    if meta_arxiv and arxiv_id and not meta_arxiv.get("arxiv_id"):
        meta_arxiv["arxiv_id"] = arxiv_id
    if meta_crossref_title and doi and not meta_crossref_title.get("doi"):
        meta_crossref_title["doi"] = doi

    # merge in priority
    merged: Dict[str, Any] = {}
    for part in (meta_crossref_doi, meta_arxiv, meta_crossref_title):
        if part:
            merged = _merge_priority(part, merged)

    # ensure shapes
    if "authors" in merged:
        merged["authors"] = _as_list(merged["authors"])
    if merged.get("year"):
        merged["year"] = str(merged["year"])

    # keep detected ids if not present
    if doi and not merged.get("doi"):
        merged["doi"] = doi
    if arxiv_id and not merged.get("arxiv_id"):
        merged["arxiv_id"] = arxiv_id

    # return None only if truly empty
    meaningful = any(merged.get(k) for k in ("title", "authors", "year", "abstract", "doi", "arxiv_id", "venue", "url"))
    return merged if meaningful else None