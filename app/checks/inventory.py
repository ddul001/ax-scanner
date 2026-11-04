"""Data layer for dealers: vehicle detail pages (inv.*)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from app.checks.context import Page, ScanContext
from app.checks.util import (
    PRICE_RX, SPEC_WORDS, VIN_RX, jsonld_types, prices_in_text, res, share_status, to_amount, valid_offer_value,
)
from app.domain.scoring import CheckResult
from app.services.page_selector import classify_url
from app.services.signals import fold

VEHICLE_TYPES = {"Car", "Vehicle", "Motorcycle", "MotorizedBicycle", "BusOrCoach"}
STOCK_ANCHOR = re.compile(
    r"\b(stoc|masini rulate|second hand|vehicule rulate|ocazii|rulate|used cars|coches de ocasion|segunda mano)\b"
)


def _vehicle_nodes(page: Page) -> list[dict[str, Any]]:
    return [n for n in page.jsonld if VEHICLE_TYPES & set(jsonld_types(n))]


def _offer_nodes(page: Page) -> list[dict[str, Any]]:
    return [n for n in page.jsonld if {"Offer", "AggregateOffer"} & set(jsonld_types(n))]


def _vdps(ctx: ScanContext) -> list[Page]:
    return ctx.ok_by_role("vdp")


def _external_stock_hosts(ctx: ScanContext) -> list[str]:
    hosts = []
    for url, label in ctx.home.links:
        hostname = (urlsplit(url).hostname or "").lower()
        same = hostname == ctx.host or hostname.endswith("." + ctx.host) or ctx.host.endswith("." + hostname)
        if hostname and not same and STOCK_ANCHOR.search(fold(label)):
            if hostname not in hosts:
                hosts.append(hostname)
    return hosts[:3]


async def vdp_urls(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    universe: set[str] = {e.url for e in ctx.sitemap if ctx.classify(e.url) == "vdp"}
    for page in ctx.pages:
        if page.ok and page.role in ("home", "stock_list"):
            universe |= {u for u, _ in page.links if ctx.classify(u) == "vdp"}
    fetched = ctx.by_role("vdp")
    ok = [p for p in fetched if p.ok]
    n = len(universe | {p.url for p in fetched})
    external = _external_stock_hosts(ctx)
    if n == 0:
        note = (
            f" The homepage links to stock hosted on another domain ({', '.join(external)}); that domain is not scanned."
            if external else ""
        )
        return res(spec, "fail", "No crawlable vehicle detail page URLs found (sitemap, homepage or stock pages)." + note,
                   missing=["VDP URLs"], details={"discovered": 0, "external_stock_hosts": external})
    working = len(ok) / len(fetched) if fetched else 1.0
    sample = [p.url for p in ok][:3]
    details = {"discovered": n, "fetched": len(fetched), "ok": len(ok)}
    if n >= 3 and working >= 0.8:
        return res(spec, "pass", f"{n} unique VDP URLs discovered; {len(ok)}/{len(fetched)} sampled pages load.",
                   pages=sample, details=details)
    return res(spec, "warn", f"{n} VDP URLs discovered; {len(ok)}/{len(fetched)} sampled pages load.",
               pages=sample, missing=["3+ VDPs that load"], details=details)


async def schema_vehicle(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    vdps = _vdps(ctx)
    if not vdps:
        return res(spec, "na", "No VDP fetched.")
    with_schema = [p.url for p in vdps if _vehicle_nodes(p)]
    share = len(with_schema) / len(vdps)
    return res(spec, share_status(share, 0.8, 0.4), f"Car/Vehicle JSON-LD on {len(with_schema)}/{len(vdps)} sampled VDPs.",
               pages=[p.url for p in vdps], found=with_schema[:3],
               missing=[p.url for p in vdps if p.url not in with_schema][:3], details={"share": round(share, 2)})


async def schema_offer(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    vdps = _vdps(ctx)
    if not vdps:
        return res(spec, "na", "No VDP fetched.")
    need = ("price", "priceCurrency", "availability", "itemCondition")
    complete = []
    partial = []
    absent_fields = set()
    invalid: dict[str, str] = {}  # field -> example of a value that breaks the schema.org rule
    for page in vdps:
        present = {f for n in _offer_nodes(page) for f in need if valid_offer_value(f, n.get(f))}
        for node in _offer_nodes(page):
            for field in need:
                if node.get(field) not in (None, "") and not valid_offer_value(field, node.get(field)):
                    invalid.setdefault(field, str(node.get(field))[:60])
        if len(present) == len(need):
            complete.append(page.url)
        elif {"price", "priceCurrency"} <= present:
            partial.append(page.url)
        absent_fields |= set(need) - present
    share = len(complete) / len(vdps)
    ok_share = (len(complete) + len(partial)) / len(vdps)
    status = share_status(share, 0.8, 2)  # pass only with all four fields
    if status != "pass":
        status = "warn" if ok_share >= 0.5 else "fail"
    invalid_note = (
        f" Invalid values: {', '.join(f'{k}={v!r}' for k, v in invalid.items())}." if invalid else ""
    )
    return res(spec, status,
               f"Offer with price, currency, availability and condition on {len(complete)}/{len(vdps)} VDPs "
               f"({len(partial)} more have price and currency only)."
               + invalid_note,
               pages=[p.url for p in vdps], found=complete[:3], missing=sorted(absent_fields),
               details={"complete": len(complete), "price_currency_only": len(partial), "invalid_values": invalid})


def _fields_of(page: Page) -> dict[str, bool]:
    text = page.text
    folded = fold(page.text)
    ld = {k: v for n in _vehicle_nodes(page) for k, v in n.items()}
    imgs = [i for i in page.tree.css("img") if (i.attributes.get("src") or i.attributes.get("data-src"))]
    ld_img = ld.get("image")
    return {
        "vin": bool(ld.get("vehicleIdentificationNumber")) or bool(VIN_RX.search(text.upper())),
        "mileage": bool(ld.get("mileageFromOdometer")) or bool(SPEC_WORDS["km"].search(folded)),
        "year": bool(ld.get("vehicleModelDate") or ld.get("productionDate") or ld.get("modelDate")) or bool(SPEC_WORDS["year"].search(folded)),
        "fuel": bool(ld.get("fuelType")) or bool(SPEC_WORDS["fuel"].search(folded)),
        "transmission": bool(ld.get("vehicleTransmission")) or bool(SPEC_WORDS["transmission"].search(folded)),
        "power": bool(ld.get("vehicleEngine")) or bool(SPEC_WORDS["power"].search(folded)),
        "photos": len(imgs) >= 3 or (isinstance(ld_img, list) and len(ld_img) >= 3),
    }


async def fields(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    vdps = _vdps(ctx)
    if not vdps:
        return res(spec, "na", "No VDP fetched.")
    per = [_fields_of(p) for p in vdps]
    names = list(per[0])
    shares = {k: sum(x[k] for x in per) / len(per) for k in names}
    weak = sorted(k for k, v in shares.items() if v < 0.8)
    mean = sum(shares.values()) / len(shares)
    status = "pass" if not weak else "warn" if mean >= 0.5 else "fail"
    return res(spec, status, f"Fields present on >=80% of VDPs: {len(names) - len(weak)}/{len(names)}.",
               pages=[p.url for p in vdps], found=[k for k in names if k not in weak], missing=weak,
               details={"shares": {k: round(v, 2) for k, v in shares.items()}})


async def price_readable(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    vdps = _vdps(ctx)
    if not vdps:
        return res(spec, "na", "No VDP fetched.")
    with_price = [p for p in vdps if prices_in_text(p.text)]
    share = len(with_price) / len(vdps)
    image_hint = []
    for page in vdps:
        if page in with_price:
            continue
        for img in page.tree.css("img"):
            blob = fold((img.attributes.get("alt") or "") + " " + (img.attributes.get("src") or ""))
            if re.search(r"\b(pret|price|precio)\b", blob):
                image_hint.append(page.url)
                break
    missing = [p.url for p in vdps if p not in with_price]
    return res(spec, share_status(share, 0.9, 0.5),
               f"Price is real text on {len(with_price)}/{len(vdps)} VDPs. (Price-in-image vision check not run yet.)",
               pages=[p.url for p in vdps], found=[p.url for p in with_price][:3], missing=missing[:3],
               details={"share": round(share, 2), "possible_price_in_image": image_hint[:3], "vision": "deferred"})


async def price_consistency(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    checked = 0
    matched = 0
    mismatched = []
    for page in _vdps(ctx):
        ld_prices = []
        for node in _offer_nodes(page):
            raw = node.get("price")
            if raw is None:
                spec_node = node.get("priceSpecification")
                raw = spec_node.get("price") if isinstance(spec_node, dict) else None
            amount = to_amount(str(raw).split(".")[0]) if raw not in (None, "") else None
            if amount:
                ld_prices.append(amount)
        if not ld_prices:
            continue
        checked += 1
        visible = set(prices_in_text(page.text))
        if any(abs(v - lp) <= max(1.0, lp * 0.005) for v in visible for lp in ld_prices):
            matched += 1
        else:
            mismatched.append(f"{page.url}: JSON-LD {ld_prices[0]:g} vs visible {sorted(visible)[:3]}")
    if checked == 0:
        return res(spec, "na", "No VDP exposes a numeric price in JSON-LD, so there is nothing to compare.")
    share = matched / checked
    return res(spec, share_status(share, 0.8, 0.5), f"JSON-LD price equals the visible price on {matched}/{checked} VDPs.",
               pages=[p.url for p in _vdps(ctx)], missing=mismatched[:3], details={"share": round(share, 2)})
