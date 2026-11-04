"""ScanContext: everything the checks read. Pages are fetched once; probes are lazy and cached."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.checks.util import PRICE_RX
from app.config import settings
from app.services.crawler import Acquisition, FetchResult, Robots, SafeFetcher, SitemapEntry, load_sitemap_entries
from app.services.page_selector import (
    DEALER_BUDGET,
    KINDS,
    PageRef,
    SiteKind,
    classify_url,
    infer_vdp_prefixes,
    same_site,
    select_pages,
    vdp_candidates_from_list,
)
from app.services.signals import fold, parse_jsonld
from app.services.url_normalizer import ScanError

if TYPE_CHECKING:
    from app.services.link_resolver import StructuredLlm

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
# user agents of AI crawlers/agents as published by their operators; used for ONE GET of the homepage each
AI_USER_AGENTS = {
    "GPTBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.1; +https://openai.com/gptbot)",
    "ChatGPT-User": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    "ClaudeBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
    "PerplexityBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
}
# robots.txt product tokens (RFC 9309) checked by disc.robots_ai; retrieval-type bots act on behalf of a user
AI_ROBOT_TOKENS = {
    "retrieval": ["ChatGPT-User", "OAI-SearchBot", "Claude-User", "PerplexityBot"],
    "training": ["GPTBot", "ClaudeBot", "Google-Extended", "Applebot-Extended", "CCBot"],
}


@dataclass
class Page:
    url: str
    role: str
    status: int
    html: str
    content_type: str = ""
    elapsed_ms: int = 0
    error: str | None = None
    _tree: HTMLParser | None = field(default=None, repr=False)
    _jsonld: list[dict[str, Any]] | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.html)

    @property
    def tree(self) -> HTMLParser:
        if self._tree is None:
            self._tree = HTMLParser(self.html or "")
        return self._tree

    @property
    def jsonld(self) -> list[dict[str, Any]]:
        if self._jsonld is None:
            self._jsonld = parse_jsonld(self.html)
        return self._jsonld

    @property
    def text(self) -> str:
        tree = HTMLParser(self.html or "")
        tree.strip_tags(["script", "style", "noscript", "template", "svg"])
        return re.sub(r"\s+", " ", tree.body.text(separator=" ", strip=True)) if tree.body else ""

    @property
    def links(self) -> list[tuple[str, str]]:
        out = []
        for anchor in self.tree.css("a[href]"):
            href = anchor.attributes.get("href") or ""
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            out.append((urljoin(self.url, href), anchor.text(strip=True)))
        return out


@dataclass
class ScanContext:
    origin: str
    host: str
    site_type: str
    home: Page
    robots: Robots
    sitemap: list[SitemapEntry]
    pages: list[Page]
    fetcher: SafeFetcher
    fetcher_factory: Callable[..., SafeFetcher] | None = None
    vdp_prefixes: frozenset[str] = frozenset()
    llm: StructuredLlm | None = None
    link_resolution: dict[str, Any] = field(default_factory=dict)  # brand sites: role -> {url, source, reason, rules_url}
    discovery: dict[str, Any] | None = None  # how the pages were found (see app/services/discovery_view.py)
    role_prefixes: dict[str, str] = field(default_factory=dict)  # brand sites: role -> URL path prefix learned from the LLM picks
    _cache: dict[str, Any] = field(default_factory=dict)

    def classify(self, url: str) -> str | None:
        return classify_url(url, self.vdp_prefixes)

    def by_role(self, *roles: str) -> list[Page]:
        return [p for p in self.pages if p.role in roles]

    def ok_by_role(self, *roles: str) -> list[Page]:
        return [p for p in self.by_role(*roles) if p.ok]

    async def _once(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        if key not in self._cache:
            try:
                self._cache[key] = await factory()
            except ScanError as e:
                self._cache[key] = e
        return self._cache[key]

    async def fetch_text(self, path: str, kind: str) -> FetchResult | None:
        """GET origin+path (robots-checked); returns FetchResult, None when disallowed/unreachable."""
        url = urljoin(self.origin + "/", path.lstrip("/"))
        if not self.robots.allowed(url):
            return None

        async def go() -> FetchResult:
            return await self.fetcher.fetch(url, kind=kind, accept=None, max_bytes=300_000)

        result = await self._once(f"fetch:{path}", go)
        return None if isinstance(result, ScanError) else result

    async def ua_probe(self) -> dict[str, dict[str, Any]]:
        """Homepage status + size for a browser UA and each AI UA, one request each, spaced out. A blocked or different-looking
        answer is confirmed with a second attempt (and a fresh browser sample) before it counts: WAFs rate-limit bursts."""

        async def once(name: str, ua: str) -> dict[str, Any] | None:
            probe_fetcher = self.fetcher_factory(user_agent=ua) if self.fetcher_factory else None
            if probe_fetcher is None:
                return None
            try:
                result = await probe_fetcher.fetch(self.origin + "/", kind=f"ua:{name}", accept=None, max_bytes=2_000_000, retries=0)
                return {"status": result.status, "length": len(result.text), "error": None}
            except ScanError as e:
                return {"status": 0, "length": 0, "error": e.code}
            finally:
                await probe_fetcher.aclose()

        def blocked(result: dict[str, Any]) -> bool:
            return bool(result["error"]) or result["status"] != 200

        def differs(result: dict[str, Any], lengths: list[int]) -> bool:
            return bool(lengths) and not (min(lengths) * 0.9 <= result["length"] <= max(lengths) * 1.1)

        async def go() -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for name, ua in {"browser": BROWSER_UA, **AI_USER_AGENTS}.items():
                result = await once(name, ua)
                if result is None:
                    break
                out[name] = {**result, "attempts": 1}
                await asyncio.sleep(settings.probe_delay_s)
            browser = out.get("browser")
            if not browser:
                return out
            browser["lengths"] = [browser["length"]]
            for name, ua in AI_USER_AGENTS.items():
                result = out.get(name)
                if result is None or (browser["status"] == 200 and not blocked(result) and not differs(result, browser["lengths"])):
                    continue
                await asyncio.sleep(settings.probe_retry_delay_s)  # confirm before it counts
                browser_again = await once("browser", BROWSER_UA)
                if browser_again and not blocked(browser_again):
                    browser["lengths"].append(browser_again["length"])
                again = await once(name, ua)
                if again is not None:
                    first = {k: result[k] for k in ("status", "length", "error")}
                    out[name] = {
                        **again, "attempts": 2, "first": first,
                        "recovered": blocked(result) and not blocked(again),
                    }
            return out

        cached = await self._once("ua_probe", go)
        return {} if isinstance(cached, ScanError) else cached

    async def http_redirect(self) -> dict[str, Any]:
        """Does plain http:// redirect to https://? (one GET, no redirect following beyond SafeFetcher's)."""

        async def go() -> dict[str, Any]:
            probe_fetcher = self.fetcher_factory() if self.fetcher_factory else None
            if probe_fetcher is None:
                return {"tested": False}
            try:
                result = await probe_fetcher.fetch(f"http://{self.host}/", kind="http-redirect", accept=None, max_bytes=50_000)
                return {
                    "tested": True, "final": result.final_url,
                    "https": result.final_url.startswith("https://"), "status": result.status,
                }
            except ScanError as e:
                return {"tested": True, "error": e.code, "https": False}
            finally:
                await probe_fetcher.aclose()

        cached = await self._once("http_redirect", go)
        return {"tested": False} if isinstance(cached, ScanError) else cached


