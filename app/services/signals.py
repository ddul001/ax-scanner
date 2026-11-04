"""Deterministic signal extraction (pure functions over HTML + sitemap URLs)."""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.domain.models import Signals

JS_SHELL_MIN_TEXT = 500

AUTO_SCHEMA = {"AutoDealer", "AutomotiveBusiness", "AutoRepair", "MotorcycleDealer", "AutoPartsStore"}
VEHICLE_SCHEMA = {"Car", "Vehicle", "Motorcycle", "MotorizedBicycle", "BusOrCoach"}

URL_GROUPS: dict[str, tuple[str, ...]] = {
    "stock": (
        "stoc", "stock", "vanzari-auto", "masini", "autoturisme", "inventory", "vehicule", "ocazii", "rulate",
        "vehiculos", "coches", "segunda-mano", "used-cars", "new-cars", "second-hand",
    ),
    "models": ("modele", "model", "models", "gama", "modelos", "range", "gamma"),
    "products": ("produs", "produse", "product", "products", "producto", "productos", "piese", "accesorii"),
    "listings": ("anunt", "anunturi", "anuncio", "anuncios", "listing", "listings", "ad", "ads", "oferta"),
    "dealers": (
        "dealeri", "dealers", "retea", "reteaua-de-dealeri", "concesionarios", "dealer-locator",
        "find-a-dealer", "locator",
    ),
}

_CART_PATH = re.compile(
    r"(^|/)(cart|cos|checkout|basket|carrito|cesta|cos-de-cumparaturi|shopping-cart)(/|$)"
)
_CART_TEXT = (
    "adauga in cos", "add to cart", "add to basket", "anadir al carrito", "cosul meu",
    "cos de cumparaturi", "shopping cart", "mi carrito",
)
_CART_ATTR = ("add-to-cart", "add_to_cart", "addtocart", "btn-cart")
_SERVICE_TEXT = re.compile(
    r"programare service|programeaza service|service auto|atelier|taller|cita (previa )?taller"
    r"|(?<!customer )(?<!client )\bservice\b"
)
_SERVICE_SEGS = {"service", "atelier", "taller", "programare-service", "service-auto"}
_LOCATOR_TEXT = re.compile(
    r"\b(dealeri|dealers|concesionarios|find a dealer|dealer locator|gaseste (un )?dealer"
    r"|encuentra (tu )?concesionario)\b"
)
_LOCATOR_SEGS = {"dealeri", "dealers", "concesionarios", "retea-dealeri", "dealer-locator", "find-a-dealer"}
_CONFIG_TEXT = re.compile(r"configurator|configureaza|configure your|configurador|build your")
_TEST_DRIVE = re.compile(r"test[ -]?drive|prueba de conduccion")
_POST_LISTING = re.compile(
    r"(adauga|adaugati|posteaza|publica|depune)\w* (un |o |prima ta |primul tau )?anunt|\bpost (an |your )?ad\b"
    r"|sell your (car|vehicle)|vinde(-ti)? (masina|autoturismul)|vende tu coche|publicar (un )?anuncio|poner anuncio"
)
_SELLERS = re.compile(
    r"\b(vanzator\w*|particular\w*|persoane fizice|profesionisti|sellers?|private sellers?|vendedor\w*)\b"
)
_MAKES = (
    "abarth alfa aston audi bentley bmw bugatti byd cadillac chevrolet chrysler citroen cupra dacia daewoo dodge "
    "ferrari fiat ford honda hyundai infiniti jaguar jeep kia lamborghini lancia lexus maserati mazda mercedes "
    "mini mitsubishi nissan opel peugeot porsche renault rover seat skoda smart subaru suzuki tesla toyota "
    "volkswagen volvo"
).split()
_MAKES_RX = re.compile(r"\b(" + "|".join(sorted(_MAKES, key=len, reverse=True)) + r")\b")
_FINANCE_WORDS = re.compile(
    r"\b(leasing|renting|credit\w*|imprumut\w*|finantar\w+|banca|bank|banking|ifn|dobanda|dae|prestamo\w*"
    r"|financiacion|financiaci\w+|hipoteca|asigurar\w+|seguros?|conturi|cuentas?|carduri|tarjetas?)\b"
)
_FINANCE_LEGAL = re.compile(
    r"\b(ifn|bnr|banca nationala|banco de espana|autorizat\w* de|supraveghe\w+|supervis\w+|tae|dae|"
    r"institutie de credit|entidad de credito)\b"
)
_COOKIE_HINT = re.compile(r"cookie|consent|onetrust|cookiebot|gdpr|cc-window|cmp-|privacy-banner")
_VIN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.I)
_KM = re.compile(r"\b\d{1,3}(?:[.,\s]\d{3})*\s?km\b")
_PRICE = re.compile(r"(?:\d[\d.\s,]*\s?(?:€|eur\b|euro\b|lei\b|ron\b))|(?:€\s?\d)")
_PRICE_FROM = re.compile(
    r"(?:de la|from|desde|starting at|incepand de la|a partir de)\s*(?:€\s*)?\d[\d.\s,]*\s*(?:€|eur|euro|lei|ron)?"
)
_SHIP_RETURN = re.compile(r"\b(livrare|retur\w*|rambursare|shipping|returns?|refund|envio|devoluci\w+)\b")
_AUTO_WORDS = re.compile(
    r"\b(auto|autos|masini|masina|autoturism\w*|vehicul\w*|vehicle\w*|dealer\w*|concesionari\w*"
    r"|coches?|cars?|automotive|automovil\w*|anvelop\w*|motocicl\w*|motorcycles?|piese auto)\b"
)
_STRIP_TAGS = ["script", "style", "noscript", "template", "svg"]


