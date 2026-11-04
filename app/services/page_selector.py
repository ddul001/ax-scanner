"""Choose which pages to crawl for a site type (docs/PLAN.md section 4): URL patterns + stable sample."""
from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.services.signals import URL_GROUPS

ROLE_SEGMENTS: dict[str, tuple[str, ...]] = {
    "service": ("service", "atelier", "programare-service", "service-auto", "taller", "cita-taller"),
    "test_drive": ("test-drive", "testdrive", "programare-test-drive", "prueba-de-conduccion", "solicita-prueba"),
    "contact": ("contact", "contacto", "contact-us", "despre-noi", "about", "sobre-nosotros"),
    "faq": ("faq", "intrebari-frecvente", "preguntas-frecuentes", "ajutor", "help"),
    "financing": ("finantare", "leasing", "credit", "financiacion", "financiare", "financing"),
}
STOCK = URL_GROUPS["stock"]
# page budget per role for a dealer (sum <= 15); home is added separately
DEALER_BUDGET = {"stock_list": 2, "vdp": 5, "service": 2, "test_drive": 1, "contact": 1, "faq": 1, "financing": 1}
_VDP_QUERY = re.compile(r"(?:^|&)(?:category|brand|marca|make)=[^&]+", re.I)
_ASSET = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|pdf|css|js|ico|xml|zip|mp4)(?:\?|$)", re.I)
_PAGE_EXT = re.compile(r"\.(?:html?|php\d?|aspx?|jsp)$")


@dataclass(frozen=True)
class PageRef:
    url: str
    role: str


def _segs(url: str) -> list[str]:
    segs = [s for s in urlsplit(url).path.lower().split("/") if s]
    if segs:
        segs[-1] = _PAGE_EXT.sub("", segs[-1]) or segs[-1]  # /dealeri.html is the page "dealeri"
    return segs


def _is_stock_seg(seg: str) -> bool:
    return any(seg == k or seg.startswith(k + "-") for k in STOCK)


def _detail_like(seg: str) -> bool:
    """A slug that identifies one item: has a digit, or is a long hyphenated slug."""
    return bool(re.search(r"\d", seg)) or (seg.count("-") >= 3 and len(seg) >= 14)


def infer_vdp_prefixes(urls: list[str]) -> set[str]:
    """Language-independent fallback: if one first path segment holds most of a large sitemap and its URLs end in
    slugs with ids, that segment is the vehicle-detail section (e.g. /vanzari-auto/<make>-<model>-<id>.html)."""
    firsts = [(_segs(u) or [""])[0] for u in urls if _segs(u) and len(_segs(u)) >= 2]
    if len(firsts) < 20:
        return set()
    out = set()
    for seg, count in Counter(firsts).most_common(2):
        if count / max(len(urls), 1) >= 0.5 and count >= 20:
            slugs = [(_segs(u) or [""])[-1] for u in urls if (_segs(u) or [""])[0] == seg]
            if sum(bool(re.search(r"\d", s)) for s in slugs) / len(slugs) >= 0.8:
                out.add(seg)
    return out


def classify_url(url: str, vdp_prefixes: frozenset[str] | set[str] = frozenset()) -> str | None:
    """Role of a URL for a dealer site, or None if it is not interesting."""
    if _ASSET.search(urlsplit(url).path):
        return None
    segs = _segs(url)
    if not segs:
        return None
    if len(segs) == 1 and _detail_like(segs[0]) and _VDP_QUERY.search(urlsplit(url).query):
        return "vdp"  # /<make>-<model>-<trim>?category=<brand>: one slug, brand in the query (e.g. pia.ro)
    if len(segs) >= 2 and segs[0] in vdp_prefixes:
        return "vdp"
    for role, keys in ROLE_SEGMENTS.items():
        if any(seg == k or seg.startswith(k + "-") for seg in segs for k in keys):
            return role
    for i, seg in enumerate(segs):
        if _is_stock_seg(seg):
            rest = segs[i + 1:]
            if any(_detail_like(r) for r in rest) and not all(_is_stock_seg(r) for r in rest):
                return "vdp"
            return "stock_list"
    return None


