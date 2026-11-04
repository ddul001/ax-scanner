"""Task definitions and deterministic verification of journey answers (the agent's claims are checked against the page)."""
from __future__ import annotations

import re
from typing import Any

from app.checks.context import Page
from app.checks.util import SPEC_WORDS, VIN_RX, prices_in_text
from app.journey.agent import JourneyAnswer
from app.journey.browser import HttpBrowser, build_view
from app.services.signals import fold

MAX_PRICE_EUR = 30000
DEALER_TASKS = {
    "find": (
        f"Find a used car priced under {MAX_PRICE_EUR:,} EUR on this dealer's website (a hybrid SUV would be ideal, but "
        "any used car under that price is acceptable). Open its own vehicle page and report that page's URL, the price, "
        "the mileage in km and the VIN, exactly as shown on the page."
    ),
    "act": (
        "Find where a customer can book a test drive for a car in stock. Open the booking form page and list the name "
        "of every field the customer would have to fill in. Do NOT submit anything; just read the form."
    ),
}


def _numbers(text: str) -> set[int]:
    return {int(re.sub(r"\D", "", m)) for m in re.findall(r"\d[\d.\s ]*\d|\d", text) if re.sub(r"\D", "", m)}


def _ld_values(page: Page, *keys: str) -> list[Any]:
    out = []
    for node in page.jsonld:
        for key in keys:
            value = node.get(key)
            if isinstance(value, dict):
                value = value.get("value") or value.get("price")
            if value not in (None, ""):
                out.append(value)
    return out


async def verify_find(ans: JourneyAnswer | None, browser: HttpBrowser) -> dict[str, Any]:
    if ans is None or not ans.found:
        return {"status": "fail", "summary": "The agent could not find a vehicle with its price, mileage and VIN.",
                "agent_notes": (ans.notes if ans else "")[:200]}
    if not ans.url:
        return {"status": "fail", "summary": "The agent reported a vehicle without a page URL."}
    page = await browser.fetch_page(ans.url)
    if page is None or not page.ok:
        return {"status": "fail", "summary": "The page the agent reported does not exist or cannot be opened (not a real vehicle page).",
                "url": ans.url}
    text = page.text
    page_prices = set(prices_in_text(text))
    for value in _ld_values(page, "price"):
        try:
            page_prices.add(float(str(value).replace(",", ".")))
        except ValueError:
            pass
    km_nums = {
        int(re.sub(r"\D", "", m.group(0)))
        for m in SPEC_WORDS["km"].finditer(text) if re.sub(r"\D", "", m.group(0))
    }
    for value in _ld_values(page, "mileageFromOdometer"):
        try:
            km_nums.add(int(float(str(value))))
        except ValueError:
            pass
    page_vin = {v for v in VIN_RX.findall(text.upper()) if any(c.isdigit() for c in v)} | {
        str(v).upper() for v in _ld_values(page, "vehicleIdentificationNumber")
    }
    is_vehicle_page = bool(page_prices) and (bool(km_nums) or bool(page_vin) or bool(page.jsonld))
    checks = {
        "page_is_vehicle": is_vehicle_page,
        "price_matches": ans.price is not None and any(abs(p - ans.price) <= 1 for p in page_prices),
        "mileage_matches": ans.mileage_km is not None and ans.mileage_km in km_nums,
        "vin_matches": (ans.vin.upper() in page_vin) if ans.vin else not page_vin,
        "within_budget": ans.price is not None and ans.price < MAX_PRICE_EUR and (ans.currency or "EUR").upper() in ("EUR", "€"),
    }
    core = checks["page_is_vehicle"] and checks["price_matches"] and checks["mileage_matches"]
    if core and checks["vin_matches"] and checks["within_budget"]:
        status, summary = "pass", "The agent found a real vehicle under the budget and its price, mileage and VIN match the page."
    elif checks["page_is_vehicle"] and (checks["price_matches"] or checks["mileage_matches"]):
        bad = [k for k, v in checks.items() if not v]
        status, summary = "warn", f"The agent reached a real vehicle page but some answers did not match: {', '.join(bad)}."
    else:
        status, summary = "fail", "The agent's answer does not match the page it reported."
    return {"status": status, "summary": summary, "url": ans.url, "checks": checks,
            "page_values": {"prices": sorted(page_prices)[:3], "mileage": sorted(km_nums)[:3], "vin": sorted(page_vin)[:2]}}


def tokens_ok(label: str) -> bool:
    """Ignore blank fields and site-search boxes (they are not part of a booking form)."""
    return bool(re.search(r"[a-z0-9]{3,}", label)) and not re.search(r"\b(cautare|search|buscar|term)\b", label)