_BUY_MARKERS = (
    "add to cart", "adauga in cos", "adauga la cos", "adaugă în coș", "añadir al carrito",
    "in den warenkorb", "cere oferta", "cere ofertă", "solicita oferta",
)
_NOT_MODEL = re.compile(r"(?:legal|termen|cookie|privacy|confiden|gdpr|politic|cariere|career|despre|about|presa|press|noutati|news|blog|sitemap|login|cont|search|cauta)")
_MODEL_EVIDENCE = re.compile(r"(?:wltp|co2|g/km|l/100|\b\d{2,4}\s?(?:cp|hp|kw|cv|ps)\b|\bmotoriz\w*|\bengine\w*|\bversiun\w*)", re.I)


async def _verified_model_pages(
    pages: list[Page],
    host: str,
    seen: set[str],
    polite: Callable[[PageRef], Awaitable[Page]],
    room: int,
    kind: SiteKind | None = None,
) -> list[Page]:
    """Brand sites often have model pages at /<model> with no common prefix: try the unclassified links of the model
    list (or the homepage) and keep only pages that carry price or engine evidence."""
    kind = kind or KINDS["importer"]
    src = [p for p in pages if p.ok and p.role == kind.list_role] or [p for p in pages if p.role == "home"]
    candidates = sorted(
        {
            u.split("#", 1)[0].split("?", 1)[0]
            for p in src for u, t in p.links
            if same_site(u, host) and kind.classify(u) is None and u not in seen
            and 1 <= len([x for x in urlsplit(u).path.split("/") if x]) <= 2 and 2 <= len(t) <= 40
            and not _NOT_MODEL.search(u.lower())
        },
        key=lambda u: (len(urlsplit(u).path.split("/")), len(u), u),
    )
    candidates = [u for u in candidates if u not in seen][: min(6, max(room, 0))]
    got = await asyncio.gather(*(polite(PageRef(u, kind.item_role)) for u in candidates))

    def looks_right(page: Page) -> bool:
        if not (page.ok and PRICE_RX.search(page.text)):
            return False
        if kind.item_role == "product":  # a product page: Product data or a buy/offer control
            low = page.html.lower()
            return any("Product" in str(n.get("@type")) for n in page.jsonld) or any(k in low for k in _BUY_MARKERS)
        return len(_MODEL_EVIDENCE.findall(page.text)) >= 2

    return [p for p in got if looks_right(p)][: kind.item_max]