# ---- brand / importer sites (docs/checks/importer.md): models, offers, dealer locator, configurator ----
BRAND_SEGMENTS: dict[str, tuple[str, ...]] = {
    "configurator": (
        "configurator", "configureaza", "configura", "configurador", "configure", "build", "build-your",
        "personalizeaza", "personaliza",
    ),
    "test_drive": ROLE_SEGMENTS["test_drive"] + (
        "programeaza-test-drive", "solicita-prueba-de-conduccion", "probefahrt", "essai",
        "essai-routier", "prova-su-strada", "testrit", "proefrit",
    ),
    "locator": (
        "dealeri", "dealer", "dealer-locator", "reteaua-de-dealeri", "retea", "reteaua", "gaseste-dealer",
        "gaseste-un-dealer", "find-a-dealer", "dealers", "concesionarios", "concesionario",
        "encuentra-tu-concesionario", "puncte-de-vanzare", "distribuitori", "distribuitor", "locator",
        "haendler", "haendlersuche", "handler", "partnersuche", "concessionnaires",
        "trouver-un-concessionnaire", "reseau", "concessionari", "rete-vendita", "dealer-zoeken",
    ),
    "shop": (
        "shop", "magazin", "magazin-online", "accesorii", "tienda", "store", "boutique", "webshop",
        "eshop", "e-shop", "accesorios", "zubehoer", "zubehor", "accessoires", "accessori",
    ),
    "offers": (
        "oferte", "oferta", "promotii", "campanii", "offers", "ofertas", "promociones", "deals",
        "special-offers", "angebote", "aktionen", "offres", "promotions", "offerte", "aanbiedingen",
    ),
    "contact": ROLE_SEGMENTS["contact"],
    "faq": ROLE_SEGMENTS["faq"],
}
_MODEL_KEYS = (
    "modele", "gama", "gama-modele", "gama-de-modele", "toate-modelele", "models", "range", "modelos",
    "our-models", "gamma", "new-cars", "new-models", "all-models", "autoturisme", "coches",
    "modelle", "gamme", "modeles", "modelli", "modellen",
)
_OLD_MODELS = re.compile(r"(?:vechi|-old|/old|discontinu|arhiv|archive|istoric|oldmodels)")
_USED_STOCK = re.compile(
    r"rulate|second-?hand|ocazi|usado|segunda-mano|used|approved|certified|certificat"
    r"|gebrauchtwagen|jahreswagen|occasion|usato|tweedehands"
)
_NEW_STOCK = (
    "stoc", "stock", "masini-noi", "vehicule-noi", "autoturisme-noi", "pronta-livrare", "coches-nuevos",
    "stoc-nou", "neuwagen", "lagerfahrzeuge", "vehicules-neufs", "stock-neuf", "nuovo", "nieuw",
)
BRAND_BUDGET = {
    "models_list": 1, "model": 4, "offers": 1, "locator": 1, "configurator": 1, "test_drive": 1,
    "shop": 1, "contact": 1, "stock_new": 1, "stock_used": 1, "faq": 1,
}


def _seg_is(seg: str, keys: tuple[str, ...]) -> bool:
    return any(seg == k or seg.startswith(k + "-") for k in keys)


def classify_brand_url(  # noqa: ARG001 (same signature as classify_url)
    url: str, vdp_prefixes: frozenset[str] | set[str] = frozenset()
) -> str | None:
    """Role of a URL on a brand/importer site, or None."""
    if _ASSET.search(urlsplit(url).path):
        return None
    segs = _segs(url)
    if not segs:
        return None
    for role in ("configurator", "test_drive", "locator", "shop", "offers"):
        if any(_seg_is(s, BRAND_SEGMENTS[role]) for s in segs):
            return role
    if any(_USED_STOCK.search(s) for s in segs):
        return "stock_used"
    if any(_seg_is(s, _NEW_STOCK) for s in segs):
        return "stock_new"
    for role in ("contact", "faq"):
        if any(_seg_is(s, BRAND_SEGMENTS[role]) for s in segs):
            return role
    if _seg_is(segs[0], _MODEL_KEYS):
        if _OLD_MODELS.search(url.lower()):
            return None  # discontinued / archived models are not the current range
        return "model" if len(segs) >= 2 and segs[-1] not in _MODEL_KEYS else "models_list"
    return None


# ---- online shops (docs/checks/ecommerce.md): categories, products, policies, cart ----
SHOP_SEGMENTS: dict[str, tuple[str, ...]] = {
    "cart": ("cos", "cos-de-cumparaturi", "cart", "carrito", "warenkorb", "panier", "basket", "winkelmand"),
    "checkout": ("checkout", "finalizare-comanda", "finalizeaza-comanda", "comanda", "pago", "kasse", "paiement", "afrekenen"),
    "shipping": ("livrare", "transport", "shipping", "delivery", "envios", "envio", "versand", "livraison", "levering"),
    "returns": ("retur", "returnare", "returns", "return-policy", "devoluciones", "devolucion", "ruckgabe", "retour", "retourneren"),
    "warranty": ("garantie", "garantii", "warranty", "garantia", "gewaehrleistung", "garantie-legale"),
    "offers": ("oferte", "promotii", "promotions", "offers", "ofertas", "angebote", "aktionen", "offres", "deals", "reduceri"),
    "contact": ("contact", "contacto", "kontakt", "contactez-nous", "despre-noi", "about"),
}
_CATEGORY_KEYS = (
    "categorii", "categorie", "category", "categories", "produse", "products", "catalog", "shop", "magazin",
    "tienda", "categoria", "categorias", "kategorie", "kategorien", "boutique", "roti-iarna", "anvelope",
    "piese", "tires",
)
SHOP_BUDGET = {
    "categories": 1, "product": 5, "offers": 1, "cart": 1, "checkout": 1, "shipping": 1,
    "returns": 1, "warranty": 1, "contact": 1,
}


