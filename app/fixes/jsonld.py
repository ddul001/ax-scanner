"""JSON-LD fix generators (AutoDealer, Car + Offer). Pure functions over a finished ScanContext.

Rules: only facts found on the site are written (never invented); everything inferred goes in `assumptions`;
fields the check wants but the page does not expose go in `todo` for the dealer to complete.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any
from urllib.parse import urljoin

from app.checks.context import Page, ScanContext
from app.checks.identity import DEALER_TYPES, PHONE_RX, _dealer_nodes
from app.checks.inventory import _offer_nodes, _vehicle_nodes
from app.checks.util import PRICE_RX, SPEC_WORDS, VIN_RX, first_str, jsonld_types, to_amount, valid_offer_value
from app.domain.scoring import CheckResult, build_report
from app.fixes.base import FixDraft, snippet  # noqa: F401  (snippet re-exported)
from app.services.signals import fold

MAX_VEHICLE_FIXES = 5
CONTEXT = "https://schema.org"
AVAILABILITY = "https://schema.org/InStock"
CONDITION = {"used": "https://schema.org/UsedCondition", "new": "https://schema.org/NewCondition"}
FUEL = (
    ("hibrid", "Hybrid"), ("hybrid", "Hybrid"), ("electric", "Electric"), ("benzin", "Petrol"),
    ("gasolina", "Petrol"), ("motorin", "Diesel"), ("diesel", "Diesel"), ("disel", "Diesel"), ("gpl", "LPG"),
)
KM_RX = re.compile(r"(\d[\d.\s ]*)\s?km\b", re.I)
POWER_RX = re.compile(r"\b(\d{2,4})\s?(cp|hp|kw|cv|ps)\b", re.I)
DEALER_FIELDS = ("name", "address", "geo", "telephone", "openingHours", "brand")
DEALER_LABELS = {
    "name": "name", "address": "address (PostalAddress)", "geo": "geo coordinates",
    "telephone": "telephone", "openingHours": "opening hours", "brand": "brand",
}


# ---------- validation (structural subset of schema.org rules) ----------

def validate(node: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if node.get("@context") != CONTEXT:
        errs.append("@context must be https://schema.org")
    types = jsonld_types(node)
    if not types:
        errs.append("@type missing")
    if not first_str(node.get("name")):
        errs.append("name missing")
    if "Car" in types or "Vehicle" in types:
        if not first_str(node.get("url")).startswith("http"):
            errs.append("url must be absolute")
        offer = node.get("offers")
        if offer is not None:
            if not isinstance(offer, dict) or offer.get("@type") != "Offer":
                errs.append("offers must be an Offer")
            else:
                try:
                    if float(offer.get("price")) <= 0:
                        errs.append("Offer.price must be > 0")
                except (TypeError, ValueError):
                    errs.append("Offer.price must be numeric")
                if not re.fullmatch(r"[A-Z]{3}", str(offer.get("priceCurrency", ""))):
                    errs.append("Offer.priceCurrency must be an ISO 4217 code")
    if DEALER_TYPES & set(types):
        addr = node.get("address")
        if addr is not None and (not isinstance(addr, dict) or addr.get("@type") != "PostalAddress"):
            errs.append("address must be a PostalAddress")
    try:
        json.dumps(node)
    except (TypeError, ValueError):
        errs.append("not JSON-serialisable")
    return errs


# ---------- helpers ----------

def _meta(page: Page, prop: str) -> str:
    el = page.tree.css_first(f'meta[property="{prop}"]') or page.tree.css_first(f'meta[name="{prop}"]')
    return ((el.attributes.get("content") if el else "") or "").strip()


def _abs_images(page: Page, limit: int = 5) -> list[str]:
    out: list[str] = []
    og = _meta(page, "og:image")
    if og:
        out.append(urljoin(page.url, og))
    for img in page.tree.css("img"):
        src = img.attributes.get("src") or img.attributes.get("data-src") or ""
        blob = fold(src + " " + (img.attributes.get("class") or "") + " " + (img.attributes.get("alt") or ""))
        if not src or src.startswith("data:") or src.lower().endswith(".svg") or re.search(r"logo|icon|sprite|avatar", blob):
            continue
        url = urljoin(page.url, src)
        if url not in out:
            out.append(url)
    return out[:limit]


def _site_name(ctx: ScanContext) -> str:
    name = _meta(ctx.home, "og:site_name")
    if name:
        return name
    title = ctx.home.tree.css_first("title")
    return re.split(r"\s[|–—-]\s", title.text(strip=True))[0].strip() if title else ""


def _tel(ctx: ScanContext) -> str:
    for page in (ctx.home, *ctx.ok_by_role("contact")):
        anchor = page.tree.css_first('a[href^="tel:"]')
        if anchor:
            return re.sub(r"[^\d+]", "", (anchor.attributes.get("href") or "")[4:])
    return ""


def _text_phone(ctx: ScanContext) -> str:
    """Phone written in plain text, accepted only when the same number shows on every homepage/contact page that has one."""
    found = []
    for page in (ctx.home, *ctx.ok_by_role("contact")):
        nums = {re.sub(r"[^\d+]", "", m) for m in PHONE_RX.findall(page.text) if len(re.sub(r"\D", "", m)) >= 9}
        if nums:
            found.append(nums)
    common = set.intersection(*found) if found else set()
    return sorted(common)[0] if len(common) == 1 else ""


_TEMPLATE_RX = re.compile(r"\{\{|\}\}|\{%|<%|<\?|\$\{")


def _scrub(node: Any, dropped: list[str], path: str = "") -> Any:
    """Remove values that are unrendered template code (e.g. "{{$model->price}}"): the page's own bug, not a fact."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            clean = _scrub(value, dropped, f"{path}.{key}" if path else key)
            if clean not in (None, "", [], {}):
                out[key] = clean
        return out
    if isinstance(node, list):
        return [c for c in (_scrub(v, dropped, path) for v in node) if c not in (None, "", [], {})]
    if isinstance(node, str) and _TEMPLATE_RX.search(node):
        dropped.append(path)
        return None
    return node