def _path_prefix(url: str) -> str | None:
    """'/modelle' for https://x/modelle or /modelle/; None for files (.html) or the site root."""
    path = urlsplit(url).path.rstrip("/")
    return path if path and "." not in path.rsplit("/", 1)[-1] else None


async def build_context(
    acquired: Acquisition,
    host: str,
    site_type: str,
    fetcher: SafeFetcher,
    fetcher_factory: Callable[..., SafeFetcher] | None,
    *,
    delay_s: float = 0.2,
    llm: StructuredLlm | None = None,
) -> ScanContext:
    sitemap = await load_sitemap_entries(fetcher, acquired)
    home = Page(
        acquired.homepage.final_url, "home", acquired.homepage.status, acquired.homepage.text,
        acquired.homepage.content_type, acquired.homepage.elapsed_ms,
    )
    home_links = [u for u, _ in home.links]
    prefixes = frozenset(infer_vdp_prefixes([e.url for e in sitemap]))
    kind = KINDS.get(site_type)  # brand/importer and e-commerce sites: LLM-first link resolution
    brand = kind is not None
    if brand:
        plan = select_pages(host, home.url, home_links + [e.url for e in sitemap], kind.budget, kind.classify)
    else:
        plan = select_pages(host, home.url, home_links + [e.url for e in sitemap])

    async def get(ref: PageRef) -> Page:
        if not acquired.robots.allowed(ref.url):
            return Page(ref.url, ref.role, 0, "", error="BLOCKED_BY_ROBOTS")
        try:
            result = await fetcher.fetch(ref.url, kind=ref.role)
            return Page(result.final_url, ref.role, result.status, result.text, result.content_type, result.elapsed_ms)
        except ScanError as e:
            return Page(ref.url, ref.role, 0, "", error=e.code)

    pages = [home]
    sem = asyncio.Semaphore(3)

    async def polite(ref: PageRef) -> Page:
        async with sem:
            await asyncio.sleep(delay_s)
            return await get(ref)

    first = [r for r in plan if r.role != "home"]
    resolution: dict[str, Any] = {}
    rule_models: list[PageRef] = []
    llm_links = None
    if brand and llm is not None:
        # LLM first: it picks among the homepage links (any language); rules only fill what it leaves empty
        from app.services.link_resolver import collect_links, resolve_roles  # local: link_resolver imports Page from here

        llm_links = collect_links(home, host)
        picks = await resolve_roles(llm, host, llm_links, site_type)
        rules_url = {r.role: r.url for r in reversed(first)}
        used: set[str] = set()
        chosen: list[PageRef] = []
        for role in kind.roles:
            pick = picks.get(role)
            if pick is None:
                continue
            entry = {
                "url": pick["url"], "source": "llm", "reason": pick["reason"], "rules_url": rules_url.get(role),
                "agrees": rules_url.get(role) == pick["url"],
            }
            if pick["internal"] and pick["url"] in used:
                entry.update(source="rules", ignored="same page as another role")  # one page, one role: rules fill this one
            elif pick["internal"]:
                used.add(pick["url"])
                chosen.append(PageRef(pick["url"], role))
            else:
                entry["external"] = True  # another domain: recorded for the detections, not crawled
            resolution[role] = entry
        rule_models = [r for r in first if r.role == kind.item_role] if kind.llm_items else []
        taken = {c.role for c in chosen}
        keep = [r for r in first if r.role not in taken and (r.role != kind.item_role or not kind.llm_items) and r.url not in used]
        first = (chosen + keep)[:13]
    pages += await asyncio.gather(*(polite(r) for r in first))

    if brand and resolution:
        # the LLM may answer a role although no link fits: drop picks whose page does not look like the role; rules fill in
        from app.services.role_evidence import looks_like  # local: role_evidence imports Page from here

        for page in list(pages):
            entry = resolution.get(page.role)
            if page is not home and entry and entry.get("source") == "llm" and page.ok and not looks_like(page.role, page):
                pages.remove(page)
                resolution[page.role] = {
                    "url": entry.get("url"), "source": "rules",
                    "rejected": f"the page chosen by the LLM does not look like a {page.role} page",
                    "rules_url": entry.get("rules_url"),
                }

    # sites without usable sitemap: discover VDPs from the stock list pages we just fetched
    have_vdp = [p for p in pages if p.role == "vdp"]
    if (not brand or not kind.llm_items) and len(have_vdp) < 3:
        seen = {p.url for p in pages}
        extra_urls: list[str] = []
        if llm_links is not None:  # the sitemap sample was too small: let the LLM recognise vehicle pages (any language)
            from app.services.link_resolver import collect_links, resolve_models  # local: see above

            src = next((p for p in pages if p.role == "stock_list" and p.ok), None)
            links = collect_links(src, host) if src is not None else llm_links
            picked = (await resolve_models(llm, host, links, seen, site_type))[: 5 - len(have_vdp)]
            extra_urls = [m["url"] for m in picked]
            if extra_urls:
                resolution["vdp"] = {"source": "llm", "urls": extra_urls, "rules_urls": [p.url for p in have_vdp]}
        if len(have_vdp) + len(extra_urls) < 3:  # rules: vehicle-looking links of the stock list pages
            found: list[str] = []
            for page in pages:
                if page.role == "stock_list" and page.ok:
                    found += vdp_candidates_from_list(page.url, [u for u, _ in page.links], host, prefixes)
            extra_urls += [u for u in sorted(set(found)) if u not in seen and u not in extra_urls]
        extra = [PageRef(u, "vdp") for u in extra_urls][: 5 - len(have_vdp)]
        pages += await asyncio.gather(*(polite(r) for r in extra))

    # roles still missing (e.g. test drive is only linked from vehicle pages): look at links of the pages we have
    got = {p.role for p in pages if p.ok}
    seen = {p.url for p in pages}
    more: list[PageRef] = []
    if brand:
        budget, classify_fn, roles = kind.budget, kind.classify, kind.roles
    else:
        budget, classify_fn = DEALER_BUDGET, classify_url
        roles = ("test_drive", "service", "contact", "financing", "faq")
    for role in roles:
        if role in got or len(pages) + len(more) >= 15:
            continue
        candidates = sorted(
            {
                u for p in pages if p.ok for u, _ in p.links
                if same_site(u, host) and classify_fn(u) == role and u not in seen
            },
            key=lambda u: (len(u), u),
        )
        more += [PageRef(u, role) for u in candidates[: budget.get(role, 1)]]
    if more:
        pages += await asyncio.gather(*(polite(r) for r in more[: 15 - len(pages)]))

    if brand and kind.llm_items:
        have = {p.url for p in pages}
        if llm_links is not None:  # model pages: the LLM chooses among the links of the model list (or the homepage)
            from app.services.link_resolver import collect_links, resolve_models  # local: see above

            src = next((p for p in pages if p.role == kind.list_role and p.ok), None)
            links = collect_links(src, host) if src is not None else llm_links
            room = min(kind.item_max, 15 - len(pages))
            picked = (await resolve_models(llm, host, links, have, site_type))[:room]
            if not picked and src is not None:  # the list page had no item links (e.g. only sub-categories): try the homepage
                picked = (await resolve_models(llm, host, llm_links, have, site_type))[:room]
            if picked:
                pages += await asyncio.gather(*(polite(PageRef(m["url"], kind.item_role)) for m in picked))
                resolution[kind.item_role] = {
                    "source": "llm", "urls": [m["url"] for m in picked],
                    "rules_urls": [r.url for r in rule_models],
                }
        if sum(p.role == kind.item_role and p.ok for p in pages) < 2:  # fallback: rules, then verified unclassified links
            have = {p.url for p in pages}
            extra = [r for r in rule_models if r.url not in have][: max(0, min(kind.item_max, 15 - len(pages)))]
            if extra:
                pages += await asyncio.gather(*(polite(r) for r in extra))
            if sum(p.role == kind.item_role and p.ok for p in pages) < 2:
                pages += await _verified_model_pages(pages, host, {p.url for p in pages}, polite, 15 - len(pages), kind)
            if any(p.role == kind.item_role and p.ok for p in pages):
                resolution.setdefault(kind.item_role, {"source": "rules"})
                resolution[kind.item_role]["fallback"] = "rules"

    ctx = ScanContext(
        acquired.origin, host, site_type, home, acquired.robots, sitemap, pages, fetcher, fetcher_factory, prefixes
    )
    if brand:
        for role, entry in resolution.items():
            if role != kind.item_role and entry.get("url"):
                entry["fetched"] = any(p.role == role and p.ok for p in pages)
        for role in kind.roles:
            if role not in resolution and any(p.role == role and p.ok for p in pages):
                resolution[role] = {
                    "url": next(p.url for p in pages if p.role == role and p.ok),
                    "source": "rules", "fetched": True,
                }
        if not kind.llm_items:  # dealer: say where the vehicle pages came from
            vdps = [p.url for p in pages if p.role == "vdp" and p.ok]
            resolution.setdefault("vdp", {"source": "rules", "urls": vdps})
        ctx.link_resolution = resolution
        from app.services.discovery_view import build_discovery  # local: discovery_view imports ScanContext from here

        ctx.discovery = build_discovery(ctx, resolution, llm_used=llm_links is not None)
        for role in kind.prefix_roles:
            prefix = _path_prefix(resolution[role]["url"]) if role in resolution and resolution[role].get("url") else None
            if prefix:
                ctx.role_prefixes[role] = prefix
        item_urls = [p.url for p in pages if p.role == kind.item_role and p.ok]
        parents = {_path_prefix(u.rsplit("/", 1)[0]) for u in item_urls}
        if len(parents) == 1 and next(iter(parents)):
            ctx.role_prefixes[kind.item_role] = next(iter(parents))
    return ctx
