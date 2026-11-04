"""WebMCP detection (act.webmcp): which tools does the site offer to in-browser agents? Static analysis only.

Two ways a page can expose tools to an agent (WebMCP):
- declarative: an HTML element with a `toolname` attribute (usually a <form> with `tooldescription`, optional `toolautosubmit`);
- imperative: JavaScript that calls `navigator.modelContext.registerTool(...)` / `provideContext({tools: [...]})`.

The scanner reads the HTML and the same-site scripts the homepage loads. It never runs JavaScript and never calls a tool, so the
result says what is DECLARED, not whether a tool works. Script text is untrusted data.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.checks.context import Page, ScanContext
from app.checks.util import res
from app.domain.scoring import CheckResult
from app.services.page_selector import same_site

MAX_SCRIPTS = 6
_TOOL_SHAPE = re.compile(r"inputSchema|input_schema|parameters|execute|handler|schema", re.I)
_REGISTER = re.compile(r"registerTool|provideContext|modelContext\s*\.\s*\w+")
_NAME = re.compile(r"""\bname\s*:\s*["']([a-z][a-z0-9_]{2,48})["']""")
_DESC = re.compile(r"""\bdescription\s*:\s*(?:"([^"\\]{10,400})"|'([^'\\]{10,400})'|`([^`\\]{10,400})`)""")
BUY_TOOL = re.compile(r"cart|buy|order|purchase|checkout|offer|quote|oferta|cerere|cumpar|comand|devis|angebot|pedido|presupuesto", re.I)
DRIVE_TOOL = re.compile(r"drive|probefahrt|essai|prueba|test_?drive", re.I)


def _declarative(pages: list[Page]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = set()
    for page in pages:
        for el in page.tree.css("[toolname]"):
            name = (el.attributes.get("toolname") or "").strip()
            if not name or (name, page.url) in seen:
                continue
            seen.add((name, page.url))
            out.append({
                "name": name[:60], "kind": "declarative", "page": page.url,
                "description": (el.attributes.get("tooldescription") or "")[:300],
                "auto_submit": "toolautosubmit" in el.attributes, "element": el.tag,
            })
    return out


def _imperative(script_text: str, url: str) -> list[dict[str, Any]]:
    """Tool definitions in a script that registers tools. Heuristic: a snake_case `name:` followed, within 900 chars, by a
    `description:` and by a schema/handler key (inputSchema, parameters, execute, ...). Property names do not match."""
    if not _REGISTER.search(script_text):
        return []
    out: dict[str, dict[str, Any]] = {}
    for match in _NAME.finditer(script_text):
        name = match.group(1)
        if "_" not in name and name not in ("search", "compare"):
            continue
        after = script_text[match.end(): match.end() + 900]
        desc = _DESC.search(after)
        if not desc or not _TOOL_SHAPE.search(after):
            continue
        out.setdefault(name, {
            "name": name, "kind": "imperative", "script": url,
            "description": next(g for g in desc.groups() if g)[:300], "auto_submit": False,
        })
    return list(out.values())


async def detect(ctx: ScanContext) -> dict[str, Any]:
    """{tools: [...], scripts_scanned: [...]}; cached per scan."""

    async def go() -> dict[str, Any]:
        pages = [p for p in ctx.pages if p.ok]
        tools = _declarative(pages)
        srcs: list[str] = []
        for script in ctx.home.tree.css("script[src]"):
            src = (script.attributes.get("src") or "").strip()
            if not src:
                continue
            url = urljoin(ctx.home.url, src)
            if same_site(url, ctx.host) and url not in srcs:
                srcs.append(url)
        scanned = []
        for url in srcs[:MAX_SCRIPTS]:
            parts = urlsplit(url)
            result = await ctx.fetch_text(parts.path + (f"?{parts.query}" if parts.query else ""), "webmcp-script")
            if result is None or result.status != 200 or not result.text:
                continue
            scanned.append(url)
            tools += _imperative(result.text, url)
        names = {}
        for tool in tools:  # one entry per tool name; the declarative one wins (it carries the page and auto-submit flag)
            names.setdefault(tool["name"], tool)
        return {"tools": list(names.values()), "scripts_scanned": scanned}

    cached = await ctx._once("webmcp", go)
    return cached if isinstance(cached, dict) else {"tools": [], "scripts_scanned": []}


async def webmcp(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    found = await detect(ctx)
    tools = found["tools"]
    details = {"detected": bool(tools), "scripts_scanned": len(found["scripts_scanned"]), "executed": False, "tools": tools[:12]}
    if not tools:
        return res(spec, "na", "No WebMCP tools detected (no toolname attributes and no registerTool calls in the page scripts).",
                   details=details)
    names = [t["name"] for t in tools]
    auto = [t["name"] for t in tools if t.get("auto_submit")]
    note = f" Tools that auto-submit without a human step: {', '.join(auto)}." if auto else ""
    return res(spec, "pass", f"WebMCP detected: {len(tools)} tool(s): {', '.join(names[:8])}. Declared only, nothing was run.{note}",
               pages=sorted({t.get("page") or t.get("script") for t in tools if t.get("page") or t.get("script")})[:4],
               found=names[:12], details=details)


async def purchase_tool(ctx: ScanContext) -> dict[str, Any] | None:
    """A WebMCP tool that lets an agent order, add to cart or request an offer (used to soften add-to-cart failures)."""
    for tool in (await detect(ctx))["tools"]:
        if BUY_TOOL.search(tool["name"]) or BUY_TOOL.search(tool.get("description", "")):
            return tool
    return None


REGISTRY = {"act.webmcp": webmcp}
