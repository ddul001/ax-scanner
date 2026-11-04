"""Serve demo/sample-brand-site through the scanner's own fetcher (no network, no localhost: the scanner refuses private hosts)
and run the importer rules on it. Used by the offline tests, the opt-in live test and, from a shell, to see a real run:

    python -m tests.demo_site_runner            # real Muse agent (needs META_API_KEY)
    python -m tests.demo_site_runner --js-only  # same site, dealer list filled by JavaScript only (control: should fail)
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from pathlib import Path

import httpx

from app.checks.context import build_context
from app.checks.engine import load_template, make_report, run_checks
from app.services.crawler import SafeFetcher, acquire_homepage
from app.services.url_normalizer import normalize_input
from tests.conftest import public_resolver

SITE = Path(__file__).resolve().parent.parent / "demo" / "sample-brand-site"
HOST = "velora.ro"


def _file_for(path: str) -> Path | None:
    rel = path.lstrip("/") or "index.html"
    for cand in (rel, rel + ".html", rel.rstrip("/") + "/index.html"):
        p = (SITE / cand).resolve()
        if p.is_file() and SITE in p.parents:
            return p
    return None


def _js_only(html: str) -> str:
    """The same page, but the dealer list is filled in by JavaScript: nothing a no-JS agent can read (a very common build)."""
    return re.sub(r'<ul id="dealer-list">.*?</ul>', '<ul id="dealer-list"></ul><script>fetch("/api/dealers").then(r => r.json()).then(render)</script>', html, flags=re.S)


def build_fetcher_factory(js_only: bool = False):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.scheme == "http" and request.url.path == "/":
            return httpx.Response(301, headers={"location": f"https://{HOST}/"})
        if request.url.host not in (HOST, "www." + HOST):
            return httpx.Response(404, text="not found")
        f = _file_for(request.url.path)
        if f is None:
            return httpx.Response(404, text="not found")
        ctype = mimetypes.guess_type(f.name)[0] or "text/plain"
        if f.suffix == ".txt":
            ctype = "text/plain"
        text = f.read_text(encoding="utf-8")
        if js_only and f.name == "dealeri.html":
            text = _js_only(text)
        if js_only and "/dealeri/" in request.url.path:
            return httpx.Response(404, text="not found")  # detail pages are only reachable through the JS app
        return httpx.Response(200, headers={"content-type": f"{ctype}; charset=utf-8"}, text=text)

    return requests, lambda **kw: SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver, **kw)


async def run(llm=None, site_type: str = "importer", *, js_only: bool = False, discovery: bool = True):
    requests, factory = build_fetcher_factory(js_only)
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input(HOST))
    ctx = await build_context(acq, HOST, site_type, fetcher, factory, delay_s=0, llm=llm if discovery else None)
    ctx.llm = llm
    template = load_template(site_type)
    results = await run_checks(ctx, template)
    report = make_report(site_type, template, results)
    await fetcher.aclose()
    return {r.check_id: r for r in results}, report, ctx, requests


async def _main(js_only: bool = False) -> None:
    from app.config import settings
    from app.services.meta_llm import MetaLlm

    if not settings.meta_api_key:
        raise SystemExit("META_API_KEY is not set")
    llm = MetaLlm()
    res, report, ctx, requests = await run(llm, js_only=js_only)
    await llm.aclose()
    print(f"AX {report.ax_score} grade {report.grade}   layers: {[(l.layer, l.score) for l in report.layers]}")
    for r in res.values():
        print(f"  {r.check_id:22} {r.status:7} {r.summary[:120]}")
    j = res["ux.j_dealer"].details.get("journey", {})
    print("\nGoal:", j.get("goal"))
    for s in j.get("steps", []):
        print(f"  {s['idx']} {s['action']:9} {s['url'][-48:]:48} | {s['thought'][:70]}")
    print("Answer:", json.dumps(j.get("answer"), ensure_ascii=False))
    print("Verification:", json.dumps(res["ux.j_dealer"].details.get("verification"), ensure_ascii=False))
    print("Methods used:", sorted({r.method for r in requests}))


if __name__ == "__main__":
    import sys

    asyncio.run(_main(js_only="--js-only" in sys.argv))