def _is_vehicle_page(page: Page) -> bool:
    """Evidence that a page is a vehicle, not an accessory or a category that the URL rules took for one."""
    if _vehicle_nodes(page) or VIN_RX.search(page.text.upper()):
        return True
    folded = fold(page.text)
    signals = (
        bool(KM_RX.search(page.text)), bool(POWER_RX.search(page.text)),
        any(tok in folded for tok, _ in FUEL), bool(SPEC_WORDS["year"].search(page.text)),
    )
    return sum(signals) >= 3


def _currency(token: str) -> str:
    lowered = token.lower()
    return "EUR" if ("€" in lowered or "eur" in lowered) else "RON"


# ---------- dealer ----------

def build_dealer(ctx: ScanContext, brands: list[str]) -> FixDraft:
    nodes = _dealer_nodes(ctx)
    base = (
        copy.deepcopy(max(nodes, key=lambda item: bool(DEALER_TYPES & set(jsonld_types(item[1]))))[1])
        if nodes else {}
    )
    assumptions: list[str] = []
    if nodes and not (DEALER_TYPES & set(jsonld_types(base))):
        assumptions.append(f"Type changed from {'/'.join(jsonld_types(base)) or 'unknown'} to AutoDealer (the site sells vehicles).")
    rest = {k: v for k, v in base.items() if k not in ("@context", "@type")}
    node: dict[str, Any] = {"@context": CONTEXT, "@type": "AutoDealer", **rest}
    if not first_str(node.get("name")):
        if name := _site_name(ctx):
            node["name"] = name
            assumptions.append("name taken from og:site_name / page title.")
    node.setdefault("url", ctx.origin)
    if not node.get("telephone"):
        if tel := _tel(ctx):
            node["telephone"] = tel
        elif tel := _text_phone(ctx):
            node["telephone"] = tel
            assumptions.append("telephone read from plain text shared by the homepage and contact page.")
    if not node.get("image") and (og := _meta(ctx.home, "og:image")):
        node["image"] = urljoin(ctx.home.url, og)
    if not node.get("brand") and brands:
        node["brand"] = [{"@type": "Brand", "name": b} for b in brands[:5]]
        assumptions.append("brand taken from the scan's brand detection.")
    todo = [
        DEALER_LABELS[f] for f in DEALER_FIELDS
        if not (node.get(f) or (f == "openingHours" and node.get("openingHoursSpecification")))
    ]
    return FixDraft(
        check_id="id.schema_dealer", type="jsonld", title="AutoDealer JSON-LD", target_url=ctx.origin + "/",
        jsonld=node, placement="Homepage and contact page, inside <head> or before </body>.",
        assumptions=assumptions, todo=todo, errors=validate(node),
    )


