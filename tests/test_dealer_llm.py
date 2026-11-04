"""LLM-first page discovery for dealers: roles come from the LLM, the vehicle sample stays rules-first (sitemap), LLM fills in."""
from __future__ import annotations

import re

import httpx
import pytest

from app.checks.context import build_context
from app.checks.engine import load_template, make_report, run_checks
from app.services import link_resolver
from app.services.crawler import SafeFetcher, acquire_homepage
from app.services.link_resolver import ModelPicks, Pick
from app.services.url_normalizer import normalize_input
from tests.conftest import FakeWeb, html_page, public_resolver
from tests.site_builder import CARS, FORM, build_site, dealer_jsonld, vdp_html

HOST = "a.example"
KEYWORDS = {"stock_list": r"gebrauchtwagen|stoc", "test_drive": r"probefahrt|test drive", "service": r"werkstatt|service",
            "contact": r"^kontakt$|^contact$", "financing": r"finanzierung|finantare", "faq": r"faq|hilfe"}


class FakeDealerLlm:
    configured = True
    model = "fake-dealer"

    def __init__(self):
        self.calls = []

    async def structured(self, system, user, model_cls, *, name="answer", effort=None, usage=None):
        self.calls.append(name)
        rows = [m for m in (re.match(r"^(\d+)\. \[(\w+)\] '(.*)' -> (\S*)", ln) for ln in user.splitlines()) if m]
        if model_cls is ModelPicks:
            return ModelPicks(indices=[int(m.group(1)) for m in rows if re.match(r"^/(fahrzeugboerse|stoc)/[^/]+$", m.group(4))])
        picks = {}
        for field in model_cls.model_fields:
            rx = KEYWORDS.get(field)
            hit = next((int(m.group(1)) for m in rows if rx and re.search(rx, m.group(3).lower())), None)
            picks[field] = Pick(index=hit, reason="fake")
        return model_cls(**picks)


def build_de_dealer():
    """German-speaking dealer: none of the URL slugs is known to the keyword rules, and the sitemap is too small to infer VDPs."""
    nav = ("<nav><a href='/fahrzeugboerse'>Gebrauchtwagen</a><a href='/meisterbetrieb'>Werkstatt-Termin</a>"
           "<a href='/termin-vereinbaren'>Probefahrt</a><a href='/geld'>Finanzierung</a><a href='/wir-sind-fuer-sie-da'>Kontakt</a><a href='/ueber-uns'>Über uns</a></nav>")
    routes: dict[str, object] = {
        f"{HOST}/": html_page(f"<!doctype html><html lang='de'><head><title>Autohaus</title>{dealer_jsonld(True)}</head><body>{nav}"
                               "<h1>Autohaus Muster</h1><p>Willkommen. " + "Gebrauchtwagen mit Garantie. " * 15 + "</p></body></html>"),
        f"{HOST}/fahrzeugboerse": html_page("<html><head><title>Gebrauchtwagen</title></head><body><h1>Gebrauchtwagen</h1>" + nav + "".join(f"<a href='/fahrzeugboerse/{s}'>{n}</a>" for s, n, _, _ in CARS) + "</body></html>"),
        f"{HOST}/meisterbetrieb": html_page("<html><body><h1>Werkstatt</h1></body></html>"),
        f"{HOST}/termin-vereinbaren": html_page(f"<html><body><h1>Probefahrt</h1>{FORM}</body></html>"),
        f"{HOST}/geld": html_page("<html><body><h1>Finanzierung</h1></body></html>"),
        f"{HOST}/ueber-uns": html_page("<html><head><title>Über uns</title></head><body><h1>Über uns</h1><p>Seit 1990.</p></body></html>"),
        f"{HOST}/wir-sind-fuer-sie-da": html_page("<html><body><h1>Kontakt</h1><p>Telefon +40 264 000 100, Str. Exemplu 10, Cluj-Napoca</p></body></html>"),
        f"{HOST}/robots.txt": (200, {"content-type": "text/plain"}, "User-agent: *\nAllow: /"),
    }
    for slug, name, price, vin in CARS:
        routes[f"{HOST}/fahrzeugboerse/{slug}"] = html_page(vdp_html(slug, name, price, vin).replace("/test-drive/", "/termin-vereinbaren"))
    web = FakeWeb(routes)
    return web, lambda **kw: SafeFetcher(transport=web.transport, resolver=public_resolver, **kw)


