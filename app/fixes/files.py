"""File fixes: llms.txt and robots.txt. Both are verified against the same logic the checks use."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from app.checks.context import AI_ROBOT_TOKENS, Page, ScanContext
from app.fixes.base import FixDraft
from app.fixes.jsonld import _meta, _site_name
from app.services.crawler import Robots
from app.services.page_selector import classify_url
from app.services.signals import fold

SECTIONS = (
    ("stock", "Stock", ("stock_list",)),
    ("service", "Service", ("service",)),
    ("contact", "Contact", ("contact",)),
)
WANTED = {"stock_list": "stock", "vdp": "stock", "service": "service", "contact": "contact"}
MAX_FEATURED = 5


# ---------- llms.txt ----------

def llms_coverage(text: str) -> set[str]:
    """Same extraction as the disc.llms_txt check."""
    flat = re.findall(r"https?://[^\s)\]>\"']+", text) + re.findall(r"\]\((/[^)\s]+)\)", text)
    roles = {classify_url(u if u.startswith("http") else "https://x" + u) for u in flat}
    return {WANTED[r] for r in roles if r in WANTED}


def _title(page: Page, fallback: str) -> str:
    h1 = page.tree.css_first("h1")
    return (h1.text(strip=True) if h1 else "") or fallback


def _links_for(ctx: ScanContext, roles: tuple[str, ...], limit: int = 1) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in ctx.ok_by_role(*roles):
        if page.url not in seen:
            seen.add(page.url)
            out.append((_title(page, urlsplit(page.url).path.strip("/") or page.url), page.url))
    for url, label in ctx.home.links:
        host = (urlsplit(url).hostname or "").lower()
        same = host == ctx.host or host.endswith("." + ctx.host) or ctx.host.endswith("." + host)
        if url in seen or ctx.classify(url) not in roles or not same:
            continue
        seen.add(url)
        out.append((label or urlsplit(url).path.strip("/"), url))
    return out[:limit]


async def build_llms(ctx: ScanContext) -> FixDraft:
    result = await ctx.fetch_text("/llms.txt", "llms.txt")
    existing = (
        result.text.strip()
        if result is not None and result.status == 200 and not result.text.lstrip().lower().startswith(("<!doctype", "<html"))
        else ""
    )
    assumptions: list[str] = []
    lines: list[str] = []
    covered = llms_coverage(existing) if existing else set()
    if existing:
        lines = [existing, ""]
        assumptions.append("Your existing llms.txt is kept as is; only the missing sections are appended.")
    else:
        name = _site_name(ctx) or ctx.host
        lines = [f"# {name}", ""]
        desc = _meta(ctx.home, "description")
        if desc:
            lines += [f"> {desc}", ""]
            assumptions.append("Summary taken from the homepage meta description.")
    todo: list[str] = []
    for key, heading, roles in SECTIONS:
        if key in covered:
            continue
        links = _links_for(ctx, roles)
        if not links:
            todo.append(f"{heading.lower()} page (not found on the site)")
            continue
        lines += [f"## {heading}"] + [f"- [{t}]({u})" for t, u in links] + [""]
    if "stock" not in covered:
        feats = [(_title(p, p.url), p.url) for p in ctx.ok_by_role("vdp")][:MAX_FEATURED]
        if feats:
            lines += ["## Featured vehicles"] + [f"- [{t}]({u})" for t, u in feats] + [""]
    if not desc_present(lines) and not existing:
        todo.append("one-sentence description of the dealership")
    content = "\n".join(lines).rstrip() + "\n"
    errors = [] if len(llms_coverage(content)) >= 2 else ["Fewer than two of stock/service/contact pages were found to link to."]
    return FixDraft(
        check_id="disc.llms_txt", type="llms_txt", title="llms.txt", target_url=ctx.origin + "/llms.txt",
        filename="llms.txt", content_type="text/markdown", content=content,
        placement="Serve at the site root: /llms.txt (200, text/markdown or text/plain).",
        assumptions=assumptions, todo=todo, errors=errors,
    )


def desc_present(lines: list[str]) -> bool:
    return any(line.startswith("> ") for line in lines)


# ---------- robots.txt ----------

def _parse(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    groups: list[dict[str, Any]] = []
    other: list[str] = []
    current: dict[str, Any] | None = None
    last_ua = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        name, value = (x.strip() for x in line.split(":", 1))
        key = name.lower()
        if key == "user-agent":
            if current is None or not last_ua:
                current = {"agents": [], "rules": []}
                groups.append(current)
            current["agents"].append(value)
            last_ua = True
            continue
        last_ua = False
        if key == "sitemap" or current is None:
            other.append(f"{name}: {value}")
        else:
            current["rules"].append(f"{name}: {value}")
    return groups, other


def _render(groups: list[dict[str, Any]], other: list[str]) -> str:
    blocks = ["\n".join([f"User-agent: {a}" for a in g["agents"]] + g["rules"]) for g in groups if g["agents"]]
    if other:
        blocks.append("\n".join(other))
    return "\n\n".join(blocks) + "\n"


def build_robots(ctx: ScanContext, bots: list[str], targets: list[str]) -> FixDraft:
    groups, other = _parse(ctx.robots.text)
    star = [r for g in groups if any(a == "*" for a in g["agents"]) for r in g["rules"]]
    wanted = {b.lower() for b in bots}
    for group in groups:  # drop the blocked bots from their old groups so the new groups are not merged with them
        group["agents"] = [a for a in group["agents"] if a.lower() not in wanted]
    groups = [g for g in groups if g["agents"]]

    def keeps_access(rule: str) -> bool:
        probe = Robots(f"User-agent: x\n{rule}\n")
        return all(probe.allowed(u, user_agent="x") for u in targets)

    kept = [r for r in star if r.lower().startswith("disallow:") and r.split(":", 1)[1].strip() and keeps_access(r)]
    for bot in bots:
        groups.append({"agents": [bot], "rules": kept + ["Allow: /"]})  # specific Disallows first: stdlib parser is first-match
    content = _render(groups, other)
    fixed = Robots(content)
    errors = [f"{b} is still blocked on {u}" for b in bots for u in targets if not fixed.allowed(u, user_agent=b)]
    training = (
        [t for t in AI_ROBOT_TOKENS["training"] if not Robots(ctx.robots.text).allowed(targets[0], user_agent=t)]
        if targets else []
    )
    assumptions = [
        f"Allowed the user-facing AI bots {', '.join(bots)} on stock and service pages.",
        "Other rules of the '*' group that do not cover those pages were copied into each bot group.",
        "Comments of the original file are not preserved; compare with a diff before publishing.",
    ]
    if training:
        assumptions.append(f"Training crawlers ({', '.join(training)}) were left as they are: that is a business policy choice.")
    return FixDraft(
        check_id="disc.robots_ai", type="robots_txt", title="robots.txt: allow AI agents", target_url=ctx.origin + "/robots.txt",
        filename="robots.txt", content=content, placement="Replace the file served at /robots.txt after reviewing the diff.",
        assumptions=assumptions, errors=errors,
    )