# ---------- vehicle + offer ----------

def build_vehicle(page: Page, brands: list[str]) -> FixDraft:
    dropped: list[str] = []
    existing = _scrub({k: v for n in _vehicle_nodes(page) for k, v in n.items() if k not in ("@context", "@type")}, dropped)
    ex_offer = next(iter(_offer_nodes(page)), None) or (
        existing.get("offers") if isinstance(existing.get("offers"), dict) else None
    )
    if ex_offer is None:  # the page's offers can sit on an untyped / non-vehicle node
        raw = next((n.get("offers") for n in page.jsonld if isinstance(n.get("offers"), dict)), None)
        ex_offer = raw
    ex_offer = _scrub(ex_offer, dropped, "offers") if ex_offer else None
    text = page.text
    folded = fold(page.text)
    h1 = page.tree.css_first("h1")
    name = first_str(existing.get("name")) or (h1.text(strip=True) if h1 else "") or _meta(page, "og:title")
    assumptions: list[str] = []
    if dropped:
        assumptions.append("The page's own JSON-LD contains unrendered template code, which was discarded: "
                           + ", ".join(dict.fromkeys(dropped)) + ". Fix the template so the live page outputs real values.")
    todo: list[str] = []
    node: dict[str, Any] = {"@context": CONTEXT, "@type": "Car", **existing}
    if name:
        node["name"] = name
    node["url"] = page.url

    if not node.get("vehicleIdentificationNumber"):
        match = VIN_RX.search(text.upper())
        if match:
            node["vehicleIdentificationNumber"] = match.group(0)
        else:
            todo.append("VIN")
    km = None
    if not node.get("mileageFromOdometer"):
        match = KM_RX.search(text)
        km = to_amount(match.group(1).replace(" ", " ").strip()) if match else None
        if km is not None and 0 <= km <= 1_500_000:
            node["mileageFromOdometer"] = {"@type": "QuantitativeValue", "value": int(km), "unitCode": "KMT"}
        else:
            km = None
            todo.append("mileage")
    elif isinstance(node["mileageFromOdometer"], dict):
        try:
            km = float(node["mileageFromOdometer"].get("value"))
        except (TypeError, ValueError):
            km = None
    if not (node.get("vehicleModelDate") or node.get("productionDate")):
        match = SPEC_WORDS["year"].search(name) or SPEC_WORDS["year"].search(text)
        if match:
            node["vehicleModelDate"] = match.group(0)
            assumptions.append(f"vehicleModelDate {match.group(0)} is the first year found on the page.")
        else:
            todo.append("year")
    if not node.get("fuelType"):
        hit = next((label for tok, label in FUEL if tok in folded), None)
        if hit:
            node["fuelType"] = hit
        else:
            todo.append("fuel type")
    if not node.get("vehicleTransmission"):
        if re.search(r"\bautomat\w*|\bautomatic\b", folded):
            node["vehicleTransmission"] = "Automatic"
        elif re.search(r"\bmanual\w*", folded):
            node["vehicleTransmission"] = "Manual"
        else:
            todo.append("transmission")
    if not node.get("vehicleEngine"):
        match = POWER_RX.search(text)
        if match:
            unit = "KWT" if match.group(2).lower() == "kw" else "BHP"
            node["vehicleEngine"] = {"@type": "EngineSpecification", "enginePower": {
                "@type": "QuantitativeValue", "value": int(match.group(1)), "unitCode": unit}}
        else:
            todo.append("engine power")
    if not node.get("image"):
        imgs = _abs_images(page)
        if imgs:
            node["image"] = imgs
        else:
            todo.append("photos")
    if not node.get("brand"):
        brand = next((b for b in brands if fold(b) in fold(name)), None)
        if brand:
            node["brand"] = {"@type": "Brand", "name": brand}
        else:
            todo.append("brand")

    offer: dict[str, Any] = {"@type": "Offer", **{k: v for k, v in (ex_offer or {}).items() if k != "@context"}}
    if not offer.get("price"):
        match = PRICE_RX.search(text)
        amount = to_amount(match.group(1) or match.group(2)) if match else None
        if match and amount:
            offer["price"] = int(amount) if amount == int(amount) else amount
            offer.setdefault("priceCurrency", _currency(match.group(0)))
            assumptions.append("Offer.price is the first price found on the page; check it is the vehicle price.")
        else:
            todo.append("price")
    if offer.get("price"):
        if not offer.get("priceCurrency"):
            todo.append("priceCurrency")
        offer.setdefault("url", page.url)
        if not offer.get("availability"):
            offer["availability"] = AVAILABILITY
            assumptions.append("availability set to InStock because the vehicle is listed on the stock page.")
        if not offer.get("itemCondition"):
            if km is None:
                todo.append("itemCondition")
            else:
                offer["itemCondition"] = CONDITION["used" if km > 100 else "new"]
                assumptions.append(f"itemCondition inferred from mileage ({int(km)} km).")
        node["offers"] = offer
    return FixDraft(
        check_id="inv.schema_vehicle", type="jsonld", title=f"Car + Offer JSON-LD: {name or page.url}"[:120],
        target_url=page.url, jsonld=node, placement="This vehicle page, inside <head> or before </body>.",
        assumptions=assumptions, todo=list(dict.fromkeys(todo)), errors=validate(node),
    )


