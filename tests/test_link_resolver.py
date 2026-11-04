"""LLM-first link resolution for brand sites in other markets (here: an Austrian site with slugs no keyword rule knows)."""
from __future__ import annotations

import json
import re

import httpx
import pytest

from app.checks.context import build_context
from app.checks.engine import load_template, make_report, run_checks
from app.services import link_resolver
from app.services.crawler import SafeFetcher, acquire_homepage
from app.services.link_resolver import ModelPicks, Pick, RolePicks, collect_links, resolve_models, resolve_roles
from app.services.url_normalizer import normalize_input
from tests.conftest import FakeWeb, html_page, public_resolver

HOST = "marke.example"
ORG = {"@context": "https://schema.org", "@type": "Organization", "name": "Marke Österreich", "url": f"https://{HOST}",
       "logo": f"https://{HOST}/l.png", "sameAs": ["https://x.example/m"], "brand": {"@type": "Brand", "name": "Marke"}}
KEYWORDS = {  # what the fake model "understands" from the anchor text (German/French/English)
    "configurator": r"konfigur|configur|bauen sie",
    "test_drive": r"probefahrt|essai|test drive",
    "locator": r"händler finden|haendler finden|concession|find a dealer",
    "models_list": r"alle modelle|nos modèles|all models",
    "offers": r"angebote|offres",
    "contact": r"^kontakt$|^contact$",
}


class FakeLlm:
    configured = True
    model = "fake-llm"

    def __init__(self, hostile_index: int | None = None):
        self.calls = 0
        self.hostile_index = hostile_index

    async def structured(self, system, user, model_cls, *, name="answer", effort=None, usage=None):
        self.calls += 1
        rows = [re.match(r"^(\d+)\. \[(\w+)\] '(.*)' -> (\S*)", ln) for ln in user.splitlines()]
        rows = [m for m in rows if m]
        if model_cls is ModelPicks:
            return ModelPicks(indices=[int(m.group(1)) for m in rows if m.group(4).startswith("/unsere-autos/")][:6])
        picks = {}
        for role in ("configurator", "test_drive", "stock_new", "stock_used", "locator", "shop", "offers", "models_list", "contact"):
            rx = KEYWORDS.get(role)
            hit = next((int(m.group(1)) for m in rows if rx and re.search(rx, m.group(3).lower())), None)
            if self.hostile_index is not None and role == "shop":
                hit = self.hostile_index  # a manipulated answer must not become a URL
            picks[role] = Pick(index=hit, reason="fake")
        return RolePicks(**picks)


def build_at():
    nav = ("<nav><a href='/unsere-autos'>Alle Modelle</a><a href='/aktuelles-und-vorteile'>Angebote</a>"
           "<a href='/ansprechpartner/vor-ort'>Händler finden</a><a href='/fahren-erleben/termin'>Probefahrt buchen</a>"
           "<a href='/bauen-sie-ihr-auto'>Konfigurator</a><a href='/hilfe/kontaktformular'>Kontakt</a></nav>")
    ld = f'<script type="application/ld+json">{json.dumps(ORG)}</script>'
    routes: dict[str, object] = {
        f"{HOST}/": html_page(f"<html lang='de'><head><title>Marke</title>{ld}</head><body>{nav}<h1>Marke Österreich</h1><p>"
                               + "Willkommen. " * 20 + "</p></body></html>"),
        f"{HOST}/unsere-autos": html_page("<html><body>" + nav + "".join(f"<a href='/unsere-autos/{m}'>{m}</a>" for m in ("kompakt-x", "stadt-y", "suv-z")) + "</body></html>"),
        f"{HOST}/aktuelles-und-vorteile": html_page("<html><body><h1>Angebote</h1></body></html>"),
        f"{HOST}/ansprechpartner/vor-ort": html_page("<html><head><title>Händler finden</title></head><body><h1>Händler finden</h1><ul>" + "".join(
            f"<li>Autohaus {i}, Hauptstraße nr. {i}, Telefon 0732 55{i:02d}00</li>" for i in range(6)) + "</ul></body></html>"),
        f"{HOST}/fahren-erleben/termin": html_page("<html><head><title>Probefahrt buchen</title></head><body><h1>Probefahrt buchen</h1><form><label for='n'>Name</label><input id='n' name='name'></form></body></html>"),
        f"{HOST}/bauen-sie-ihr-auto": html_page("<html><body><h1>Konfigurator</h1></body></html>"),
        f"{HOST}/hilfe/kontaktformular": html_page("<html><body><p>Telefon +43 1 234 5678</p></body></html>"),
        f"{HOST}/robots.txt": (200, {"content-type": "text/plain"}, "User-agent: *\nAllow: /"),
    }
    for m in ("kompakt-x", "stadt-y", "suv-z"):
        routes[f"{HOST}/unsere-autos/{m}"] = html_page(f"<html><body><h1>{m}</h1><p>ab 24.990 € · 110 PS · WLTP 5,1 l/100 km · Garantie 5 Jahre · Motorisierung Benzin</p></body></html>")
    web = FakeWeb(routes)
    return web, lambda **kw: SafeFetcher(transport=web.transport, resolver=public_resolver, **kw)


