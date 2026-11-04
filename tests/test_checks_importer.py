"""Brand / importer rules on a small synthetic brand website (all pages are FakeWeb routes)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.checks.context import build_context
from app.checks.engine import load_template, make_report, run_checks
from app.services.crawler import SafeFetcher, acquire_homepage
from app.services.page_selector import classify_brand_url
from app.services.url_normalizer import normalize_input
from tests.conftest import FakeWeb, html_page, public_resolver

HOST = "b.example"
MODELS = ["alfa", "beta", "omega", "delta"]
TD_FORM = (
    "<form action='/test-drive/send' method='post'><label for='n'>Nume</label><input id='n' name='name' autocomplete='name'>"
    "<label for='d'>Dealer</label><select id='d' name='dealer'><option>Cluj</option></select>"
    "<button type='submit'>Trimite</button></form>"
)
ORG = {"@context": "https://schema.org", "@type": "Organization", "name": "Velora Romania", "url": f"https://{HOST}",
       "logo": f"https://{HOST}/logo.png", "sameAs": ["https://facebook.com/velora"], "brand": {"@type": "Brand", "name": "Velora"},
       "contactPoint": {"@type": "ContactPoint", "telephone": "+40 21 000 1111", "contactType": "customer service"}}


def model_html(name: str) -> str:
    return (f"<!doctype html><html lang='ro'><head><title>Velora {name}</title></head><body><h1>Velora {name}</h1>"
            f"<p>de la 18.990 € cu TVA. Motorizari benzina si hibrid, 110 CP, consum WLTP 5,2 l/100 km, CO2 118 g/km. "
            f"Garantie 5 ani.</p><a href='/test-drive/'>Test drive</a></body></html>")


def dealers_html(n: int = 6) -> str:
    rows = "".join(f"<li>Dealer Velora Oras{i}, Str. Exemplu nr. {i}, telefon 0264 000 1{i:02d}</li>" for i in range(n))
    return f"<html><body><h1>Reteaua de dealeri</h1><ul>{rows}</ul></body></html>"


def build_brand(*, locator="list", form=True, captcha=False, org=True, shop=True, used=True, prices=True, llms=True):
    routes: dict[str, object] = {}
    nav = ("<nav><a href='/modele/'>Modele</a><a href='/oferte/'>Oferte</a><a href='/dealeri/'>Dealeri</a>"
           "<a href='/test-drive/'>Test drive</a><a href='/configurator/'>Configurator</a><a href='/contact/'>Contact</a>"
           "<a href='/masini-noi/'>Mașini noi</a>"
           + ("<a href='/masini-rulate/'>Mașini rulate</a>" if used else "")
           + ("<a href='/magazin/'>Magazin online</a>" if shop else "") + "</nav>")
    ld = f'<script type="application/ld+json">{json.dumps(ORG)}</script>' if org else ""
    routes[f"{HOST}/"] = html_page(f"<!doctype html><html lang='ro'><head><title>Velora Romania</title>{ld}</head><body>{nav}"
                                    f"<h1>Velora Romania</h1><p>Importator oficial. Telefon +40 21 000 1111, office@velora.example. " + "Gama completa. " * 20 + "</p></body></html>")
    routes[f"{HOST}/modele/"] = html_page("<html><body>" + nav + "".join(f"<a href='/modele/{m}'>{m}</a>" for m in MODELS) + "</body></html>")
    for m in MODELS:
        body = model_html(m) if prices else f"<html><body><h1>{m}</h1><img src='/i/pret.png' alt='pret de la'></body></html>"
        routes[f"{HOST}/modele/{m}"] = html_page(body)
    routes[f"{HOST}/oferte/"] = html_page("<html><body><h1>Oferte</h1></body></html>")
    if locator == "list":
        routes[f"{HOST}/dealeri/"] = html_page(dealers_html())
    elif locator == "map":
        routes[f"{HOST}/dealeri/"] = html_page("<html><body><div id='map'></div><script src='https://maps.googleapis.com/maps/api/js'></script></body></html>")
    routes[f"{HOST}/test-drive/"] = html_page("<html><body><h1>Test drive</h1>" + (TD_FORM if form else "<div id='app'></div>")
                                               + ("<div class='g-recaptcha' data-sitekey='x'></div>" if captcha else "") + "</body></html>")
    routes[f"{HOST}/configurator/"] = html_page("<html><body><h1>Configurator</h1></body></html>")
    routes[f"{HOST}/contact/"] = html_page("<html><body><h1>Contact</h1><p>Telefon +40 21 000 1111</p></body></html>")
    routes[f"{HOST}/masini-noi/"] = html_page("<html><body><h1>Stoc masini noi</h1></body></html>")
    if used:
        routes[f"{HOST}/masini-rulate/"] = html_page("<html><body><h1>Masini rulate</h1></body></html>")
    if shop:
        routes[f"{HOST}/magazin/"] = html_page("<html><body><h1>Magazin</h1><button>Adauga in cos</button></body></html>")
    day = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    urls = "".join(f"<url><loc>https://{HOST}/modele/{m}</loc><lastmod>{day}</lastmod></url>" for m in MODELS)
    routes[f"{HOST}/sitemap.xml"] = (200, {"content-type": "application/xml"}, f"<urlset>{urls}</urlset>")
    routes[f"{HOST}/robots.txt"] = (200, {"content-type": "text/plain"}, f"User-agent: *\nAllow: /\nSitemap: https://{HOST}/sitemap.xml")
    if llms:
        routes[f"{HOST}/llms.txt"] = (200, {"content-type": "text/markdown"},
                                      f"# Velora\n- [Modele](https://{HOST}/modele/)\n- [Oferte](https://{HOST}/oferte/)\n- [Dealeri](https://{HOST}/dealeri/)\n")
    web = FakeWeb(routes)
    inner = web.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.scheme == "http" and request.url.path == "/":
            web.requests.append(request)
            return httpx.Response(301, headers={"location": f"https://{HOST}/"})
        return inner(request)

    return web, lambda **kw: SafeFetcher(transport=httpx.MockTransport(handler), resolver=public_resolver, **kw)


async def scan(**kw):
    web, factory = build_brand(**kw)
    fetcher = factory()
    acq = await acquire_homepage(fetcher, normalize_input(HOST))
    ctx = await build_context(acq, HOST, "importer", fetcher, factory, delay_s=0)
    template = load_template("importer")
    results = await run_checks(ctx, template)
    report = make_report("importer", template, results)
    await fetcher.aclose()
    return {r.check_id: r for r in results}, report, web, ctx


def st(res, cid):
    return res[cid].status


def test_brand_url_roles():
    c = classify_brand_url
    assert c("https://x.ro/modele/") == "models_list" and c("https://x.ro/modele/sandero") == "model"
    assert c("https://x.ro/new-cars/aygo-x") == "model" and c("https://x.ro/new-cars") == "models_list"
    assert c("https://x.ro/modele-si-configurator/toate-modelele") == "models_list"
    assert c("https://x.ro/modele-vechi/logan.html") is None  # discontinued models are not the current range
    assert c("https://x.ro/new-cars/aygo-x/build") == "configurator" and c("https://x.ro/configurator-modele.html") == "configurator"
    assert c("https://x.ro/reteaua-dacia.html") == "locator" and c("https://x.ro/dealers") == "locator"
    assert c("https://x.ro/forms/test-drive") == "test_drive" and c("https://x.ro/oferte") == "offers"
    assert c("https://x.ro/rulate-certificate") == "stock_used" and c("https://x.ro/masini-noi/") == "stock_new"
    assert c("https://x.ro/legal") is None and c("https://x.ro/") is None


@pytest.mark.anyio
async def test_good_brand_site_passes_and_stays_read_only():
    res, report, web, _ = await scan()
    bad = {k: (v.status, v.summary) for k, v in res.items() if v.status not in ("pass", "na") and k not in ("proto.aap_card", "ux.j_dealer")}
    assert bad == {}, bad
    assert st(res, "proto.aap_card") == "fail" and res["proto.aap_card"].not_adopted
    assert st(res, "ux.j_dealer") == "skipped"  # no LLM in this test: the journey is skipped, not failed
    assert report.layers[5].layer == "agent_ux" and report.layers[5].score is None  # no applicable check: weight renormalised
    assert {r.method for r in web.requests} == {"GET"}
    assert "test-drive/send" not in {r.url.path for r in web.requests}


@pytest.mark.anyio
async def test_detection_checks_are_informational():
    res, report, *_ = await scan()
    for cid in ("det.configurator", "det.stock", "det.shop"):
        assert res[cid].severity == "INFO" and st(res, cid) == "pass"
    assert res["det.stock"].details["new"] and res["det.stock"].details["used"]
    assert res["det.shop"].details["cart"]
    res2, report2, *_ = await scan(shop=False, used=False)
    assert st(res2, "det.shop") == "na" and res2["det.stock"].details["used"] is False and res2["det.stock"].details["new"]
    assert report.readiness == report2.readiness  # INFO checks never change the score
    assert all(r.severity != "INFO" or r.status in ("pass", "na") for r in report.results)


@pytest.mark.anyio
async def test_locator_variants():
    assert st((await scan(locator="list"))[0], "net.locator") == "pass"
    assert st((await scan(locator="map"))[0], "net.locator") == "fail"
    assert "JavaScript map" in (await scan(locator="map"))[0]["net.locator"].summary
    assert st((await scan(locator="none"))[0], "net.locator") == "fail"


@pytest.mark.anyio
async def test_test_drive_form_and_captcha():
    assert res_ok(await scan(form=True), "act.test_drive_route", "pass")
    r = (await scan(form=True, captcha=True))[0]["act.test_drive_route"]
    assert r.status == "warn" and "CAPTCHA" in r.summary
    r = (await scan(form=False))[0]["act.test_drive_route"]
    assert r.status == "warn" and "JavaScript" in r.summary


def res_ok(out, cid, status):
    return out[0][cid].status == status


@pytest.mark.anyio
async def test_identity_and_model_checks_degrade():
    res = (await scan(org=False))[0]
    assert st(res, "id.schema_org") == "fail"
    res = (await scan(prices=False))[0]
    assert st(res, "mod.price_readable") == "fail" and res["mod.price_readable"].details["possible_price_in_image"]
    res = (await scan(llms=False))[0]
    assert st(res, "disc.llms_txt") == "fail"
    res = (await scan())[0]
    assert res["mod.urls"].details["model_pages_fetched"] == 4 and st(res, "mod.fields") == "pass"


@pytest.mark.anyio
async def test_importer_scan_runs_through_the_api_and_has_no_dealer_fixes():
    from fastapi.testclient import TestClient
    from app.jobs.scan_pipeline import Deps
    from app.main import create_app
    from app.repo.db import make_engine

    web, factory = build_brand()
    app = create_app(engine=make_engine("sqlite:///:memory:"), deps=Deps(fetcher_factory=factory, llm_factory=lambda: None, renderer=None, run_checks=True))
    with TestClient(app) as c:
        sid = c.post("/api/scans", json={"url": HOST, "force": True}).json()["scan_id"]
        s = c.get(f"/api/scans/{sid}").json()
        if s["status"] == "needs_confirmation":
            c.post(f"/api/scans/{sid}/confirm", json={"type": "importer"})
            s = c.get(f"/api/scans/{sid}").json()
        assert s["status"] == "completed" and s["report"]["site_type"] == "importer", s
        assert c.get(f"/api/scans/{sid}/fixes").json()["fixes"] == []
        assert s["fixes_count"] == 0  # the UI hides "Review fixes" for this scan
        ai = s["report"]["coverage"]["ai"]  # nothing is implied: no Muse in this test, so nothing is listed as used
        assert ai["provider"] == "Meta Model API" and ai["model"] and ai["used_for"] == []
