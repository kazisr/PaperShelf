from __future__ import annotations
import re, datetime as dt
from typing import Optional, Dict, Any, List
import httpx
import feedparser
from urllib.parse import quote

DOI_RE = re.compile(r'\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b')
ARXIV_RE = re.compile(
    r'\barXiv:(\d{4}\.\d{4,5})(v\d+)?\b|\b(\d{4}\.\d{4,5})(v\d+)?\b',
    re.I
)

CROSSREF_WORKS = "https://api.crossref.org/works/"
CROSSREF_SEARCH = "https://api.crossref.org/works"
ARXIV_API = "http://export.arxiv.org/api/query"

UA = "PaperShelf/1.0 (mailto:kazi.rafid@seu.edu.bd)"  # put your contact here
TIMEOUT = httpx.Timeout(15.0)

def extract_ids_from_text(text: str) -> Dict[str, Optional[str]]:
    doi = None
    m = DOI_RE.search(text or "")
    if m:
        doi = m.group(0)

    arxiv_id = None
    m2 = ARXIV_RE.search(text or "")
    if m2:
        arxiv_id = (m2.group(1) or m2.group(3))
    return {"doi": doi, "arxiv_id": arxiv_id}

def _norm_authors_crossref(items: List[Dict[str, Any]]) -> List[str]:
    names = []
    for a in items or []:
        given, family = a.get("given", ""), a.get("family", "")
        full = " ".join([given, family]).strip() or a.get("name") or ""
        if full:
            names.append(full)
    return names

def _parse_date(parts) -> Optional[dt.date]:
    try:
        comp = (parts.get("date-parts") or [[]])[0]
        year = comp[0]
        month = comp[1] if len(comp) > 1 else 1
        day = comp[2] if len(comp) > 2 else 1
        return dt.date(year, month, day)
    except Exception:
        return None

async def fetch_crossref_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    url = CROSSREF_WORKS + quote(doi, safe="")
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        m = r.json().get("message", {})
        return {
            "title": (m.get("title") or [""])[0],
            "authors": _norm_authors_crossref(m.get("author")),
            "year": str((m.get("issued") or {}).get("date-parts", [[None]])[0][0]) if m.get("issued") else None,
            "venue": (m.get("container-title") or [""])[0],
            "abstract": None,
            "url": m.get("URL") or (f"https://doi.org/{doi}" if doi else None),
            "published_at": _parse_date(m.get("issued")),
            "doi": doi
        }

async def search_crossref_by_title(title: str) -> Optional[Dict[str, Any]]:
    if not title:
        return None
    params = {"query.title": title, "rows": 1}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}) as client:
        r = await client.get(CROSSREF_SEARCH, params=params)
        if r.status_code != 200:
            return None
        items = r.json().get("message", {}).get("items", [])
        if not items:
            return None
        m = items[0]
        doi = m.get("DOI")
        return await fetch_crossref_by_doi(doi) if doi else None

async def fetch_arxiv_by_id(arxiv_id: str) -> Optional[Dict[str, Any]]:
    params = {"search_query": f"id:{arxiv_id}", "max_results": 1}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}) as client:
        r = await client.get(ARXIV_API, params=params)
        if r.status_code != 200:
            return None
        feed = feedparser.parse(r.text)
        if not feed.entries:
            return None
        e = feed.entries[0]
        authors = [a.name for a in getattr(e, "authors", [])]
        published = dt.date.fromisoformat(e.published[:10]) if getattr(e, "published", None) else None
        norm_id = (e.id.split("/")[-1]).split("v")[0] if getattr(e, "id", None) else arxiv_id
        return {
            "title": e.title.strip(),
            "authors": authors,
            "year": str(published.year) if published else None,
            "venue": "arXiv",
            "abstract": getattr(e, "summary", None),
            "url": e.link,
            "published_at": published,
            "arxiv_id": norm_id
        }

async def search_arxiv_by_title(title: str) -> Optional[Dict[str, Any]]:
    if not title:
        return None
    params = {"search_query": f'all:"{title}"', "max_results": 1}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}) as client:
        r = await client.get(ARXIV_API, params=params)
        if r.status_code != 200:
            return None
        feed = feedparser.parse(r.text)
        if not feed.entries:
            return None
        e = feed.entries[0]
        arxiv_id = (e.id.split("/")[-1]).split("v")[0]
        return await fetch_arxiv_by_id(arxiv_id)

async def autofetch_metadata(pdf_text_first_pages: str, title_hint: Optional[str]) -> Optional[Dict[str, Any]]:
    ids = extract_ids_from_text(pdf_text_first_pages or "")
    if ids["doi"]:
        m = await fetch_crossref_by_doi(ids["doi"])
        if m:
            return m
    if ids["arxiv_id"]:
        m = await fetch_arxiv_by_id(ids["arxiv_id"])
        if m:
            return m
    if title_hint:
        m = await search_crossref_by_title(title_hint)
        if m:
            return m
        m = await search_arxiv_by_title(title_hint)
        if m:
            return m
    return None