async def verify_act(ans: JourneyAnswer | None, browser: HttpBrowser) -> dict[str, Any]:
    if ans is None or not ans.found:
        return {"status": "fail", "summary": "The agent could not find a test-drive booking form.",
                "agent_notes": (ans.notes if ans else "")[:200]}
    url = ans.form_url or ans.url
    page = await browser.fetch_page(url) if url else None
    if page is None or not page.ok:
        return {"status": "fail", "summary": "The form page the agent reported cannot be opened.", "url": url}
    forms = build_view(page).forms
    real = {fold(f"{x['label']} {x['name']}") for f in forms for x in f["fields"] if x["type"] not in ("checkbox", "radio")}
    real = {r for r in real if tokens_ok(r)}
    if not real:
        return {"status": "fail", "summary": "The reported page has no fillable form.", "url": url}
    claimed = [fold(c) for c in ans.form_fields if c.strip()]
    stop = {"selectati", "selecteaza", "please", "select", "campul", "field", "checkbox", "input", "datele", "pentru"}

    def tokens(value: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]{4,}", value) if t not in stop}

    def match(candidate: str, reference: str) -> bool:
        candidate_tokens, reference_tokens = tokens(candidate), tokens(reference)
        return bool(candidate_tokens and reference_tokens and candidate_tokens & reference_tokens)

    hit_real = sum(1 for r in real if any(match(c, r) for c in claimed))
    hit_claim = sum(1 for c in claimed if any(match(c, r) for r in real))
    recall = hit_real / len(real)
    precision = hit_claim / len(claimed) if claimed else 0.0
    status = "pass" if recall >= 0.6 and precision >= 0.6 else "warn" if recall >= 0.3 and precision >= 0.3 else "fail"
    summary = {
        "pass": "The agent found the booking form and listed its fields correctly (nothing was submitted).",
        "warn": "The agent found the form but listed only part of its fields.",
        "fail": "The agent's field list does not match the form.",
    }[status]
    return {"status": status, "summary": summary, "url": url, "recall": round(recall, 2), "precision": round(precision, 2),
            "page_fields": sorted(real)[:12], "claimed_fields": ans.form_fields[:12]}


# ---- brand / importer: "find the nearest authorized dealer" ----
MARKET_CITY = {
    "ro": "Bucharest", "es": "Madrid", "at": "Vienna", "fr": "Paris", "de": "Berlin", "it": "Rome",
    "nl": "Amsterdam", "pl": "Warsaw", "pt": "Lisbon", "be": "Brussels", "ch": "Zurich", "cz": "Prague",
    "hu": "Budapest", "bg": "Sofia", "gr": "Athens", "uk": "London", "ie": "Dublin", "se": "Stockholm",
    "dk": "Copenhagen", "hr": "Zagreb",
}
CITY_ALIASES = {
    "Bucharest": ("bucuresti", "bucharest"), "Vienna": ("wien", "vienna"), "Rome": ("roma", "rome"),
    "Warsaw": ("warszawa", "warsaw"), "Lisbon": ("lisboa", "lisbon"),
    "Brussels": ("bruxelles", "brussel", "brussels"), "Prague": ("praha", "prague"),
    "Zurich": ("zurich", "zuerich"), "Athens": ("athina", "athens"),
}


def market_city(host: str) -> str | None:
    return MARKET_CITY.get(host.rsplit(".", 1)[-1].lower())


def importer_task(host: str, model: str | None) -> str:
    city = market_city(host)
    where = f"in {city}" if city else "in the capital city of the country this website serves"
    what = f" that sells the {model}" if model else ""
    return (
        f"A customer {where} wants to see a car of this brand. Find the nearest authorized dealer{what} using this website's "
        "dealer locator or dealer network pages. Open the dealer's own entry or contact page and report the dealer's name, "
        "address and phone number (or email), exactly as shown on the page. Do NOT submit anything; just read."
    )


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


