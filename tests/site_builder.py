"""Builds a small fake dealer website (all pages as FakeWeb routes) with switches to degrade it."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

from tests.conftest import FakeWeb, html_page, public_resolver

HOST = "a.example"
CARS = [
    ("golf-8-2021", "VW Golf 8", 17900, "WVWZZZAUZLW123456"),
    ("octavia-2020", "Skoda Octavia", 15500, "TMBJJ7NE5L0123456"),
    ("focus-2019", "Ford Focus", 11200, "WF0AXXGCDA1234567"),
    ("corolla-2022", "Toyota Corolla", 21900, "SB1ZS3BE10E123456"),
    ("clio-2021", "Renault Clio", 12900, "VF15RJL0A65123456"),
    ("astra-2020", "Opel Astra", 13400, "W0VBD8EL1L1123456"),
]


def dealer_jsonld(full: bool = True) -> str:
    node = {
        "@context": "https://schema.org", "@type": "AutoDealer", "name": "AutoPrima Cluj",
        "telephone": "+40264000100", "brand": {"@type": "Brand", "name": "Velora"},
        "address": {"@type": "PostalAddress", "streetAddress": "Str. Exemplu 10", "addressLocality": "Cluj-Napoca"},
        "geo": {"@type": "GeoCoordinates", "latitude": 46.77, "longitude": 23.62},
        "openingHours": "Mo-Fr 09:00-18:00",
    }
    if not full:
        node = {"@context": "https://schema.org", "@type": "Organization", "name": "AutoPrima Cluj"}
    return f'<script type="application/ld+json">{json.dumps(node)}</script>'


def vdp_html(slug: str, name: str, price: int, vin: str, *, jsonld=True, price_in_text=True, offer_complete=True,
             js_only=False, price_mismatch=False) -> str:
    if js_only:
        return '<html><head><title>x</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
    ld = ""
    if jsonld:
        offer = {"@type": "Offer", "price": price + (500 if price_mismatch else 0), "priceCurrency": "EUR"}
        if offer_complete:
            offer.update(availability="https://schema.org/InStock", itemCondition="https://schema.org/UsedCondition")
        car = {
            "@context": "https://schema.org", "@type": "Car", "name": name, "vehicleIdentificationNumber": vin,
            "mileageFromOdometer": {"@type": "QuantitativeValue", "value": 45000, "unitCode": "KMT"},
            "vehicleModelDate": "2021", "fuelType": "Petrol", "vehicleTransmission": "Automatic",
            "image": ["/i/1.jpg", "/i/2.jpg", "/i/3.jpg"], "offers": offer,
        }
        ld = f'<script type="application/ld+json">{json.dumps(car)}</script>'
    price_html = f"<p>Preț: {price:,} €</p>".replace(",", ".") if price_in_text else '<img src="/i/pret.png" alt="pret masina">'
    return (
        f"<!doctype html><html lang='ro'><head><title>{name} — AutoPrima</title>{ld}</head><body>"
        f"<h1>{name}</h1>{price_html}<p>45.000 km, an 2021, benzină, cutie automată, 150 CP</p><p>VIN {vin}</p>"
        "<img src='/i/1.jpg'><img src='/i/2.jpg'><img src='/i/3.jpg'>"
        "<a href='/test-drive/'>Programează test drive</a></body></html>"
    )


FORM = (
    "<form action='/test-drive/send' method='post'>"
    "<label for='n'>Nume</label><input id='n' name='name' autocomplete='name' required>"
    "<label for='e'>Email</label><input id='e' name='email' type='email' autocomplete='email' required>"
    "<label for='t'>Telefon</label><input id='t' name='phone' type='tel' autocomplete='tel'>"
    "<button type='submit'>Trimite</button></form>"
)
BAD_FORM = "<form><input name='x'><input type='email' name='email'><input name='y'></form>"


def build_site(
    *, robots: str = "User-agent: *\nAllow: /", sitemap_fresh=True, llms=True, card=True, full_ld=True,
    vdp_kwargs: dict | None = None, form: str = FORM, captcha=False, test_drive_from_vdp=True,
    block_ua: str | None = None, sitemap=True, http_redirect=True,
) -> tuple[FakeWeb, callable]:
    vk = vdp_kwargs or {}
    routes: dict[str, object] = {}
    nav = "<nav><a href='/stoc/'>Stoc</a><a href='/service/'>Programare service</a><a href='/contact/'>Contact</a>"
    nav += "" if test_drive_from_vdp else "<a href='/test-drive/'>Test drive</a>"
    nav += "</nav>"
    routes[f"{HOST}/"] = html_page(
        f"<!doctype html><html lang='ro'><head><title>AutoPrima Cluj — dealer autorizat</title>{dealer_jsonld(full_ld)}</head>"
        f"<body>{nav}<h1>AutoPrima Cluj</h1><p>Dealer auto autorizat. Telefon +40 264 000 100. Str. Exemplu 10, Cluj-Napoca. "
        + "Masini rulate verificate, finantare, service. " * 12 + "</p></body></html>"
    )
    links = "".join(f"<li><a href='/stoc/{s}'>{n}</a></li>" for s, n, _, _ in CARS)
    routes[f"{HOST}/stoc/"] = html_page(f"<html><body>{nav}<h1>Stoc</h1><ul>{links}</ul></body></html>")
    for slug, name, price, vin in CARS:
        page = vdp_html(slug, name, price, vin, **vk)
        if not test_drive_from_vdp:
            page = page.replace("<a href='/test-drive/'>Programează test drive</a>", "")
        routes[f"{HOST}/stoc/{slug}"] = html_page(page)
    routes[f"{HOST}/service/"] = html_page(f"<html><body>{nav}<h1>Service auto</h1></body></html>")
    extra = "<div class='g-recaptcha' data-sitekey='x'></div>" if captcha else ""
    routes[f"{HOST}/test-drive/"] = html_page(f"<html><body><h1>Test drive</h1>{form}{extra}</body></html>")
    routes[f"{HOST}/contact/"] = html_page(
        "<html><body><h1>Contact AutoPrima Cluj</h1><p>Telefon +40 264 000 100, Str. Exemplu 10, Cluj-Napoca</p></body></html>"
    )
    routes[f"{HOST}/robots.txt"] = (200, {"content-type": "text/plain"}, robots + ("\nSitemap: https://a.example/sitemap.xml" if sitemap else ""))
    if sitemap:
        day = datetime.now(timezone.utc) - timedelta(days=1 if sitemap_fresh else 60)
        urls = "".join(
            f"<url><loc>https://{HOST}/stoc/{s}</loc><lastmod>{day.date().isoformat()}</lastmod></url>" for s, *_ in CARS
        )
        routes[f"{HOST}/sitemap.xml"] = (200, {"content-type": "application/xml"}, f"<urlset>{urls}</urlset>")
    if llms:
        routes[f"{HOST}/llms.txt"] = (
            200, {"content-type": "text/markdown"},
            "# AutoPrima\n- [Stoc](https://a.example/stoc/)\n- [Service](https://a.example/service/)\n- [Contact](https://a.example/contact/)\n",
        )
    if card:
        routes[f"{HOST}/.well-known/agent-card.json"] = (
            200, {"content-type": "application/json"},
            json.dumps({"name": "AutoPrima", "capabilities": {"extensions": [{"uri": "https://autoagentprotocol.org/extensions/aap/v3.0", "required": True}]}}),
        )
    web = FakeWeb(routes)
    inner = web.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        ua = request.headers.get("user-agent", "")
        if block_ua and block_ua in ua:
            web.requests.append(request)
            return httpx.Response(403, text="blocked")
        if request.url.scheme == "http" and request.url.host == HOST and request.url.path == "/":
            web.requests.append(request)
            if http_redirect:
                return httpx.Response(301, headers={"location": f"https://{HOST}/"})
            return html_page("<html><body>plain http</body></html>")
        return inner(request)

    web.handler = handler  # type: ignore[attr-defined]
    return web, lambda **kw: __import__("app.services.crawler", fromlist=["SafeFetcher"]).SafeFetcher(
        transport=httpx.MockTransport(handler), resolver=public_resolver, **kw
    )