def fold(value: str) -> str:
    """Lowercase + strip diacritics so RO/ES keywords match regardless of accents."""
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c))


def _segments(url: str) -> list[str]:
    return [s for s in urlsplit(url).path.lower().split("/") if s]


def _in_group(seg: str, group: tuple[str, ...]) -> bool:
    return any(seg == k or seg.startswith(k + "-") for k in group)


def _walk(node: Any) -> Iterator[Any]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _types(node: dict[str, Any]) -> list[str]:
    declared = node.get("@type")
    if isinstance(declared, str):
        return [declared]
    if isinstance(declared, list):
        return [x for x in declared if isinstance(x, str)]
    return []


def _jsonld_nodes(tree: HTMLParser) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text() or "")
        except (ValueError, TypeError):
            continue
        nodes.extend(_walk(data))
    return nodes


def parse_jsonld(html: str) -> list[dict[str, Any]]:
    """All JSON-LD nodes of a page (flattened, malformed blocks ignored)."""
    return _jsonld_nodes(HTMLParser(html or ""))


def _brand_names(nodes: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
        elif isinstance(value, dict):
            add(value.get("name"))
        elif isinstance(value, list):
            for item in value:
                add(item)

    for node in nodes:
        if "Brand" in _types(node):
            add(node.get("name"))
        if "brand" in node:
            add(node["brand"])
    seen: dict[str, str] = {}
    for brand in names:
        seen.setdefault(brand.lower(), brand)
    return list(seen.values())[:10]


def _address_count(nodes: list[dict[str, Any]]) -> int:
    keys = set()
    for node in nodes:
        if "PostalAddress" in _types(node):
            keys.add((str(node.get("streetAddress", "")).lower(), str(node.get("addressLocality", "")).lower()))
    return len(keys)


_ORG_TYPES = {
    "Organization", "Corporation", "LocalBusiness", "Store", "OnlineStore", "AutoDealer", "AutomotiveBusiness",
    "AutoRepair", "AutoPartsStore", "MotorcycleDealer", "BankOrCreditUnion", "FinancialService", "LoanOrCredit",
    "InsuranceAgency", "ProfessionalService", "WebSite",
}


def _text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def jsonld_summary(nodes: list[dict[str, Any]], limit: int = 800) -> str:
    """Compact, non-personal digest of the schema.org nodes that say what the business is (no phones/emails/streets)."""
    parts: list[str] = []
    for node in nodes:
        kinds = [t for t in _types(node) if t in _ORG_TYPES]
        if not kinds or not (node.get("name") or node.get("legalName") or node.get("description")):
            continue
        bits = ["/".join(kinds)]
        for key, cap in (("name", 80), ("legalName", 80), ("description", 220)):
            if cleaned := _text(node.get(key), cap):
                bits.append(f"{key}={cleaned}")
        area = node.get("areaServed")
        if area:
            if isinstance(area, str):
                area_name = area
            elif isinstance(area, dict):
                area_name = area.get("name", "")
            else:
                area_name = ""
            bits.append("areaServed=" + _text(area_name, 60))
        for key in ("sameAs", "makesOffer", "hasOfferCatalog", "department", "subOrganization"):
            value = node.get(key)
            if value:
                bits.append(f"{key}:{len(value) if isinstance(value, list) else 1}")
        parts.append("; ".join(b for b in bits if b and not b.endswith("=")))
        if len(parts) >= 4:
            break
    return " | ".join(parts)[:limit]


def extract_signals(html: str, base_url: str, sitemap_urls: list[str] | None = None) -> Signals:
    sitemap_urls = sitemap_urls or []
    tree = HTMLParser(html or "")
    nodes = _jsonld_nodes(tree)  # parse before stripping scripts
    title_el = tree.css_first("title")
    title = (title_el.text(strip=True) if title_el else "")[:300]
    meta = tree.css_first('meta[name="description"]')
    description = ((meta.attributes.get("content") if meta else "") or "")[:500]
    root = tree.css_first("html")
    lang = ((root.attributes.get("lang") if root else None) or "").split("-")[0].lower() or None
    if not lang:
        alt = tree.css_first("link[hreflang]")
        lang = ((alt.attributes.get("hreflang") if alt else "") or "").split("-")[0].lower() or None

    links = []
    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href") or ""
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        links.append((urljoin(base_url, href), anchor.text(strip=True)))
    form_urls = [urljoin(base_url, form.attributes.get("action") or "") for form in tree.css("form[action]")]
    cart_attr_hits = sum(
        1
        for el in tree.css("[class],[id],[data-action]")
        if any(
            k in fold(" ".join(filter(None, (el.attributes.get("class"), el.attributes.get("id"), el.attributes.get("data-action")))))
            for k in _CART_ATTR
        )
    )

    nav_nodes = tree.css("nav a") or tree.css("header a")
    nav_items: list[str] = []
    for anchor in nav_nodes:
        label = re.sub(r"\s+", " ", anchor.text(strip=True))[:60]
        if label and label not in nav_items:
            nav_items.append(label)
    nav_items = nav_items[:30]

    has_root = bool(tree.css("#root, #app, #__next, #__nuxt, [data-reactroot], app-root"))
    has_scripts = bool(tree.css("script[src]"))
    for el in tree.css("[class],[id]"):
        if el.tag in ("html", "body", "main"):
            continue
        marker = fold((el.attributes.get("class") or "") + " " + (el.attributes.get("id") or ""))
        if _COOKIE_HINT.search(marker) and len(el.text(strip=True)) < 1500:
            el.decompose()  # cookie/consent banners would eat the excerpt budget
    headings = []
    for heading in tree.css("h1, h2, h3"):
        label = re.sub(r"\s+", " ", heading.text(strip=True))[:100]
        if label and label not in headings:
            headings.append(label)
    headings = headings[:15]
    ctas = []
    for button in tree.css("button, [role=button], a.btn, a.button, a[class*=btn], a[class*=button], a[class*=cta]"):
        label = re.sub(r"\s+", " ", button.text(strip=True))[:60]
        if label and label not in ctas:
            ctas.append(label)
    ctas = ctas[:15]
    footer_node = tree.css_first("footer")
    footer_raw = re.sub(r"\s+", " ", footer_node.text(separator=" ", strip=True)) if footer_node else ""
    tree.strip_tags(_STRIP_TAGS)
    body = tree.body
    text = re.sub(r"\s+", " ", body.text(separator=" ", strip=True)) if body else ""
    ftext = fold(text)
    evidence: dict[str, str] = {}

    # --- schema.org
    types = sorted({t for n in nodes for t in _types(n)})
    vehicle_n = sum(1 for n in nodes if VEHICLE_SCHEMA & set(_types(n)))
    product_n = sum(1 for n in nodes if "Product" in _types(n))
    offer_n = sum(1 for n in nodes if {"Offer", "AggregateOffer"} & set(_types(n)))
    if types:
        evidence["schema_types"] = ", ".join(types[:8])

    # --- urls (homepage links + sitemap)
    all_urls = [u for u, _ in links] + sitemap_urls
    patterns = {g: 0 for g in URL_GROUPS}
    seen_urls: set[str] = set()
    for url in all_urls:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        segs = _segments(url)
        for group, keys in URL_GROUPS.items():
            if any(_in_group(s, keys) for s in segs):
                patterns[group] += 1
    for group, count in patterns.items():
        if count:
            evidence[f"url_patterns.{group}"] = f"{count} URLs"

    # --- cart
    cart_hits = cart_attr_hits
    for url, label in links:
        folded = fold(label)
        if _CART_PATH.search(urlsplit(url).path.lower()) or any(k in folded for k in _CART_TEXT):
            cart_hits += 1
            evidence.setdefault("cart_hits", label or url)
    for form_url in form_urls:
        if _CART_PATH.search(urlsplit(form_url).path.lower()):
            cart_hits += 1
    if any(k in ftext for k in _CART_TEXT):
        cart_hits += 1
        evidence.setdefault("cart_hits", next(k for k in _CART_TEXT if k in ftext))
    if cart_attr_hits:
        evidence.setdefault("cart_hits", "add-to-cart element")

    # --- vehicles
    vins: set[str] = set()
    haystack = [text] + [str(n.get("vehicleIdentificationNumber", "")) for n in nodes] + all_urls
    for chunk in haystack:
        for match in _VIN.findall(chunk):
            if any(c.isdigit() for c in match) and any(c.isalpha() for c in match):
                vins.add(match.upper())
    km = len(_KM.findall(ftext))
    if vins:
        evidence["vin_count"] = sorted(vins)[0]
    if km:
        evidence["km_mentions"] = f"{km} mentions"

    # --- actions / navigation
    def link_match(pattern: re.Pattern, path_segs: set[str]) -> str | None:
        for url, label in links:
            if pattern.search(fold(label)) or any(s in path_segs for s in _segments(url)):
                return label or url
        return None

    service = link_match(_SERVICE_TEXT, _SERVICE_SEGS)
    locator = link_match(_LOCATOR_TEXT, _LOCATOR_SEGS)
    config = link_match(_CONFIG_TEXT, {"configurator", "configurador"})
    drive = link_match(_TEST_DRIVE, {"test-drive", "testdrive", "prueba-de-conduccion"})
    post = link_match(_POST_LISTING, {"adauga-anunt", "posteaza-anunt", "post-ad", "publicar-anuncio"})
    for name, value in (
        ("has_post_listing", post),
        ("has_service_booking", service),
        ("has_dealer_locator", locator),
        ("has_configurator", config),
        ("has_test_drive", drive),
    ):
        if value:
            evidence[name] = value[:80]

    # --- prices
    price_count = len(_PRICE.findall(ftext))
    from_count = len(_PRICE_FROM.findall(ftext))
    if price_count == 0:
        style = "none"
    elif from_count >= 2 and from_count / price_count >= 0.3:
        style = "from"
    else:
        style = "per_item"
    if price_count:
        evidence["price_style"] = f"{price_count} prices, {from_count} 'from'"
    ship = len(_SHIP_RETURN.findall(ftext))

    # --- identity
    head_blob = fold(" ".join([title, description, " ".join(nav_items), " ".join(headings)]))
    finance_hits = len(set(_FINANCE_WORDS.findall(head_blob))) + 2 * len(set(_FINANCE_LEGAL.findall(ftext)))
    if finance_hits:
        evidence["finance_hits"] = f"{finance_hits} finance terms"
    samples: list[str] = []
    per_group: dict[str, int] = {}
    for url in sitemap_urls:
        segs = _segments(url)
        group = segs[0] if segs else ""
        if per_group.get(group, 0) < 2 and len(samples) < 15:
            per_group[group] = per_group.get(group, 0) + 1
            samples.append(urlsplit(url).path[:80] or "/")
    sellers = len(_SELLERS.findall(ftext))
    makes = {m for m in _MAKES_RX.findall(fold(" ".join(nav_items) + " " + text[:20000]))}
    if sellers:
        evidence["seller_mentions"] = f"{sellers} mentions"
    if len(makes) >= 8:
        evidence["make_count"] = ", ".join(sorted(makes)[:6])
    brands = _brand_names(nodes)
    locations = _address_count(nodes)
    auto_text = " ".join([title, description, " ".join(nav_items), text[:20000]])
    auto_hits = len(_AUTO_WORDS.findall(fold(auto_text)))
    if AUTO_SCHEMA & set(types) or vehicle_n:
        auto_hits += 5

    return Signals(
        title=title,
        description=description,
        language=lang,
        nav_items=nav_items,
        text_excerpt=text[:3000],
        visible_text_len=len(text),
        js_shell=not nodes and (
            (len(text) < JS_SHELL_MIN_TEXT and has_root) or (len(text) < 100 and has_scripts)
        ),
        schema_types=types,
        vehicle_schema_count=vehicle_n,
        product_schema_count=product_n,
        offer_schema_count=offer_n,
        cart_hits=cart_hits,
        vin_count=len(vins),
        km_mentions=km,
        has_service_booking=bool(service),
        has_dealer_locator=bool(locator),
        has_configurator=bool(config),
        has_test_drive=bool(drive),
        has_post_listing=bool(post),
        finance_hits=finance_hits,
        jsonld_summary=jsonld_summary(nodes),
        headings=headings,
        cta_texts=ctas,
        footer_text=(footer_raw or text)[-600:] if (footer_raw or text) else "",
        sitemap_samples=samples,
        seller_mentions=sellers,
        make_count=len(makes),
        url_patterns=patterns,
        price_count=price_count,
        price_from_count=from_count,
        price_style=style,
        shipping_returns_hits=ship,
        brands=brands,
        locations=locations,
        auto_hits=auto_hits,
        evidence=evidence,
    )