async def scan(build, llm=None):
    web, factory = build()
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input(HOST))
    ctx = await build_context(acq, HOST, "dealer", fetcher, factory, delay_s=0, llm=llm)
    ctx.llm = None  # page discovery is what is under test; the agent journeys are skipped here
    template = load_template("dealer")
    results = [r for r in await run_checks(ctx, template)]
    report = make_report("dealer", template, results)
    await fetcher.aclose()
    return {r.check_id: r for r in results}, report, ctx


@pytest.fixture(autouse=True)
def _clear_cache():
    link_resolver._CACHE.clear()


@pytest.mark.anyio
async def test_llm_finds_the_dealer_pages_that_keyword_rules_miss():
    rules, _, ctx0 = await scan(build_de_dealer, None)
    assert not ctx0.ok_by_role("stock_list") and not ctx0.ok_by_role("test_drive") and rules["inv.vdp_urls"].status == "fail"

    llm = FakeDealerLlm()
    res, report, ctx = await scan(build_de_dealer, llm)
    assert {p.role for p in ctx.pages if p.ok} >= {"home", "stock_list", "test_drive", "service", "contact", "financing", "vdp"}
    assert ctx.link_resolution["stock_list"]["source"] == "llm" and ctx.link_resolution["test_drive"]["source"] == "llm"
    assert ctx.link_resolution["vdp"]["source"] == "llm" and len(ctx.link_resolution["vdp"]["urls"]) >= 3
    assert res["inv.vdp_urls"].status == "pass" and res["act.test_drive"].status == "pass"
    assert llm.calls == ["link_roles", "item_links"]  # roles first, then vehicle pages because the sitemap sample was empty
    assert ctx.role_prefixes["stock_list"] == "/fahrzeugboerse"


@pytest.mark.anyio
async def test_sitemap_sample_stays_rules_first_so_the_inventory_sample_is_representative():
    async def go(llm):
        web, factory = build_site()
        fetcher = factory()
        acq = await acquire_homepage(fetcher, normalize_input(HOST))
        ctx = await build_context(acq, HOST, "dealer", fetcher, factory, delay_s=0, llm=llm)
        await fetcher.aclose()
        return ctx

    plain, with_llm = await go(None), None
    llm = FakeDealerLlm()
    with_llm = await go(llm)
    assert {p.url for p in plain.ok_by_role("vdp")} == {p.url for p in with_llm.ok_by_role("vdp")}  # same sample, LLM or not
    assert with_llm.link_resolution["vdp"]["source"] == "rules" and llm.calls == ["link_roles"]  # no extra call for vehicle pages
    assert with_llm.link_resolution["stock_list"]["source"] == "llm"


class WrongTestDriveLlm(FakeDealerLlm):
    """Answers every role, including a test-drive page that is really the About page (the kind of wrong pick seen on a real dealer)."""

    async def structured(self, system, user, model_cls, *, name="answer", effort=None, usage=None):
        out = await super().structured(system, user, model_cls, name=name, effort=effort)
        if model_cls is not ModelPicks:
            rows = [m for m in (re.match(r"^(\d+)\. \[(\w+)\] '(.*)' -> (\S*)", ln) for ln in user.splitlines()) if m]
            about = next(int(m.group(1)) for m in rows if m.group(4) == "/ueber-uns")
            out.test_drive = Pick(index=about, reason="looks like test drive")
        return out


@pytest.mark.anyio
async def test_a_page_that_does_not_look_like_the_role_is_rejected_and_rules_fill_in():
    from app.services.role_evidence import looks_like
    from app.checks.context import Page

    _, _, ctx = await scan(build_de_dealer, WrongTestDriveLlm())
    td = ctx.link_resolution["test_drive"]
    assert td["source"] == "rules" and "does not look like a test_drive page" in td["rejected"]
    assert not any(p.role == "test_drive" and p.url.endswith("/ueber-uns") for p in ctx.pages)
    assert not any(p.role == "test_drive" for p in ctx.pages)  # no keyword rule knows /termin-vereinbaren: better no page than a wrong one
    # the stock list (the other pick) is still accepted, and the evidence is read from title/headings/URL, not from menu text
    assert ctx.link_resolution["stock_list"]["source"] == "llm"
    menu_only = Page("https://x.example/stock", "test_drive", 200, "<html><head><title>Stock</title></head><body><nav><a href='/t'>Test drive</a></nav><h1>Cars</h1></body></html>")
    assert not looks_like("test_drive", menu_only)
    assert looks_like("test_drive", Page("https://x.example/booking", "test_drive", 200, "<html><head><title>Probefahrt buchen</title></head><body></body></html>"))
    assert looks_like("models_list", menu_only) and looks_like("categories", menu_only)  # roles without a rule always pass