async def scan(llm):
    web, factory = build_at()
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input(HOST))
    ctx = await build_context(acq, HOST, "importer", fetcher, factory, delay_s=0, llm=llm)
    results = {r.check_id: r for r in await run_checks(ctx, load_template("importer"))}
    await fetcher.aclose()
    return ctx, results


@pytest.fixture(autouse=True)
def _clear_cache():
    link_resolver._CACHE.clear()


@pytest.mark.anyio
async def test_llm_finds_what_keyword_rules_do_not():
    ctx_rules, res_rules = await scan(None)
    assert res_rules["net.locator"].status == "fail" and res_rules["act.test_drive_route"].status == "fail"
    llm = FakeLlm()
    ctx, res = await scan(llm)
    assert res["net.locator"].status == "pass" and res["act.test_drive_route"].status == "pass"
    assert res["mod.urls"].details["model_pages_fetched"] == 3 and res["det.configurator"].status == "pass"
    assert ctx.link_resolution["locator"]["source"] == "llm" and ctx.link_resolution["locator"]["fetched"] is True
    assert ctx.link_resolution["model"]["source"] == "llm" and len(ctx.link_resolution["model"]["urls"]) == 3
    assert ctx.role_prefixes["models_list"] == "/unsere-autos"  # learned from the pick: sitemap/llms.txt checks can use it
    assert llm.calls == 2  # one call for roles, one for model pages


@pytest.mark.anyio
async def test_same_links_hit_the_cache_so_rescans_are_reproducible():
    llm = FakeLlm()
    await scan(llm)
    first = llm.calls
    ctx, _ = await scan(llm)
    assert llm.calls == first and ctx.link_resolution["locator"]["source"] == "llm"


@pytest.mark.anyio
async def test_invalid_or_hostile_picks_are_ignored():
    ctx, res = await scan(FakeLlm(hostile_index=9999))  # index outside the list
    assert "shop" not in ctx.link_resolution or ctx.link_resolution["shop"]["source"] != "llm"
    assert res["net.locator"].status == "pass"  # the other picks still work


@pytest.mark.anyio
async def test_resolver_never_returns_urls_outside_the_list_and_survives_llm_errors():
    web, factory = build_at()
    f = factory()
    acq = await acquire_homepage(f, normalize_input(HOST))
    from app.checks.context import Page
    home = Page(acq.homepage.final_url, "home", acq.homepage.status, acq.homepage.text)
    links = collect_links(home, HOST)
    picks = await resolve_roles(FakeLlm(), HOST, links)
    assert {p["url"] for p in picks.values()} <= {link.url for link in links}

    class Boom(FakeLlm):
        async def structured(self, *a, **k):
            raise RuntimeError("down")

    link_resolver._CACHE.clear()  # a cached answer would hide the failure
    assert await resolve_roles(Boom(), HOST, links) == {} and await resolve_models(Boom(), HOST, links, set()) == []
    assert await resolve_roles(None, HOST, links) == {}
    await f.aclose()


def test_collect_links_marks_zones_and_prefers_menu():
    from app.checks.context import Page
    html = ("<html><body><footer><a href='/impressum'>Impressum</a></footer><nav><a href='/modelle'>Modelle</a></nav>"
            "<main><a href='/x'>Teaser</a><a href='javascript:void(0)'>no</a><a href='https://other.example/a'>Extern</a></main></body></html>")
    links = collect_links(Page(f"https://{HOST}/", "home", 200, html), HOST)
    assert [link.zone for link in links] == ["menu", "content", "content", "footer"]
    assert [link.internal for link in links if link.text == "Extern"] == [False]


@pytest.mark.anyio
async def test_a_pick_cannot_be_the_sites_own_homepage_but_may_be_another_domain_root():
    from app.checks.context import Page

    class Root(FakeLlm):
        async def structured(self, system, user, model_cls, **kw):
            none = Pick(index=None, reason="-")
            return RolePicks(configurator=none, test_drive=none, stock_new=none, stock_used=Pick(index=1, reason="used cars"),
                             locator=Pick(index=0, reason="start page"), shop=none, offers=none, models_list=none, contact=none)

    html = f"<html><body><nav><a href='/'>Start</a><a href='https://gebrauchtwagen.example/'>Gebrauchtwagen</a></nav></body></html>"
    links = collect_links(Page(f"https://{HOST}/", "home", 200, html), HOST)
    picks = await resolve_roles(Root(), HOST, links)
    assert "locator" not in picks  # own homepage
    assert picks["stock_used"]["url"] == "https://gebrauchtwagen.example/" and picks["stock_used"]["internal"] is False
