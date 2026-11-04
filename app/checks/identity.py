"""Identity layer: does the site say who the dealer is? (id.*)"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.checks.context import ScanContext
from app.checks.util import digits_tail, first_str, jsonld_types, res
from app.domain.scoring import CheckResult
from app.services.signals import fold

DEALER_TYPES = {"AutoDealer", "AutomotiveBusiness", "MotorcycleDealer"}
GENERIC_TYPES = {"LocalBusiness", "Organization", "AutoRepair", "Store"}
PHONE_RX = re.compile(r"(?:\+|00)?\d[\d\s().-]{7,16}\d")


def _dealer_nodes(ctx: ScanContext) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for page in ctx.ok_by_role("home", "contact"):
        for node in page.jsonld:
            if (DEALER_TYPES | GENERIC_TYPES) & set(jsonld_types(node)):
                out.append((page.url, node))
    return out


def _ld_phone(node: dict[str, Any]) -> str:
    """telephone may sit on the node or inside contactPoint (valid schema.org)."""
    if node.get("telephone"):
        return first_str(node["telephone"])
    contact = node.get("contactPoint")
    for point in (contact if isinstance(contact, list) else [contact]):
        if isinstance(point, dict) and point.get("telephone"):
            return first_str(point["telephone"])
    return ""


def _has(node: dict[str, Any], field: str) -> bool:
    if field == "hours":
        return bool(node.get("openingHoursSpecification") or node.get("openingHours"))
    if field == "telephone":
        return bool(_ld_phone(node))
    return bool(node.get(field))


async def schema_dealer(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    nodes = _dealer_nodes(ctx)
    if not nodes:
        return res(spec, "fail", "No AutoDealer/LocalBusiness JSON-LD on the homepage or contact page.",
                   missing=["AutoDealer JSON-LD"])
    fields = ["name", "address", "geo", "telephone", "hours", "brand"]
    # best node = the one with most fields; dealer-specific types beat generic ones
    url, best = max(
        nodes,
        key=lambda item: (
            bool(DEALER_TYPES & set(jsonld_types(item[1]))),
            sum(_has(item[1], f) for f in fields),
        ),
    )
    present = [f for f in fields if _has(best, f)]
    missing = [f for f in fields if f not in present]
    specific = bool(DEALER_TYPES & set(jsonld_types(best)))
    if specific and len(present) >= 5:
        status = "pass"
    elif len(present) >= 3:
        status = "warn"
    else:
        status = "fail"
    if not specific and status == "pass":
        status = "warn"
    kind = "/".join(jsonld_types(best))
    return res(spec, status, f"{kind} JSON-LD has {len(present)}/6 of {', '.join(fields)}.",
               pages=[url], found=present, missing=missing, snippet=first_str(best.get("name"))[:80],
               details={"type": kind, "dealer_specific_type": specific})


async def nap(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    pages = ctx.ok_by_role("home", "contact")
    if not pages:
        return res(spec, "na", "No homepage/contact content available.")
    nodes = _dealer_nodes(ctx)
    phones_by_page = {
        p.url: {digits_tail(m) for m in PHONE_RX.findall(p.text) if len(re.sub(r"\D", "", m)) >= 9}
        for p in pages
    }
    ld = nodes[0][1] if nodes else {}
    ld_phone = digits_tail(_ld_phone(ld)) if _ld_phone(ld) else ""
    ld_name = fold(first_str(ld.get("name")))
    texts = [fold(p.text) for p in pages]
    name_found = bool(ld_name) and any(ld_name in t for t in texts)
    phone_found = bool(ld_phone) and any(ld_phone in phones for phones in phones_by_page.values())
    addr = ld.get("address") if isinstance(ld.get("address"), dict) else {}
    street = fold(first_str(addr.get("streetAddress")))
    addr_found = (not street) or any(street in t for t in texts)
    if ld and phone_found and name_found and addr_found:
        return res(spec, "pass", "Name, phone and address in JSON-LD match the visible page text.",
                   pages=[p.url for p in pages], found=["name", "telephone"] + (["address"] if street else []))
    if ld:
        missing = [n for n, ok in (("name", name_found), ("telephone", phone_found), ("address", addr_found)) if not ok]
        status = "warn" if (phone_found or name_found) else "fail"
        return res(spec, status, f"JSON-LD does not match visible text for: {', '.join(missing)}.",
                   pages=[p.url for p in pages], missing=missing)
    common = Counter(p for phones in phones_by_page.values() for p in phones).most_common(1)
    if common and common[0][1] >= 2:
        return res(spec, "warn", "No JSON-LD, but the same phone number appears on several pages.",
                   pages=[p.url for p in pages], found=["telephone (text only)"], missing=["JSON-LD business data"])
    return res(spec, "fail", "No structured business data and no consistent contact details across pages.",
               pages=[p.url for p in pages], missing=["JSON-LD", "consistent phone"])
