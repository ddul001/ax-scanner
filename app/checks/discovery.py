"""Discovery layer: can agents reach and read the site? (disc.*)"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.checks.context import AI_ROBOT_TOKENS, ScanContext
from app.checks.util import PRICE_RX, SPEC_WORDS, res, share_status
from app.domain.scoring import CheckResult
from app.services.page_selector import classify_url
from app.services.signals import fold

BLOCK_STATUSES = (401, 403, 429, 503)


async def robots_ai(
    ctx: ScanContext,
    spec: dict[str, Any],
    *,
    roles: tuple[str, ...] = ("stock_list", "vdp", "service"),
    where: str = "stock or service pages",
) -> CheckResult:
    if not ctx.robots.text:
        return res(spec, "pass", "No robots.txt: nothing is disallowed for AI bots.")
    targets = [p.url for p in ctx.by_role(*roles) if p.url] or [ctx.home.url]
    blocked: dict[str, list[str]] = {}
    for group in ("retrieval", "training"):
        for bot in AI_ROBOT_TOKENS[group]:
            hit = [u for u in targets if not ctx.robots.allowed(u, user_agent=bot)]
            if hit:
                blocked[bot] = hit[:2]
    retrieval = [b for b in AI_ROBOT_TOKENS["retrieval"] if b in blocked]
    training = [b for b in AI_ROBOT_TOKENS["training"] if b in blocked]
    found = [f"{b}: blocked on {blocked[b][0]}" for b in blocked]
    if retrieval:
        return res(spec, "fail", f"Agent/search bots blocked on {where}: {', '.join(retrieval)}.",
                   pages=targets[:5], found=found, missing=retrieval, details={"blocked": blocked})
    if training:
        return res(spec, "warn", f"Only training crawlers blocked ({', '.join(training)}); user-facing agents are allowed.",
                   pages=targets[:5], found=found, missing=[], details={"blocked": blocked})
    return res(spec, "pass", f"No AI bot is disallowed on {where}.", pages=targets[:5])


async def waf_ua(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    probe = await ctx.ua_probe()
    browser = probe.get("browser")
    if not browser or browser["status"] != 200:
        return res(spec, "na", "Baseline browser request did not return 200; cannot compare.", details={"probe": probe})
    lengths = browser.get("lengths") or [browser["length"]]
    blocked = []
    differs = []
    recovered = []
    for name, result in probe.items():
        if name == "browser":
            continue
        if result["error"] or result["status"] in BLOCK_STATUSES or result["status"] != 200:
            blocked.append(f"{name}: {result['error'] or result['status']}")
        elif not (min(lengths) * 0.9 <= result["length"] <= max(lengths) * 1.1):
            differs.append(f"{name}: {result['length']} bytes vs {min(lengths)}-{max(lengths)}")
        elif result.get("recovered"):
            recovered.append(name)
    if blocked:
        return res(spec, "fail", "The site answers AI user agents differently from a browser (blocked, confirmed on a second attempt).",
                   found=blocked, missing=[b.split(':')[0] for b in blocked], details={"probe": probe})
    if differs:
        return res(spec, "warn", "AI user agents get content of a different size (>10%).", found=differs,
                   details={"probe": probe})
    note = (
        f" (a first request from {', '.join(recovered)} was blocked and succeeded on retry: intermittent rate limiting)"
        if recovered else ""
    )
    return res(spec, "pass", "AI user agents receive the same status and content size as a browser." + note,
               details={"probe": probe, "intermittent": recovered})


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def sitemap(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    if not ctx.sitemap:
        return res(spec, "fail", "No readable sitemap.xml found.", missing=["sitemap"])
    vdps = [e for e in ctx.sitemap if ctx.classify(e.url) == "vdp"]
    if not vdps:
        return res(spec, "fail", f"Sitemap has {len(ctx.sitemap)} URLs but none looks like a vehicle detail page.",
                   missing=["VDP URLs"], details={"urls": len(ctx.sitemap)})
    dates = [d for d in (_parse_date(e.lastmod) for e in vdps) if d]
    newest = max(dates) if dates else None
    fresh = newest is not None and datetime.now(timezone.utc) - newest < timedelta(days=7)
    details = {"urls": len(ctx.sitemap), "vdp_urls": len(vdps), "newest_lastmod": newest.isoformat() if newest else None}
    if fresh:
        return res(spec, "pass", f"{len(vdps)} VDP URLs in sitemap, newest lastmod within 7 days.", details=details)
    why = "no lastmod on VDP URLs" if newest is None else "newest VDP lastmod is older than 7 days"
    return res(spec, "warn", f"{len(vdps)} VDP URLs in sitemap but {why}.", missing=["fresh lastmod"], details=details)


async def llms_txt(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    result = await ctx.fetch_text("/llms.txt", "llms.txt")
    if result is None or result.status != 200 or not result.text.strip() or result.text.lstrip().lower().startswith(("<!doctype", "<html")):
        return res(spec, "fail", "No /llms.txt found.", missing=["/llms.txt"])
    flat = re.findall(r"https?://[^\s)\]>\"']+", result.text) + re.findall(r"\]\((/[^)\s]+)\)", result.text)
    roles = {classify_url(u if u.startswith("http") else "https://x" + u) for u in flat}
    wanted = {"stock_list": "stock", "vdp": "stock", "service": "service", "contact": "contact"}
    covered = {wanted[x] for x in roles if x in wanted}
    snippet = result.text[:300]
    if len(covered) >= 2:
        return res(spec, "pass", f"llms.txt links to {', '.join(sorted(covered))}.", found=sorted(covered), snippet=snippet)
    return res(spec, "warn", "llms.txt exists but links to fewer than two of stock/service/contact.",
               found=sorted(covered), missing=sorted({"stock", "service", "contact"} - covered), snippet=snippet)


async def no_js(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    vdps = ctx.ok_by_role("vdp")
    if not vdps:
        return res(spec, "na", "No vehicle detail page was fetched.")
    good = []
    for page in vdps:
        text = fold(page.text)
        specs = sum(1 for pattern in SPEC_WORDS.values() if pattern.search(text))
        if PRICE_RX.search(page.text) and specs >= 3:
            good.append(page.url)
    share = len(good) / len(vdps)
    bad = [p.url for p in vdps if p.url not in good]
    return res(spec, share_status(share, 0.7, 0.4),
               f"Price and specs are in the raw HTML on {len(good)}/{len(vdps)} sampled VDPs.",
               pages=[p.url for p in vdps], found=good[:3], missing=bad[:3], details={"share": round(share, 2)})
