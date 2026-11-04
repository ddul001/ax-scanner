"""How the scanner found each kind of page: the evidence behind the report's Discovery tab.

Built once from the crawl context (what the LLM picked, what the rules found, what was rejected, what was read) and, after the
checks ran, annotated with the checks that used each page. Pure data: the UI only renders it.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.checks.context import Page, ScanContext
from app.domain.scoring import CheckResult
from app.services.page_selector import KINDS

ROLE_LABELS = {
    # brand / importer
    "models_list": "Model range",
    "locator": "Dealer network",
    "test_drive": "Test drive",
    "configurator": "Configurator",
    "offers": "Offers",
    "contact": "Contact",
    "shop": "Online shop / accessories",
    "stock_new": "New-car stock",
    "stock_used": "Used-car stock",
    "model": "Model pages",
    # dealer
    "stock_list": "Stock list",
    "service": "Service booking",
    "financing": "Financing",
    "faq": "FAQ",
    "vdp": "Vehicle pages",
    # online shop
    "categories": "Product categories",
    "cart": "Cart",
    "checkout": "Checkout",
    "shipping": "Delivery information",
    "returns": "Returns policy",
    "warranty": "Warranty",
    "product": "Product pages",
}
ITEM_ROLES = {"model", "vdp", "product"}


def expected_pages(site_type: str | None) -> list[dict[str, str]]:
    """The page categories the scanner looks for on this type of site (empty when the type has no page discovery)."""
    kind = KINDS.get(site_type or "")
    return [{"role": r, "label": ROLE_LABELS.get(r, r)} for r in kind.roles] if kind else []


def _norm(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.netloc.replace(':443', '').lower()}{parts.path.rstrip('/')}"


def _row(role: str, entry: dict[str, Any] | None, page: Page | None) -> dict[str, Any]:
    """One category: where it was found, by whom, and what happened to it."""
    entry = entry or {}
    url = entry.get("url") or (page.url if page is not None else None)
    llm_url = entry.get("url") if entry.get("source") == "llm" else None
    rules_url = entry.get("rules_url")
    read = bool(page is not None and page.ok)
    if entry.get("rejected"):
        state, source = "rejected", "rules" if read else "none"
        how = f"The LLM chose {llm_url or entry.get('url')} but the page does not look like this category; " + (
            f"the keyword rules found {page.url} instead." if read else "no other page was found.")
        url = page.url if read else entry.get("url")
    elif entry.get("external"):
        state, source = "external", "llm"
        how = (
            f"The LLM chose a link on another domain ({urlsplit(entry['url']).netloc}). "
            "It is recorded but was not scanned."
        )
    elif entry.get("source") == "llm" and read:
        agrees = bool(entry.get("agrees"))
        state, source = "found", "both" if agrees else "llm"
        if agrees:
            how = "The LLM picked it from the homepage links and the keyword rules agree."
        elif rules_url:
            how = f"The LLM picked it from the homepage links; the keyword rules would have chosen {rules_url}."
        else:
            how = "The LLM picked it from the homepage links; the keyword rules had no candidate."
    elif page is not None:
        url = page.url  # the page that was actually looked at, not an ignored LLM suggestion
        state, source = "found" if read else "unreadable", "rules"
        if not read:
            how = f"Found by the keyword rules, but the page could not be read (HTTP {page.status or 'error'})."
        elif entry.get("ignored"):
            how = "The LLM chose the same page as another category; the keyword rules supplied this one."
        else:
            how = "Found by the keyword rules on the URL."
    else:
        state, source = "not_found", "none"
        how = "Neither the LLM nor the keyword rules found a matching page on the homepage links."
    return {
        "role": role,
        "label": ROLE_LABELS.get(role, role),
        "url": url,
        "state": state,
        "source": source,
        "how": how,
        "reason": entry.get("reason") if entry.get("source") == "llm" else None,
        "rules_url": rules_url,
        "http_status": page.status if page is not None else None,
        "read": read,
        "used_by": [],
    }


def build_discovery(ctx: ScanContext, resolution: dict[str, Any], *, llm_used: bool) -> dict[str, Any] | None:
    kind = KINDS.get(ctx.site_type)
    if kind is None:
        return None
    first: dict[str, Page] = {}
    for page in ctx.pages:
        first.setdefault(page.role, page)
    roles = [_row(r, resolution.get(r), first.get(r)) for r in kind.roles]
    item_pages = [p for p in ctx.pages if p.role == kind.item_role]
    entry = resolution.get(kind.item_role) or {}
    if entry.get("source") == "llm":
        items_how = "The LLM chose them among the links of the category list."
    elif item_pages and entry.get("source") == "rules" and not entry.get("fallback"):
        items_how = "Sampled from the sitemap (a reproducible sample per site)."
    elif item_pages:
        items_how = "Chosen by the keyword rules."
    else:
        items_how = "No page of this kind was found."
    items = {
        "role": kind.item_role,
        "label": ROLE_LABELS.get(kind.item_role, kind.item_role),
        "source": entry.get("source") or ("rules" if item_pages else "none"),
        "fallback": entry.get("fallback"),
        "urls": [{"url": p.url, "http_status": p.status, "read": p.ok, "used_by": []} for p in item_pages],
        "how": items_how,
    }
    return {
        "mode": "llm_first" if llm_used else "rules_only",
        "roles": roles,
        "items": items,
        "pages": [
            {"role": p.role, "url": p.url, "http_status": p.status, "read": p.ok, "ms": p.elapsed_ms}
            for p in ctx.pages
        ],
        "sources": {
            "sitemap_urls": len(ctx.sitemap),
            "robots_txt": bool(ctx.robots.text),
            "pages_read": sum(p.ok for p in ctx.pages),
        },
        "summary": {
            "categories": len(roles),
            "found": sum(r["state"] == "found" for r in roles),
            "by_llm": sum(r["source"] in ("llm", "both") for r in roles),
            "by_rules": sum(r["source"] == "rules" for r in roles),
            "rejected": sum(r["state"] == "rejected" for r in roles),
            "external": sum(r["state"] == "external" for r in roles),
            "not_found": sum(r["state"] == "not_found" for r in roles),
        },
    }


def attach_usage(discovery: dict[str, Any] | None, results: list[CheckResult]) -> None:
    """Which checks looked at each page (CheckResult.pages), so a reader can follow a page to the findings it produced."""
    if not discovery:
        return
    by_url: dict[str, set[str]] = {}
    for result in results:
        for url in result.pages:
            by_url.setdefault(_norm(url), set()).add(result.check_id)
    for row in discovery["roles"]:
        if row.get("url"):
            row["used_by"] = sorted(by_url.get(_norm(row["url"]), ()))
    for item in discovery["items"]["urls"]:
        item["used_by"] = sorted(by_url.get(_norm(item["url"]), ()))
