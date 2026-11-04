"""Serve a page of a scanned site the way a crawler receives it (no JavaScript), for the report's agent player.

This is an HTML proxy of a third party's page, so it is deliberately narrow:
- only URLs the scan itself recorded (journey steps, discovery pages, check evidence), on the scanned site;
- fetched with the scanner's own SSRF-safe fetcher, honouring robots.txt unless that scan was explicitly run ignoring it;
- scripts, frames, plugins, <base> and event handlers are removed, and the response carries a CSP with `sandbox`, no script and no
  form submission, so even a hostile page cannot run code or post anything from our origin. The UI also shows it in a sandboxed iframe.
"""
from __future__ import annotations

import re
import time
from collections import OrderedDict
from html import escape
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from selectolax.lexbor import LexborHTMLParser
from sqlmodel import Session

from app.repo.models import Scan, Site
from app.services.crawler import load_robots
from app.services.discovery_view import _norm
from app.services.page_selector import same_site
from app.services.url_normalizer import ScanError

router = APIRouter(prefix="/api/scans", tags=["pages"])

CSP = (
    "sandbox; default-src 'none'; script-src 'none'; img-src https: http: data:; style-src https: http: 'unsafe-inline'; "
    "font-src https: http: data:; base-uri https: http:; form-action 'none'; frame-ancestors 'self'"
)
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, max-age=300",
}
_EVENT_ATTR = re.compile(r"""\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_JS_HREF = re.compile(r"""(href|src|action|formaction)\s*=\s*(["']?)\s*javascript:[^"'>\s]*\2""", re.I)
_CACHE: OrderedDict[tuple[int, str], tuple[float, str]] = OrderedDict()
_CACHE_MAX, _CACHE_TTL = 48, 600


def scan_urls(report: dict[str, Any] | None) -> set[str]:
    """Every URL a scan recorded: pages it opened, journey steps and the evidence pages of its checks."""
    urls: set[str] = set()
    rep = report or {}
    for page in (rep.get("coverage", {}).get("discovery") or {}).get("pages", []):
        urls.add(_norm(page["url"]))
    for result in rep.get("results", []):
        urls.update(_norm(u) for u in result.get("pages", []))
        journey = (result.get("details") or {}).get("journey") or {}
        urls.update(_norm(s["url"]) for s in journey.get("steps", []) if s.get("url"))
    return urls


def sanitize(html: str, base_url: str) -> str:
    tree = LexborHTMLParser(html)
    for selector in ("script", "iframe", "frame", "object", "embed", "base", "meta[http-equiv]"):
        for node in tree.css(selector):
            node.decompose()
    out = tree.html or ""
    out = _EVENT_ATTR.sub("", out)
    out = _JS_HREF.sub(r"\1=\2#\2", out)
    base = f'<base href="{escape(base_url, quote=True)}" target="_blank">'
    if re.search(r"<head[^>]*>", out, re.I):
        return re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + base, out, count=1, flags=re.I)
    return base + out


def _message(text: str, status: int) -> HTMLResponse:
    body = f"<!doctype html><meta charset='utf-8'><body style=\"font:14px system-ui;color:#555;padding:24px\">{escape(text)}</body>"
    return HTMLResponse(body, status_code=status, headers=HEADERS)


@router.get("/{scan_id}/page")
async def page_view(scan_id: int, url: str, request: Request) -> HTMLResponse:
    app = request.app
    app.state.page_limiter.check(request.client.host if request.client else "unknown")
    with Session(app.state.engine) as session:
        scan = session.get(Scan, scan_id)
        site = session.get(Site, scan.site_id) if scan else None
        if scan is None or site is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Scan not found"})
        report, ignore_robots, domain = scan.report, scan.ignore_robots, site.domain
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not same_site(url, domain) or _norm(url) not in scan_urls(report):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "That page was not part of this scan"})
    key = (scan_id, _norm(url))
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return HTMLResponse(hit[1], headers=HEADERS)

    fetcher = app.state.deps.fetcher_factory()
    try:
        robots = await load_robots(fetcher, f"{parts.scheme}://{parts.netloc}")
        robots.ignore = ignore_robots
        if not robots.allowed(url):
            return _message("robots.txt does not allow our scanner to open this page, so it is not shown.", 403)
        result = await fetcher.fetch(url, kind="page-view")
    except ScanError as e:
        return _message(f"The page could not be loaded now ({e.code}).", 502)
    finally:
        await fetcher.aclose()
    if result.status >= 400:
        return _message(f"The site answered HTTP {result.status} for this page.", 502)
    html = sanitize(result.text, result.final_url)
    _CACHE[key] = (time.monotonic(), html)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return HTMLResponse(html, headers=HEADERS)
