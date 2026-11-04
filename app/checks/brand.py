"""Brand / importer checks (docs/checks/importer.md): model range, dealer network, central identity. Read-only.

The generic discovery/trust/protocol checks are shared with dealers; this module holds what differs for a brand site
plus four detection checks (configurator, new/used stock, online shop) that are informational (severity INFO, no score).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from app.checks import discovery
from app.checks.actions_trust_protocol import _has_captcha, _td_links
from app.checks.context import Page, ScanContext
from app.checks.identity import DEALER_TYPES, PHONE_RX
from app.checks.util import PRICE_RX, SPEC_WORDS, digits_tail, first_str, jsonld_types, prices_in_text, res, share_status
from app.domain.scoring import CheckResult
from app.services.page_selector import classify_brand_url
from app.services.signals import fold

SCOPE_ROLES = ("models_list", "model", "offers", "locator")
ORG_TYPES = {"Organization", "Corporation", "AutomotiveBusiness", "LocalBusiness", "Brand"}
EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ENGINE_RX = re.compile(r"\b(motoriz\w*|engine\w*|motores?|versiun\w*|versions?|trim\w*)\b")
CONSUMPTION_RX = re.compile(r"\b(wltp|co2|g/km|l/100|consum\w*|emisii|emisiones|autonomi\w*|range)\b")
WARRANTY_RX = re.compile(r"\b(garanti\w*|warranty|garantia)\b")
STREET_RX = re.compile(r"\b(str\.|strada|bulevardul|bd\.|b-dul|calea|sos\.|soseaua|calle|avenida|avda\.|carretera|nr\.)")
CART_RX = re.compile(r"adauga in cos|adauga la cos|add to cart|add to basket|cos de cumparaturi|shopping cart|carrito|finalizeaza comanda|checkout")
SHOP_LINK_RX = re.compile(r"\b(magazin|shop|webshop|e-?shop|tienda|boutique|accesorii|accesorios)\b")
CONFIGURATOR_RX = re.compile(r"configurator|configureaza|configurador|configure your|build your|personalizeaza")
NEW_STOCK_RX = re.compile(r"(masini|autoturisme|vehicule|stoc|stock|coches|vehiculos)\W+(noi|noua|new|nuevos?)|\b(noi|new|nuevos?)\W+(masini|autoturisme|stoc|stock|coches)|pronta livrare|stoc(?:uri)? disponibil|din stoc|disponibil\w*\W+(?:in\W+)?stoc")
USED_STOCK_RX = re.compile(r"rulate|second.?hand|ocazi|usado|segunda mano|\bused\b|approved|certificat|certified")


def _role(ctx: ScanContext, url: str) -> str | None:
    """Role of a URL: keyword rules first, then the URL prefixes learned from the LLM picks (any language/market)."""
    if matched := classify_brand_url(url):
        return matched
    path = urlsplit(url).path.rstrip("/")
    for role in ("locator", "offers"):
        prefix = ctx.role_prefixes.get(role)
        if prefix and (path == prefix or path.startswith(prefix + "/")):
            return role
    prefix = ctx.role_prefixes.get("models_list")
    if prefix and path == prefix:
        return "models_list"
    for key in ("models_list", "model"):
        prefix = ctx.role_prefixes.get(key)
        if prefix and path.startswith(prefix + "/"):
            return "model"
    return None


def _resolved(ctx: ScanContext, role: str) -> str | None:
    entry = ctx.link_resolution.get(role)
    return entry.get("url") if isinstance(entry, dict) else None


def _models(ctx: ScanContext) -> list[Page]:
    return ctx.ok_by_role("model")


# ---------- discovery (brand versions of the shared checks) ----------

async def robots_ai(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    return await discovery.robots_ai(ctx, spec, roles=SCOPE_ROLES, where="model, offer or dealer-locator pages")


async def sitemap(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    if not ctx.sitemap:
        return res(spec, "fail", "No readable sitemap.xml found.", missing=["sitemap"])
    wanted = [e for e in ctx.sitemap if _role(ctx, e.url) in ("model", "models_list", "offers", "locator")]
    if not wanted:
        return res(spec, "fail", f"Sitemap has {len(ctx.sitemap)} URLs but none looks like a model, offer or dealer-locator page.",
                   missing=["model/offer URLs"], details={"urls": len(ctx.sitemap)})
    dates = [d for d in (discovery._parse_date(e.lastmod) for e in wanted) if d]
    newest = max(dates) if dates else None
    details = {"urls": len(ctx.sitemap), "model_offer_urls": len(wanted), "newest_lastmod": newest.isoformat() if newest else None}
    if newest is not None and datetime.now(timezone.utc) - newest < timedelta(days=30):
        return res(spec, "pass", f"{len(wanted)} model/offer URLs in sitemap, newest lastmod within 30 days.", details=details)
    why = "no lastmod on those URLs" if newest is None else "newest lastmod is older than 30 days"
    return res(spec, "warn", f"{len(wanted)} model/offer URLs in sitemap but {why}.", missing=["fresh lastmod"], details=details)


async def llms_txt(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    result = await ctx.fetch_text("/llms.txt", "llms.txt")
    if result is None or result.status != 200 or not result.text.strip() or result.text.lstrip().lower().startswith(("<!doctype", "<html")):
        return res(spec, "fail", "No /llms.txt found.", missing=["/llms.txt"])
    flat = re.findall(r"https?://[^\s)\]>\"']+", result.text) + re.findall(r"\]\((/[^)\s]+)\)", result.text)
    wanted = {"model": "models", "models_list": "models", "offers": "offers", "locator": "dealers"}
    covered = {wanted[x] for x in (_role(ctx, u if u.startswith("http") else ctx.origin + u) for u in flat) if x in wanted}
    if len(covered) >= 2:
        return res(spec, "pass", f"llms.txt links to {', '.join(sorted(covered))}.", found=sorted(covered), snippet=result.text[:300])
    return res(spec, "warn", "llms.txt exists but links to fewer than two of models/offers/dealers.",
               found=sorted(covered), missing=sorted({"models", "offers", "dealers"} - covered), snippet=result.text[:300])


async def no_js(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    models = _models(ctx)
    if not models:
        return res(spec, "na", "No model page was fetched.")
    good = []
    for page in models:
        text = fold(page.text)
        specs = sum(1 for key in ("fuel", "transmission", "power") if SPEC_WORDS[key].search(text))
        specs += bool(CONSUMPTION_RX.search(text))
        if PRICE_RX.search(page.text) and specs >= 2:
            good.append(page.url)
    share = len(good) / len(models)
    return res(spec, share_status(share, 0.7, 0.4),
               f"Starting price and specs are in the raw HTML on {len(good)}/{len(models)} sampled model pages.",
               pages=[p.url for p in models], found=good[:3], missing=[p.url for p in models if p.url not in good][:3],
               details={"share": round(share, 2)})


# ---------- identity ----------

async def schema_org(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    pages = ctx.ok_by_role("home", "contact")
    nodes = [(p.url, n) for p in pages for n in p.jsonld if ORG_TYPES & set(jsonld_types(n))]
    if not nodes:
        return res(spec, "fail", "No Organization/Brand JSON-LD on the homepage or contact page.", missing=["Organization JSON-LD"])
    fields = ["name", "logo", "url", "sameAs", "brand"]
    has_brand_node = any("Brand" in jsonld_types(n) for _, n in nodes)

    def present(node: dict[str, Any]) -> list[str]:
        return [f for f in fields if (node.get(f) and f != "brand") or (f == "brand" and (node.get("brand") or has_brand_node))]

    url, best = max(nodes, key=lambda item: len(present(item[1])))
    got = present(best)
    missing = [f for f in fields if f not in got]
    status = "pass" if len(got) >= 4 else "warn" if len(got) >= 2 else "fail"
    return res(spec, status, f"{'/'.join(jsonld_types(best))} JSON-LD has {len(got)}/5 of {', '.join(fields)}.",
               pages=[url], found=got, missing=missing, snippet=first_str(best.get("name"))[:80],
               details={"type": "/".join(jsonld_types(best))})


def _contact_points(page: Page) -> list[dict[str, Any]]:
    out = []
    for node in page.jsonld:
        contact = node.get("contactPoint")
        out += [c for c in (contact if isinstance(contact, list) else [contact]) if isinstance(c, dict)]
        if "ContactPoint" in jsonld_types(node):
            out.append(node)
    return out


async def contact(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    pages = ctx.ok_by_role("home", "contact")
    if not pages:
        return res(spec, "na", "No homepage/contact content available.")
    cps = [c for p in pages for c in _contact_points(p) if c.get("telephone") or c.get("email")]
    text = " ".join(p.text for p in pages)
    phones = {digits_tail(m) for m in PHONE_RX.findall(text) if len(re.sub(r"\D", "", m)) >= 9}
    emails = set(EMAIL_RX.findall(text))
    in_text = bool(phones or emails)
    found = (["contactPoint JSON-LD"] if cps else []) + (["phone/email in text"] if in_text else [])
    missing = ([] if cps else ["contactPoint JSON-LD"]) + ([] if in_text else ["central phone or email in text"])
    status = "pass" if cps and in_text else "warn" if cps or in_text else "fail"
    return res(spec, status, f"Central contact: {', '.join(found) if found else 'none found'}.",
               pages=[p.url for p in pages], found=found, missing=missing,
               details={"phones": sorted(phones)[:3], "emails": sorted(emails)[:3]})


# ---------- data: models + dealer network ----------

async def model_urls(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    models = _models(ctx)
    discovered = {e.url for e in ctx.sitemap if _role(ctx, e.url) == "model"}
    discovered |= {u for p in ctx.ok_by_role("home", "models_list") for u, _ in p.links if _role(ctx, u) == "model"}
    unique = {p.url.split("?")[0].rstrip("/") for p in models}
    n = len(unique)
    details = {"model_pages_fetched": n, "model_urls_discovered": len(discovered)}
    if n >= 3:
        return res(spec, "pass", f"{n} distinct, crawlable model pages found.", pages=[p.url for p in models],
                   found=sorted(unique)[:4], details=details)
    if n >= 1:
        return res(spec, "warn", f"Only {n} model page(s) could be found and read.", pages=[p.url for p in models],
                   found=sorted(unique), missing=["more model pages with their own URL"], details=details)
    return res(spec, "fail", "No crawlable model pages found (no model URLs in sitemap, homepage or model list).",
               missing=["model page URLs"], details=details)


def _model_fields(page: Page) -> dict[str, bool]:
    folded = fold(page.text)
    return {
        "price_from": bool(prices_in_text(page.text)),
        "engines": bool(ENGINE_RX.search(folded)),
        "power": bool(SPEC_WORDS["power"].search(folded)),
        "consumption_wltp": bool(CONSUMPTION_RX.search(folded)),
        "warranty": bool(WARRANTY_RX.search(folded)),
    }


async def model_fields(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    models = _models(ctx)
    if not models:
        return res(spec, "na", "No model page fetched.")
    per = [_model_fields(p) for p in models]
    names = list(per[0])
    shares = {k: sum(x[k] for x in per) / len(per) for k in names}
    weak = sorted(k for k, v in shares.items() if v < 0.8)
    mean = sum(shares.values()) / len(shares)
    status = "pass" if not weak else "warn" if mean >= 0.5 else "fail"
    return res(spec, status, f"Fields present on >=80% of model pages: {len(names) - len(weak)}/{len(names)}.",
               pages=[p.url for p in models], found=[k for k in names if k not in weak], missing=weak,
               details={"shares": {k: round(v, 2) for k, v in shares.items()}})


async def model_price_readable(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    models = _models(ctx)
    if not models:
        return res(spec, "na", "No model page fetched.")
    with_price = [p for p in models if prices_in_text(p.text)]
    share = len(with_price) / len(models)
    image_hint = []
    for page in models:
        if page in with_price:
            continue
        for img in page.tree.css("img"):
            blob = fold((img.attributes.get("alt") or "") + " " + (img.attributes.get("src") or ""))
            if re.search(r"\b(pret|price|precio|de la|desde|from)\b", blob):
                image_hint.append(page.url)
                break
    return res(spec, share_status(share, 0.9, 0.5),
               f"A price is real text on {len(with_price)}/{len(models)} model pages. (Price-in-image vision check not run yet.)",
               pages=[p.url for p in models], found=[p.url for p in with_price][:3],
               missing=[p.url for p in models if p not in with_price][:3],
               details={"share": round(share, 2), "possible_price_in_image": image_hint[:3], "vision": "deferred"})


async def locator(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    pages = ctx.ok_by_role("locator")
    if not pages:
        if ext := _resolved(ctx, "locator"):
            return res(spec, "warn", f"The dealer locator was found but it is not on this site ({urlsplit(ext).netloc}), so it was not read.",
                       pages=[ext], found=["locator link"], missing=["dealer list readable on this site"], details={"external": True})
        return res(spec, "fail", "No dealer locator page found.", missing=["dealer locator page"])
    page = pages[0]
    text = page.text
    phones = {digits_tail(m) for m in PHONE_RX.findall(text) if len(re.sub(r"\D", "", m)) >= 9}
    phones -= {digits_tail(m) for m in PHONE_RX.findall(ctx.home.text)}  # the site-wide phone (header/footer) is not a dealer entry
    ld = [n for q in pages for n in q.jsonld if DEALER_TYPES & set(jsonld_types(n))]
    streets = len(STREET_RX.findall(fold(text)))
    entries = max(len(phones), len(ld))
    js_map = bool(re.search(r"google\.maps|maps\.googleapis|leaflet|mapbox|openlayers", page.html.lower()))
    details = {"entries_with_phone": len(phones), "dealer_jsonld": len(ld), "address_hints": streets, "js_map": js_map}
    if entries >= 5 and streets >= 3:
        return res(spec, "pass", f"The locator lists {entries} dealers with phone and address in the HTML.", pages=[page.url],
                   found=["dealer list in HTML"], details=details)
    if entries >= 1 or streets >= 3:
        return res(spec, "warn", f"The locator exposes only part of the network in HTML ({entries} dealers with a phone, {streets} addresses).",
                   pages=[page.url], found=["partial list"], missing=["full dealer list in HTML/JSON"], details=details)
    why = "it looks like a JavaScript map without a readable list" if js_map else "no dealer names, phones or addresses are readable"
    return res(spec, "fail", f"A locator page exists but {why}.", pages=[page.url], missing=["dealer list in HTML/JSON"], details=details)


# ---------- actions ----------

def _form_fields(page: Page) -> list[str]:
    out = []
    for form in page.tree.css("form"):
        for field in form.css("input, select, textarea"):
            input_type = (field.attributes.get("type") or "text").lower()
            if field.tag == "input" and input_type in ("hidden", "submit", "button", "image", "search"):
                continue
            out.append(field.attributes.get("name") or field.attributes.get("id") or field.attributes.get("aria-label") or input_type)
    return out


async def test_drive_route(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    pages = ctx.ok_by_role("test_drive")
    links = [(p.url, u) for p in ctx.ok_by_role("home", "models_list", "model", "offers", "configurator") for u in _td_links(p)]
    forms = [(p, _form_fields(p)) for p in pages if p.tree.css("form")]
    if not pages and (ext := _resolved(ctx, "test_drive")):
        links.append((ctx.home.url, ext))
    if not pages and not links:
        return res(spec, "fail", "No test-drive page or link found on the homepage, model pages or offers.", missing=["test-drive entry point"])
    captcha = [p.url for p in pages if _has_captcha(p.html)]
    routes = any(re.search(r"dealer|concesionar|showroom", fold(p.text)) or p.tree.css("select") for p, _ in forms)
    details = {"form_fields": forms[0][1][:12] if forms else [], "routes_to_dealer": routes, "from_links": len(links)}
    if forms and not captcha:
        return res(spec, "pass", f"A test-drive form with {len(forms[0][1])} fields is reachable"
                                 f"{' and lets the visitor pick a dealer' if routes else ''}, with no CAPTCHA.",
                   pages=[p.url for p, _ in forms][:2], found=["test-drive form"], details=details)
    if pages and not forms:
        why = "the page has no form in its HTML (it is probably loaded by JavaScript)" + (" and mentions a CAPTCHA" if captcha else "")
    elif captcha:
        why = "a CAPTCHA protects the form"
    else:
        why = "only a link was found, the form page was not reachable"
    return res(spec, "warn", f"A test-drive entry exists but {why}.", pages=[p.url for p in pages][:2] or [src for src, _ in links][:2],
               found=["test-drive link/page"], missing=["readable form without CAPTCHA"], details=details)


def _all_links(ctx: ScanContext) -> list[tuple[str, str, str]]:
    """(source page, url, folded anchor text + url) for every link of every readable page."""
    return [(p.url, u, fold(t + " " + u)) for p in ctx.pages if p.ok for u, t in p.links]


async def detect_configurator(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    pages = [p.url for p in ctx.ok_by_role("configurator")]
    links = sorted({u for _, u, blob in _all_links(ctx) if CONFIGURATOR_RX.search(blob)})
    found = pages or ([u] if (u := _resolved(ctx, "configurator")) else []) or links
    if not found:
        return res(spec, "na", "No configurator detected on the crawled pages.", details={"detected": False})
    return res(spec, "pass", "A vehicle configurator was detected.", pages=found[:3], found=["configurator"],
               details={"detected": True, "urls": found[:3]})


async def detect_stock(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    links = _all_links(ctx)
    new = sorted(
        {u for _, u, blob in links if NEW_STOCK_RX.search(blob)} | {p.url for p in ctx.ok_by_role("stock_new")}
        | ({_resolved(ctx, "stock_new")} - {None})
    )
    used = sorted(
        {u for _, u, blob in links if USED_STOCK_RX.search(blob)} | {p.url for p in ctx.ok_by_role("stock_used")}
        | ({_resolved(ctx, "stock_used")} - {None})
    )
    details = {"new": bool(new), "used": bool(used), "new_urls": new[:3], "used_urls": used[:3]}
    if not new and not used:
        return res(spec, "na", "No new- or used-car stock section detected.", details=details)
    kinds = " and ".join(k for k, v in (("new", new), ("used", used)) if v)
    found = [f"{k} stock" for k, v in (("new", new), ("used", used)) if v]
    return res(spec, "pass", f"Vehicle stock detected: {kinds} cars.", pages=(new + used)[:3], found=found, details=details)


async def detect_shop(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    links = sorted(
        {u for _, u, blob in _all_links(ctx) if SHOP_LINK_RX.search(blob) and classify_brand_url(u) != "locator"}
        | ({_resolved(ctx, "shop")} - {None})
    )
    shop_pages = ctx.ok_by_role("shop")
    cart = [p.url for p in shop_pages if CART_RX.search(fold(p.html))]
    products = [p.url for p in shop_pages if any("Product" in jsonld_types(n) for n in p.jsonld)]
    if not links and not shop_pages:
        return res(spec, "na", "No online shop detected on the crawled pages.", details={"detected": False})
    kind = "an online shop with cart or checkout" if cart else "a shop or accessories section"
    return res(spec, "pass", f"{kind[0].upper() + kind[1:]} was detected.",
               pages=(cart or [p.url for p in shop_pages] or links)[:3],
               found=["shop link"] + (["cart/checkout markers"] if cart else []) + (["Product JSON-LD"] if products else []),
               details={"detected": True, "cart": bool(cart), "product_jsonld": bool(products), "urls": links[:3]})


REGISTRY = {
    "id.schema_org": schema_org,
    "id.contact": contact,
    "mod.urls": model_urls,
    "mod.fields": model_fields,
    "mod.price_readable": model_price_readable,
    "net.locator": locator,
    "act.test_drive_route": test_drive_route,
    "det.configurator": detect_configurator,
    "det.stock": detect_stock,
    "det.shop": detect_shop,
}
# same check id, brand-specific implementation
OVERRIDES = {"disc.robots_ai": robots_ai, "disc.sitemap": sitemap, "disc.llms_txt": llms_txt, "disc.no_js": no_js}