async def verify_dealer(ans: JourneyAnswer | None, browser: HttpBrowser, city: str | None = None) -> dict[str, Any]:
    if ans is None or not ans.found or not ans.dealer_name:
        return {"status": "fail", "summary": "The agent could not find an authorized dealer with its contact details.",
                "agent_notes": (ans.notes if ans else "")[:200]}
    if not ans.url:
        return {"status": "fail", "summary": "The agent reported a dealer without a page URL."}
    page = await browser.fetch_page(ans.url)
    if page is None or not page.ok:
        return {"status": "fail", "summary": "The page the agent reported does not exist or cannot be opened.", "url": ans.url}
    text = fold(page.text)
    name_tokens = [
        t for t in re.findall(r"[a-z0-9]{3,}", fold(ans.dealer_name))
        if t not in {"dealer", "autohaus", "auto", "concesionario"}
    ]
    name_ok = bool(name_tokens) and sum(t in text for t in name_tokens) / len(name_tokens) >= 0.6
    tail = _digits(ans.phone)[-9:]
    phone_ok = len(tail) >= 7 and tail in _digits(page.text)
    email_ok = bool(ans.email) and fold(ans.email) in text
    street_tokens = [t for t in re.findall(r"[a-z0-9]{4,}", fold(ans.address or ""))][:6]
    address_ok = bool(street_tokens) and sum(t in text for t in street_tokens) / len(street_tokens) >= 0.5
    aliases = CITY_ALIASES.get(city or "", (fold(city),) if city else ())
    in_city = bool(aliases) and any(a in fold(ans.address or "") or a in text for a in aliases)
    checks = {"name_on_page": name_ok, "phone_or_email_on_page": phone_ok or email_ok, "address_on_page": address_ok,
              "in_requested_city": in_city if aliases else None}
    if name_ok and (phone_ok or email_ok) and address_ok:
        status, summary = "pass", "The agent found a dealer and its name, address and contact match the page."
    elif name_ok and (phone_ok or email_ok or address_ok):
        bad = [k for k, v in checks.items() if v is False]
        status, summary = "warn", f"The agent reached a real dealer page but some answers did not match the page: {', '.join(bad) or 'partial details'}."
    else:
        status, summary = "fail", "The agent's dealer details do not match the page it reported."
    return {"status": status, "summary": summary, "url": ans.url, "checks": checks, "city": city}


# ---- online shop: "find a product under a budget" ----
def shop_budget(prices: list[float]) -> int | None:
    """A budget a little above the cheapest product we saw, rounded up to a round number (None when no price was seen)."""
    if not prices:
        return None
    raw = min(prices) * 1.5
    step = 10 if raw < 200 else 50 if raw < 1000 else 100
    return int(-(-raw // step) * step)


def shop_task(budget: int | None, currency: str, example: str | None) -> str:
    cost = f"costs less than {budget} {currency}" if budget else "has a clearly shown price"
    like = f" It should be something like: '{example}'." if example else ""
    return (
        f"Find a product in this online shop that {cost} and can be ordered or requested.{like} Open that product's own page "
        "and report its URL, name, price, currency and availability exactly as shown on the page. Do NOT add anything to a cart "
        "and do NOT submit anything; just read."
    )


async def verify_product(ans: JourneyAnswer | None, browser: HttpBrowser, budget: int | None) -> dict[str, Any]:
    if ans is None or not ans.found:
        return {"status": "fail", "summary": "The agent could not find a product with its price and availability.",
                "agent_notes": (ans.notes if ans else "")[:200]}
    if not ans.url:
        return {"status": "fail", "summary": "The agent reported a product without a page URL."}
    page = await browser.fetch_page(ans.url)
    if page is None or not page.ok:
        return {"status": "fail", "summary": "The page the agent reported does not exist or cannot be opened.", "url": ans.url}
    text = fold(page.text)
    prices = set(prices_in_text(page.text))
    for node in page.jsonld:
        offers = node.get("offers")
        for offer in (offers if isinstance(offers, list) else [offers, node]):
            if isinstance(offer, dict) and offer.get("price") not in (None, ""):
                try:
                    prices.add(float(str(offer["price"]).replace(",", ".")))
                except ValueError:
                    pass
    name_tokens = [t for t in re.findall(r"[a-z0-9]{3,}", fold(ans.title or "")) if not t.isdigit()][:8]
    low = page.html.lower()
    is_product = bool(prices) and (
        any("Product" in str(n.get("@type")) for n in page.jsonld)
        or any(k in low for k in ("add to cart", "adauga in cos", "cere oferta", "cere ofert", "añadir al carrito", "in den warenkorb"))
    )
    checks = {
        "page_is_product": is_product,
        "price_matches": ans.price is not None and any(abs(p - ans.price) <= 1 for p in prices),
        "name_on_page": bool(name_tokens) and sum(t in text for t in name_tokens) / len(name_tokens) >= 0.6,
        "within_budget": ans.price is not None and (budget is None or ans.price < budget),
        "availability_stated": bool(ans.availability) and (
            fold(ans.availability) in text
            or bool(re.search(r"stoc|stock|disponib|available|lager|cere oferta|oferta", text))
        ),
    }
    core = checks["page_is_product"] and checks["price_matches"] and checks["name_on_page"]
    if core and checks["within_budget"]:
        status, summary = "pass", "The agent found a real product and its name and price match the page."
    elif checks["page_is_product"] and checks["price_matches"]:
        bad = [k for k, v in checks.items() if not v]
        status, summary = "warn", f"The agent reached a real product page but some answers did not match: {', '.join(bad)}."
    else:
        status, summary = "fail", "The agent's answer does not match the page it reported."
    return {"status": status, "summary": summary, "url": ans.url, "checks": checks, "budget": budget, "page_prices": sorted(prices)[:3]}