# ---------- orchestration ----------

def _gain(site_type: str, weights: dict[str, float], results: list[CheckResult], check_ids: set[str]) -> float:
    before = build_report(site_type, weights, results).ax_score
    fixed = [r.model_copy(update={"status": "pass", "not_adopted": False})
             if r.check_id in check_ids and r.status in ("warn", "fail") else r for r in results]
    return round(max(0.0, build_report(site_type, weights, fixed).ax_score - before), 1)


def generate_fixes(
    ctx: ScanContext, results: list[CheckResult], weights: dict[str, float], brands: list[str] | None = None
) -> list[FixDraft]:
    brands = brands or []
    by_id = {r.check_id: r for r in results}
    drafts: list[FixDraft] = []

    dealer = by_id.get("id.schema_dealer")
    if dealer and dealer.status in ("warn", "fail"):
        draft = build_dealer(ctx, brands)
        draft.est_gain = _gain(ctx.site_type, weights, results, {"id.schema_dealer"})
        drafts.append(draft)

    needs = {i for i in ("inv.schema_vehicle", "inv.schema_offer") if by_id.get(i) and by_id[i].status in ("warn", "fail")}
    if needs:
        need = ("price", "priceCurrency", "availability", "itemCondition")

        def incomplete(page: Page) -> bool:
            has_offer = any(all(valid_offer_value(f, n.get(f)) for f in need) for n in _offer_nodes(page))
            return not (_vehicle_nodes(page) and has_offer)

        pages = [p for p in ctx.ok_by_role("vdp") if _is_vehicle_page(p) and incomplete(p)][:MAX_VEHICLE_FIXES]
        vehicles = [build_vehicle(p, brands) for p in pages]
        if vehicles:
            total = _gain(ctx.site_type, weights, results, needs)
            for draft in vehicles:  # gain is shared: it is reached only when all sampled VDPs are fixed
                draft.est_gain = round(total / len(vehicles), 1)
            drafts.extend(vehicles)
    return drafts
