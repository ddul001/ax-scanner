"""E-commerce rules on a small synthetic online shop (all pages are FakeWeb routes), with a scripted Muse stand-in."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.checks.context import build_context
from app.checks.engine import load_template, make_report, run_checks
from app.journey.agent import AgentStep
from app.journey.tasks import shop_budget, shop_task
from app.services.crawler import SafeFetcher, acquire_homepage
from app.services.link_resolver import ModelPicks, Pick
from app.services.page_selector import classify_shop_url
from app.services.url_normalizer import normalize_input
from tests.conftest import FakeWeb, html_page, public_resolver
from tests.test_journey import finish, link

HOST = "s.example"
PRODUCTS = [("anvelope-a-1001", "Anvelope Alfa 205/55 R16", 420), ("anvelope-b-1002", "Anvelope Beta 195/65 R15", 380),
            ("anvelope-c-1003", "Anvelope Gamma 225/45 R17", 510), ("anvelope-d-1004", "Anvelope Delta 215/60 R16", 465)]
DELIVERY = "Livrarea se face in 2-3 zile lucratoare, gratuit pentru comenzi peste 300 RON."
RETURNS = "Poti returna produsul in 14 zile de la primire, costul transportului de retur fiind suportat de client."
WARRANTY = "Toate produsele au garantie de 24 de luni conform legii."
ORG = {"@context": "https://schema.org", "@type": "OnlineStore", "name": "Magazin Test", "url": f"https://{HOST}",
       "logo": f"https://{HOST}/l.png", "contactPoint": {"@type": "ContactPoint", "telephone": "+40 21 000 1111"}}


def product_html(slug, name, price, *, jsonld=True, cart=True, quote=False, mismatch=False, login_wall=False):
    ld = ""
    if jsonld:
        node = {"@context": "https://schema.org", "@type": "Product", "name": name, "image": "/i/1.jpg", "brand": {"@type": "Brand", "name": "Marca"},
                "sku": slug, "offers": {"@type": "Offer", "price": price + (50 if mismatch else 0), "priceCurrency": "RON",
                                         "availability": "https://schema.org/InStock"}}
        ld = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    buy = "<button>Adauga in cos</button>" if cart else ("<a href='/contact/'>Cere oferta</a>" if quote else "")
    wall = "<p>Autentifica-te pentru a cumpara acest produs.</p>" if login_wall else ""
    return (f"<!doctype html><html lang='ro'><head><title>{name}</title>{ld}</head><body><h1>{name}</h1>"
            f"<p>Pret: {price} RON. In stoc.</p>{buy}{wall}</body></html>")


def build_shop(*, cart=True, quote=False, jsonld=True, mismatch=False, policies=True, checkout="guest", llms=True, mcp=False, login_wall=False):
    nav = ("<nav><a href='/produse/'>Produse</a><a href='/oferte/'>Oferte</a><a href='/livrare/'>Livrare</a><a href='/retur/'>Retur</a>"
           "<a href='/garantie/'>Garantie</a><a href='/contact/'>Contact</a><a href='/cos/'>Cos</a></nav>")
    ld = f'<script type="application/ld+json">{json.dumps(ORG)}</script>'
    routes: dict[str, object] = {
        f"{HOST}/": html_page(f"<!doctype html><html lang='ro'><head><title>Magazin Test</title>{ld}</head><body>{nav}<h1>Magazin Test</h1><p>"
                               + "Anvelope si roti. " * 25 + "</p></body></html>"),
        f"{HOST}/produse/": html_page("<html><body>" + nav + "".join(f"<a href='/produse/{s}'>Vezi detalii</a>" for s, _, _ in PRODUCTS) + "</body></html>"),
        f"{HOST}/oferte/": html_page("<html><body><h1>Oferte</h1></body></html>"),
        f"{HOST}/contact/": html_page("<html><body><h1>Contact</h1><p>Telefon +40 21 000 1111</p></body></html>"),
        f"{HOST}/robots.txt": (200, {"content-type": "text/plain"}, f"User-agent: *\nAllow: /\nSitemap: https://{HOST}/sitemap.xml"),
    }
    for slug, name, price in PRODUCTS:
        routes[f"{HOST}/produse/{slug}"] = html_page(product_html(slug, name, price, jsonld=jsonld, cart=cart, quote=quote, mismatch=mismatch, login_wall=login_wall))
    if policies:
        routes[f"{HOST}/livrare/"] = html_page(f"<html><body><h1>Livrare</h1><p>{DELIVERY}</p></body></html>")
        routes[f"{HOST}/retur/"] = html_page(f"<html><body><h1>Retur</h1><p>{RETURNS}</p></body></html>")
        routes[f"{HOST}/garantie/"] = html_page(f"<html><body><h1>Garantie</h1><p>{WARRANTY}</p></body></html>")
    if checkout == "guest":
        routes[f"{HOST}/cos/"] = html_page("<html><body><h1>Cos de cumparaturi</h1><a href='/checkout/'>Finalizeaza comanda</a></body></html>")
        routes[f"{HOST}/checkout/"] = html_page("<html><body><h1>Checkout</h1><p>Continua ca vizitator, fara cont.</p></body></html>")
    elif checkout == "login":
        routes[f"{HOST}/cos/"] = html_page("<html><body><h1>Cos</h1><p>Autentificare</p><form><input name='e'><input type='password' name='p'>"
                                            "<label>Parola</label></form></body></html>")
    day = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    urls = "".join(f"<url><loc>https://{HOST}/produse/{s}</loc><lastmod>{day}</lastmod></url>" for s, _, _ in PRODUCTS)
    routes[f"{HOST}/sitemap.xml"] = (200, {"content-type": "application/xml"}, f"<urlset>{urls}</urlset>")
    if llms:
        routes[f"{HOST}/llms.txt"] = (200, {"content-type": "text/markdown"},
                                      f"# Magazin\n- [Produse](https://{HOST}/produse/)\n- [Livrare](https://{HOST}/livrare/)\n- [Contact](https://{HOST}/contact/)\n")
    if mcp:
        routes[f"{HOST}/.well-known/ucp"] = (200, {"content-type": "application/json"}, json.dumps({"version": "1", "name": "Magazin"}))
    web = FakeWeb(routes)
    inner = web.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.scheme == "http" and request.url.path == "/":
            web.requests.append(request)
            return httpx.Response(301, headers={"location": f"https://{HOST}/"})
        return inner(request)

    return web, lambda **kw: SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver, **kw)


KEYWORDS = {"categories": r"^produse$", "offers": r"^oferte$", "cart": r"^cos$", "shipping": r"^livrare$", "returns": r"^retur$",
            "warranty": r"^garantie$", "contact": r"^contact$"}


class FakeShopLlm:
    configured = True
    model = "fake-shop"

    def __init__(self, journey=None, policy_quotes=(DELIVERY, RETURNS, WARRANTY)):
        self.journey, self.policy_quotes, self.calls = journey, policy_quotes, 0

    async def structured(self, system, user, model_cls, *, name="answer", effort=None, usage=None):
        self.calls += 1
        from app.checks.shop import Policies, Policy
        if model_cls is AgentStep:
            data = json.loads(user)
            return self.journey(data["current_page"], data["step"], data)
        if model_cls is Policies:
            d, r, w = self.policy_quotes
            return Policies(delivery=Policy(stated=True, has_concrete_terms=True, quote=d), returns=Policy(stated=True, has_concrete_terms=True, quote=r),
                            warranty=Policy(stated=True, has_concrete_terms=True, quote=w))
        rows = [m for m in (re.match(r"^(\d+)\. \[(\w+)\] '(.*)' -> (\S*)", ln) for ln in user.splitlines()) if m]
        if model_cls is ModelPicks:
            return ModelPicks(indices=[int(m.group(1)) for m in rows if m.group(4).startswith("/produse/") and m.group(4).count("/") == 2])
        picks = {}
        for field in model_cls.model_fields:
            rx = KEYWORDS.get(field)
            hit = next((int(m.group(1)) for m in rows if rx and re.search(rx, m.group(3).lower())), None)
            picks[field] = Pick(index=hit, reason="fake")
        return model_cls(**picks)


def good_journey(page, step, _):
    if step == 1:
        return AgentStep(thought="catalog", action="open_link", link_index=link(page, "/produse/"))
    if step == 2:
        return AgentStep(thought="a product", action="open_link", link_index=link(page, "anvelope-b-1002"))
    return finish(found=True, url=page["url"], title="Anvelope Beta 195/65 R15", price=380, currency="RON", availability="In stoc")


async def scan(llm=None, **site):
    web, factory = build_shop(**site)
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input(HOST))
    ctx = await build_context(acq, HOST, "ecommerce", fetcher, factory, delay_s=0, llm=llm)
    ctx.llm = llm
    template = load_template("ecommerce")
    results = await run_checks(ctx, template)
    report = make_report("ecommerce", template, results)
    await fetcher.aclose()
    return {r.check_id: r for r in results}, report, web, ctx


def st(res, cid):
    return res[cid].status


def test_shop_url_roles():
    c = classify_shop_url
    assert c("https://x.ro/cos") == "cart" and c("https://x.ro/finalizare-comanda") == "checkout" and c("https://x.ro/livrare") == "shipping"
    assert c("https://x.ro/politica-de-retur") is None and c("https://x.ro/retur") == "returns" and c("https://x.ro/garantie") == "warranty"
    assert c("https://x.ro/produse/") == "categories" and c("https://x.ro/produse/anvelope-a-1001") == "product"
    assert c("https://x.ro/") is None and c("https://x.ro/blog/ceva") is None


@pytest.mark.anyio
async def test_good_shop_passes_end_to_end_with_the_agent_journey():
    llm = FakeShopLlm(journey=good_journey)
    res, report, web, ctx = await scan(llm)
    bad = {k: (v.status, v.summary) for k, v in res.items() if v.status != "pass" and k not in ("proto.mcp_public", "act.webmcp")}
    assert bad == {}, bad
    assert res["proto.mcp_public"].status == "fail" and res["proto.mcp_public"].not_adopted
    assert ctx.link_resolution["product"]["source"] == "llm" and len(ctx.link_resolution["product"]["urls"]) == 4
    assert res["act.add_to_cart"].details["executed"] is False and res["act.guest_checkout"].details["executed"] is False
    assert {r.method for r in web.requests} == {"GET"}  # never adds to a cart, never submits anything
    assert report.layers[5].layer == "agent_ux" and report.readiness > 80


@pytest.mark.anyio
async def test_catalog_only_shop_without_cart_or_structured_data_scores_low():
    res, report, *_ = await scan(FakeShopLlm(journey=good_journey), cart=False, quote=True, jsonld=False, policies=False, checkout="none", llms=False)
    assert st(res, "act.add_to_cart") == "fail" and "quote" in res["act.add_to_cart"].summary
    assert st(res, "act.guest_checkout") == "na" and st(res, "prod.schema_product") == "fail"
    assert st(res, "trust.policies_text") == "fail" and st(res, "disc.llms_txt") == "fail"
    assert report.readiness < 60


@pytest.mark.anyio
async def test_policy_claims_must_exist_on_the_page():
    res, *_ = await scan(FakeShopLlm(journey=good_journey, policy_quotes=("Livrare gratuita in 1 ora oriunde in lume.", RETURNS, "Garantie pe viata.")))
    r = res["trust.policies_text"]
    assert r.status == "warn" and r.found == ["returns"] and set(r.missing) == {"delivery", "warranty"}  # invented quotes are discarded
    res, *_ = await scan(None)
    assert st(res, "trust.policies_text") == "skipped"


@pytest.mark.anyio
async def test_login_wall_price_mismatch_and_mcp_declared():
    res, *_ = await scan(FakeShopLlm(journey=good_journey), login_wall=True, checkout="login", mismatch=True, mcp=True)
    assert st(res, "act.add_to_cart") == "warn" and st(res, "act.guest_checkout") == "fail"
    assert st(res, "prod.price_consistency") == "fail" and st(res, "proto.mcp_public") == "pass"


@pytest.mark.anyio
async def test_shop_journey_verifies_the_answer_on_the_page():
    def liar(page, step, _):
        if step == 1:
            return AgentStep(thought="catalog", action="open_link", link_index=link(page, "/produse/"))
        if step == 2:
            return AgentStep(thought="a product", action="open_link", link_index=link(page, "anvelope-b-1002"))
        return finish(found=True, url=page["url"], title="Anvelope Beta 195/65 R15", price=99, currency="RON", availability="In stoc")

    r = (await scan(FakeShopLlm(journey=liar)))[0]["ux.j_find"]
    assert r.status == "fail" and r.details["verification"]["checks"]["price_matches"] is False
    r = (await scan(FakeShopLlm(journey=lambda p, s, u: finish(found=False, notes="nothing"))))[0]["ux.j_find"]
    assert r.status == "fail"


def test_shop_task_is_grounded_in_what_the_shop_sells():
    assert shop_budget([380, 465]) == 600 and shop_budget([40]) == 60 and shop_budget([]) is None
    t = shop_task(600, "RON", "Anvelope Beta 195/65 R15")
    assert "less than 600 RON" in t and "Anvelope Beta" in t and "do NOT submit" in t and "Do NOT add anything to a cart" in t
