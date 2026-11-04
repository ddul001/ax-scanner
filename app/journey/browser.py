"""Read-only 'crawler view' browser for the Agent Journey: GET + parse, no JavaScript, same-site only, robots-aware."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.checks.context import Page
from app.checks.util import CAPTCHA_MARKERS, first_str, jsonld_types
from app.services.crawler import Robots, SafeFetcher
from app.services.page_selector import classify_brand_url, classify_shop_url, classify_url, same_site
from app.services.signals import fold
from app.services.url_normalizer import ScanError

MAX_LINKS = 60
TEXT_CHARS = 2500
LOCATOR_LINKS, LOCATOR_CHARS = 150, 6000  # a dealer list is long: the agent must be able to reach the entry for its city
VEHICLE = {"Car", "Vehicle", "Motorcycle"}
_COOKIE = re.compile(r"cookie|consent|gdpr|acord|accept")
PRIORITY_ROLES = ("vdp", "stock_list", "test_drive", "service", "contact", "financing")
SHOP_PRIORITY_ROLES = ("product", "categories", "offers", "cart", "checkout")
BRAND_PRIORITY_ROLES = ("locator", "test_drive", "contact", "models_list", "model", "offers", "configurator")


@dataclass
class Link:
    index: int
    text: str
    url: str


@dataclass
class View:
    url: str
    status: int = 0
    title: str = ""
    text: str = ""
    links: list[Link] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    structured: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    error: str | None = None
    external_links: int = 0

    def for_agent(self) -> dict[str, Any]:
        return {
            "url": self.url, "http_status": self.status, "title": self.title, "error": self.error,
            "blockers": self.blockers, "text": self.text,
            "links": [{"i": link.index, "text": link.text, "url": link.url} for link in self.links],
            "external_links_omitted": self.external_links, "forms": self.forms, "structured_data": self.structured,
        }


def _vehicle_digest(page: Page) -> list[dict[str, Any]]:
    out = []
    for node in page.jsonld:
        if VEHICLE & set(jsonld_types(node)):
            offer = node.get("offers") if isinstance(node.get("offers"), dict) else {}
            mileage = node.get("mileageFromOdometer")
            out.append({k: v for k, v in {
                "name": first_str(node.get("name")), "price": offer.get("price"), "currency": offer.get("priceCurrency"),
                "vin": node.get("vehicleIdentificationNumber"),
                "mileage": first_str(mileage.get("value")) if isinstance(mileage, dict) else None,
                "fuel": first_str(node.get("fuelType")),
            }.items() if v not in (None, "")})
    return out[:3]


def _forms(page: Page) -> list[dict[str, Any]]:
    out = []
    for form in page.tree.css("form")[:4]:
        fields = []
        for field in form.css("input, select, textarea"):
            input_type = (field.attributes.get("type") or "text").lower()
            if field.tag == "input" and input_type in ("hidden", "submit", "button", "image"):
                continue
            label = ""
            field_id = field.attributes.get("id")
            if field_id and (label_el := page.tree.css_first(f'label[for="{field_id}"]')):
                label = label_el.text(strip=True)
            label = label or field.attributes.get("aria-label") or field.attributes.get("placeholder") or ""
            fields.append({
                "name": field.attributes.get("name") or "", "label": label[:50], "type": input_type,
                "required": "required" in field.attributes,
            })
        if fields:
            out.append({"method": (form.attributes.get("method") or "get").lower(), "fields": fields[:15]})
    return out


def _key(url: str) -> str:
    """Comparable form of a URL (no fragment, default port, trailing slash)."""
    parts = urlsplit(url)
    return f"{parts.netloc.replace(':443', '').lower()}{parts.path.rstrip('/')}"


def build_view(page: Page, site_type: str = "dealer", priority: frozenset[str] = frozenset()) -> View:
    view = View(page.url, page.status)
    if not page.ok:
        view.error = page.error or f"HTTP {page.status}"
        if page.status in (401, 403, 429, 503):
            view.blockers.append(f"http_{page.status}")
        return view
    title = page.tree.css_first("title")
    view.title = (title.text(strip=True) if title else "")[:150]
    text = page.text
    locator = site_type == "importer" and classify_brand_url(page.url) == "locator"
    view.text = text[: LOCATOR_CHARS if locator else TEXT_CHARS]
    ranked = []
    seen = set()
    for url, label in page.links:
        if url in seen or not url.startswith("http"):
            continue
        seen.add(url)
        ranked.append((url, re.sub(r"\s+", " ", label)[:60]))
    classify, wanted = {
        "importer": (classify_brand_url, BRAND_PRIORITY_ROLES),
        "ecommerce": (classify_shop_url, SHOP_PRIORITY_ROLES),
    }.get(site_type, (classify_url, PRIORITY_ROLES))
    # stable: links the discovery step identified first, then links whose URL looks interesting, then the rest
    ranked.sort(key=lambda x: 0 if _key(x[0]) in priority else 1 if classify(x[0]) in wanted else 2)
    view.links = [Link(i, t, u) for i, (u, t) in enumerate(ranked[: LOCATOR_LINKS if locator else MAX_LINKS])]
    view.forms = _forms(page)
    view.structured = _vehicle_digest(page)
    low = page.html.lower()
    if any(m in low for m in CAPTCHA_MARKERS):
        view.blockers.append("captcha")
    if len(text) < 400 and _COOKIE.search(fold(text)):
        view.blockers.append("cookie_wall")
    if len(text) < 150 and ("<script" in low):
        view.blockers.append("js_only_content")
    return view


class HttpBrowser:
    """What an AI crawler sees: server-rendered HTML only. Same site only, robots respected, GET only."""

    def __init__(
        self, fetcher: SafeFetcher, robots: Robots, host: str, *, delay_s: float = 0.3, site_type: str = "dealer",
        priority_urls: frozenset[str] = frozenset(),
    ) -> None:
        self.fetcher = fetcher
        self.robots = robots
        self.host = host
        self.delay_s = delay_s
        self.site_type = site_type
        self.priority = frozenset(_key(u) for u in priority_urls)
        self.history: list[View] = []
        self.requests = 0

    @property
    def current(self) -> View | None:
        return self.history[-1] if self.history else None

    async def fetch_page(self, url: str) -> Page | None:
        """Raw page for verification (same rules as navigation). None if not allowed/unreachable."""
        if not same_site(url, self.host) or not self.robots.allowed(url):
            return None
        try:
            await asyncio.sleep(self.delay_s)
            self.requests += 1
            result = await self.fetcher.fetch(url, kind="journey")
        except ScanError:
            return None
        return Page(result.final_url, "journey", result.status, result.text, result.content_type, result.elapsed_ms)

    async def goto(self, url: str) -> View:
        if not same_site(url, self.host):
            view = View(url, error=f"OFF_SITE: only pages of {self.host} can be opened")
        elif not self.robots.allowed(url):
            view = View(url, error="BLOCKED_BY_ROBOTS: robots.txt disallows this page", blockers=["robots_disallowed"])
        else:
            try:
                await asyncio.sleep(self.delay_s)
                self.requests += 1
                result = await self.fetcher.fetch(url, kind="journey")
                view = build_view(
                    Page(result.final_url, "journey", result.status, result.text, result.content_type, result.elapsed_ms),
                    self.site_type, self.priority,
                )
            except ScanError as e:
                view = View(url, error=f"{e.code}: {e.message}")
        self.history.append(view)
        return view

    async def open_link(self, index: int) -> View:
        current = self.current
        if current is None or not (0 <= index < len(current.links)):
            view = View(current.url if current else "", error=f"INVALID_LINK: no link with index {index} on this page")
            self.history.append(view)
            return view
        return await self.goto(current.links[index].url)

    async def back(self) -> View:
        ok = [v for v in self.history if not v.error]
        if len(ok) >= 2:
            self.history.append(ok[-2])
            return ok[-2]
        view = View(self.current.url if self.current else "", error="NO_HISTORY: nothing to go back to")
        self.history.append(view)
        return view
