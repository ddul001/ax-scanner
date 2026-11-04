"""Minimal, safe fetching for Step 0: robots.txt, homepage, one sitemap. GET only."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import settings
from app.services.url_normalizer import (
    Resolver,
    ScanError,
    Target,
    resolve_public,
    validate_url,
)

HTML_TYPES = ("text/html", "application/xhtml+xml")
XML_TYPES = ("application/xml", "text/xml", "text/plain", "application/xhtml+xml")
MAX_HTML_BYTES = 2_000_000
MAX_SITEMAP_URLS = 5_000
BLOCK_STATUSES = (401, 403, 429, 503)
RETRY_STATUSES = (429, 502, 503, 504)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    elapsed_ms: int
    redirects: list[str] = field(default_factory=list)


class SafeFetcher:
    """GET-only fetcher: validates every hop (SSRF), caps size, logs each request."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
        timeout: float | None = None,
        max_redirects: int = 5,
        user_agent: str | None = None,
    ) -> None:
        self.user_agent = user_agent or settings.bot_user_agent
        self._resolver = resolver
        self._max_redirects = max_redirects
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=timeout or settings.fetch_timeout_s,
            follow_redirects=False,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,*/*;q=0.5"},
        )
        self.log: list[dict[str, Any]] = []

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(
        self,
        url: str,
        *,
        kind: str,
        accept: tuple[str, ...] | None = HTML_TYPES,
        max_bytes: int = MAX_HTML_BYTES,
        retries: int | None = None,
    ) -> FetchResult:
        """GET with one polite retry for transient failures (a connection error, a timeout, 429/502/503/504). A 403 is never
        retried: that is an answer. Pass retries=0 where the raw first answer is the measurement (the WAF probe)."""
        attempts = (settings.fetch_retries if retries is None else retries) + 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                result = await self._fetch_once(url, kind=kind, accept=accept, max_bytes=max_bytes)
            except ScanError as e:
                if last or e.code != "UNREACHABLE":
                    raise
                await asyncio.sleep(settings.fetch_retry_delay_s)
                continue
            if last or result.status not in RETRY_STATUSES:
                return result
            await asyncio.sleep(settings.fetch_retry_delay_s)
        raise ScanError("UNREACHABLE", "Could not fetch the page")  # unreachable: the loop returns or raises

    async def _fetch_once(
        self,
        url: str,
        *,
        kind: str,
        accept: tuple[str, ...] | None,
        max_bytes: int,
    ) -> FetchResult:
        started = time.monotonic()
        redirects: list[str] = []
        current = url
        for _ in range(self._max_redirects + 1):
            host = validate_url(current)
            await resolve_public(host, self._resolver)
            try:
                async with self._client.stream("GET", current) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        redirects.append(current)
                        current = urljoin(current, resp.headers["location"])
                        continue
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if resp.status_code == 200 and accept and ctype and ctype not in accept:
                        self._record(kind, current, resp.status_code, started)
                        raise ScanError("NOT_HTML", f"Unexpected content type: {ctype}")
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) >= max_bytes:
                            del body[max_bytes:]
                            break
                    encoding = resp.encoding or "utf-8"
                    status = resp.status_code
            except httpx.HTTPError:
                self._record(kind, current, 0, started)
                raise ScanError("UNREACHABLE", f"Could not connect to {urlsplit(current).hostname}") from None
            text = body.decode(encoding, errors="replace")
            elapsed = self._record(kind, current, status, started)
            return FetchResult(url, current, status, ctype, text, elapsed, redirects)
        raise ScanError("UNREACHABLE", "Too many redirects")

    def _record(self, kind: str, url: str, status: int, started: float) -> int:
        elapsed = int((time.monotonic() - started) * 1000)
        self.log.append(
            {"kind": kind, "url": url, "status": status, "ua": self.user_agent, "elapsed_ms": elapsed}
        )
        return elapsed


class Robots:
    """Parsed robots.txt with an explicit opt-in override for scans the requester asked to run ignoring it."""

    def __init__(self, text: str = "", *, allow_all: bool = True, disallow_all: bool = False) -> None:
        self.text = text
        self._disallow_all = disallow_all
        self._parser = RobotFileParser()
        self._parser.parse(text.splitlines())
        self._parser.modified()  # without this RobotFileParser.can_fetch() always returns False
        self._allow_all = allow_all
        self.ignore = False  # set for a scan the requester explicitly asked to run ignoring robots.txt
        self.sitemaps: list[str] = self._parser.site_maps() or []

    def allowed(self, url: str, user_agent: str | None = None) -> bool:
        """May `user_agent` fetch `url`? With no user_agent this asks about OUR scanner, which an opt-in override can waive;
        asking about another agent (the disc.robots_ai analysis) always returns what robots.txt really says."""
        if self.ignore and user_agent is None:
            return True
        if self._disallow_all:
            return False
        if self._allow_all and not self.text:
            return True
        ua = (user_agent or settings.bot_user_agent).split("/")[0]
        return self._parser.can_fetch(ua, url)


async def load_robots(fetcher: SafeFetcher, origin: str) -> Robots:
    try:
        result = await fetcher.fetch(origin + "/robots.txt", kind="robots", accept=None, max_bytes=500_000)
    except ScanError as e:
        if e.code == "UNREACHABLE":
            return Robots()
        raise
    if result.status >= 500:  # RFC 9309 §2.3.1.4: unreachable robots => assume complete disallow
        return Robots(disallow_all=True)
    if result.status != 200:
        return Robots()
    return Robots(result.text)


@dataclass
class Acquisition:
    origin: str
    homepage: FetchResult
    robots: Robots


async def acquire_homepage(fetcher: SafeFetcher, target: Target, *, ignore_robots: bool = False) -> Acquisition:
    hosts = [target.host]
    if not target.host.startswith("www."):
        hosts.append("www." + target.host)
    last_error: ScanError | None = None
    for host in hosts:
        for scheme in ("https", "http"):
            origin = f"{scheme}://{host}"
            try:
                robots = await load_robots(fetcher, origin)
                robots.ignore = ignore_robots
                if not robots.allowed(origin + "/"):
                    blocked = ScanError("BLOCKED_BY_ROBOTS", "robots.txt disallows our crawler")
                    blocked.robots, blocked.origin = robots, origin  # the evidence for a partial report
                    raise blocked
                homepage = await fetcher.fetch(origin + "/", kind="homepage")
            except ScanError as e:
                if e.code in ("BLOCKED_BY_ROBOTS", "BLOCKED_TARGET", "NOT_HTML", "INVALID_URL"):
                    raise
                last_error = e
                continue
            if homepage.status in BLOCK_STATUSES:
                raise ScanError("BLOCKED_BY_WAF", f"Homepage returned HTTP {homepage.status} for our crawler")
            if homepage.status >= 400:
                last_error = ScanError("UNREACHABLE", f"Homepage returned HTTP {homepage.status}")
                continue
            final = urlsplit(homepage.final_url)
            port = f":{final.port}" if final.port not in (None, 80, 443) else ""
            return Acquisition(f"{final.scheme}://{final.hostname}{port}", homepage, robots)
    raise last_error or ScanError("UNREACHABLE", "Could not fetch the homepage")


_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_PREFERRED_CHILD = re.compile(r"vehic|stoc|stock|masin|car|produc|model|inventory|coche", re.I)
_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.I | re.S)
_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)


@dataclass
class SitemapEntry:
    url: str
    lastmod: str | None = None


def _locs(xml: str) -> list[str]:
    return _LOC.findall(xml)


def _entries(xml: str) -> list[SitemapEntry]:
    blocks = _URL_BLOCK.findall(xml)
    if not blocks:
        return [SitemapEntry(u) for u in _locs(xml)]
    out = []
    for block in blocks:
        loc = _LOC.search(block)
        if loc:
            lastmod = _LASTMOD.search(block)
            out.append(SitemapEntry(loc.group(1), lastmod.group(1) if lastmod else None))
    return out


async def load_sitemap_urls(fetcher: SafeFetcher, acquired: Acquisition) -> list[str]:
    return [e.url for e in await load_sitemap_entries(fetcher, acquired)]


async def load_sitemap_entries(fetcher: SafeFetcher, acquired: Acquisition) -> list[SitemapEntry]:
    """Best effort: first sitemap (or the best child of an index). Never raises."""
    candidates = acquired.robots.sitemaps[:1] or [acquired.origin + "/sitemap.xml"]
    try:
        url = candidates[0]
        if url.endswith(".gz") or not acquired.robots.allowed(url):
            return []
        result = await fetcher.fetch(url, kind="sitemap", accept=XML_TYPES, max_bytes=5_000_000)
        if result.status != 200:
            return []
        if "<sitemapindex" in result.text[:2000].lower():
            children = [c for c in _locs(result.text) if not c.endswith(".gz")]
            if not children:
                return []
            child = next((c for c in children if _PREFERRED_CHILD.search(c)), children[0])
            if not acquired.robots.allowed(child):
                return []
            result = await fetcher.fetch(child, kind="sitemap", accept=XML_TYPES, max_bytes=5_000_000)
            if result.status != 200:
                return []
        return _entries(result.text)[:MAX_SITEMAP_URLS]
    except ScanError:
        return []