def classify_shop_url(url: str, vdp_prefixes: frozenset[str] | set[str] = frozenset()) -> str | None:  # noqa: ARG001
    """Role of a URL on an online shop, or None."""
    if _ASSET.search(urlsplit(url).path):
        return None
    segs = _segs(url)
    if not segs:
        return None
    for role in ("cart", "checkout", "shipping", "returns", "warranty", "offers", "contact"):
        if any(_seg_is(s, SHOP_SEGMENTS[role]) for s in segs):
            return role
    if _seg_is(segs[0], _CATEGORY_KEYS):
        if len(segs) >= 2 and _detail_like(segs[-1]):
            return "product"
        return "categories"
    return None


@dataclass(frozen=True)
class SiteKind:
    """How a site type is crawled: page budget, URL rules, roles the LLM resolver fills, and the list/item pair."""

    budget: dict[str, int]
    classify: Callable[..., str | None]
    roles: tuple[str, ...]
    list_role: str
    item_role: str
    item_max: int
    prefix_roles: tuple[str, ...]
    llm_items: bool = True  # False: item pages come from rules (sitemap sample); the LLM only fills in when rules find too few


def same_site(url: str, host: str) -> bool:
    hostname = (urlsplit(url).hostname or "").lower()
    return hostname == host or hostname == "www." + host or "www." + hostname == host


def seeded_sample(items: list[str], n: int, seed: str) -> list[str]:
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))
    pool = sorted(set(items))
    rng.shuffle(pool)
    return pool[:n]


def select_pages(
    host: str,
    home_url: str,
    candidate_urls: list[str],
    budget: dict[str, int] | None = None,
    classify: Callable[..., str | None] | None = None,
) -> list[PageRef]:
    """Homepage + role-based pages, reproducible per domain (seeded sample, no randomness)."""
    budget = budget or DEALER_BUDGET
    classify = classify or classify_url
    by_role: dict[str, list[str]] = {}
    prefixes = infer_vdp_prefixes([u for u in candidate_urls if same_site(u, host)])
    for candidate in candidate_urls:
        if not same_site(candidate, host):
            continue
        candidate = candidate.split("#", 1)[0]
        role = classify(candidate, prefixes)
        if role in budget:
            by_role.setdefault(role, []).append(candidate)
    pages = [PageRef(home_url, "home")]
    for role, n in budget.items():
        urls = by_role.get(role, [])
        if role == "model" and urls:  # sample among the shallowest model URLs (not galleries / sub-pages)
            top = min(len(_segs(u)) for u in urls)
            chosen = seeded_sample([u for u in urls if len(_segs(u)) == top], n, host + role)
        elif role not in ("vdp",):
            urls = sorted(set(urls), key=lambda x: (len(_segs(x)), len(x)))  # shallowest first = category pages
            chosen = urls[:n]
        else:
            chosen = seeded_sample(urls, n, host + role)
        pages += [PageRef(u, role) for u in chosen if u != home_url]
    return pages[:15]


def vdp_candidates_from_list(
    list_url: str, links: list[str], host: str, prefixes: frozenset[str] | set[str] = frozenset()
) -> list[str]:
    """VDP-looking links found on a stock list page (for sites without a useful sitemap)."""
    return [u for u in links if same_site(u, host) and classify_url(u, prefixes) == "vdp"]


KINDS: dict[str, SiteKind] = {
    "importer": SiteKind(
        budget=BRAND_BUDGET,
        classify=classify_brand_url,
        roles=("models_list", "locator", "test_drive", "configurator", "offers", "contact", "shop", "stock_new", "stock_used"),
        list_role="models_list",
        item_role="model",
        item_max=4,
        prefix_roles=("models_list", "offers", "locator"),
    ),
    "ecommerce": SiteKind(
        budget=SHOP_BUDGET,
        classify=classify_shop_url,
        roles=("categories", "offers", "cart", "checkout", "shipping", "returns", "warranty", "contact"),
        list_role="categories",
        item_role="product",
        item_max=5,
        prefix_roles=("categories", "offers"),
    ),
    "dealer": SiteKind(
        budget=DEALER_BUDGET,
        classify=classify_url,
        roles=("stock_list", "test_drive", "service", "contact", "financing", "faq"),
        list_role="stock_list",
        item_role="vdp",
        item_max=5,
        prefix_roles=("stock_list",),
        llm_items=False,
    ),
}
