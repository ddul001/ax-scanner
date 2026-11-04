"""Shared check helpers: result builder, price/spec patterns, schema.org value rules."""
from __future__ import annotations

import re
from typing import Any

from app.domain.scoring import CheckResult

PRICE_RX = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[. \s]\d{3})+|\d{3,7})(?:,\d{1,2})?\s?(?:€|eur\b|euro\b|lei\b|ron\b)|(?:€|eur\b)\s?(\d{1,3}(?:[. \s]\d{3})+|\d{3,7})",
    re.I,
)
SPEC_WORDS = {
    "year": re.compile(r"\b(19[89]\d|20[0-4]\d)\b"),
    "km": re.compile(r"\d[\d.\s ]*\s?km\b", re.I),
    "fuel": re.compile(r"\b(benzin\w*|diesel|motorin\w*|hibrid\w*|hybrid\w*|electric\w*|gpl|gasolina|di[eé]sel|combustibil\w*|fuel)\b", re.I),
    "transmission": re.compile(r"\b(manual\w*|automat\w*|cutie|transmisi\w+|cambio|transmission)\b", re.I),
    "power": re.compile(r"\b\d{2,4}\s?(cp|hp|kw|cv|ps)\b", re.I),
}
VIN_RX = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
CAPTCHA_MARKERS = ("g-recaptcha", "recaptcha/api", "hcaptcha", "cf-turnstile", "data-sitekey")


def res(spec: dict[str, Any], status: str, summary: str, **kw: Any) -> CheckResult:
    return CheckResult(
        check_id=spec["id"], layer=spec["layer"], severity=spec["severity"], method=spec["method"],
        status=status, summary=summary, **kw,
    )


def share_status(share: float, pass_at: float, warn_at: float) -> str:
    if share >= pass_at:
        return "pass"
    if share >= warn_at:
        return "warn"
    return "fail"


def to_amount(raw: str) -> float | None:
    digits = re.sub(r"[. \s]", "", raw.split(",")[0])
    return float(digits) if digits.isdigit() else None


def prices_in_text(text: str) -> list[float]:
    out: list[float] = []
    for match in PRICE_RX.finditer(text):
        value = to_amount(match.group(1) or match.group(2))
        if value is not None:
            out.append(value)
    return out


def digits_tail(phone: str, n: int = 9) -> str:
    return re.sub(r"\D", "", phone)[-n:]


def jsonld_types(node: dict[str, Any]) -> list[str]:
    declared = node.get("@type")
    if isinstance(declared, str):
        return [declared]
    if isinstance(declared, list):
        return [x for x in declared if isinstance(x, str)]
    return []


def first_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or value.get("@value") or "")
    if isinstance(value, list) and value:
        return first_str(value[0])
    return ""


# ---- schema.org Offer value rules (Google structured-data guidelines for Offer) ----
_AVAILABILITY = {
    "BackOrder", "Discontinued", "InStock", "InStoreOnly", "LimitedAvailability", "MadeToOrder",
    "OnlineOnly", "OutOfStock", "PreOrder", "PreSale", "Reserved", "SoldOut",
}
_CONDITION = {"NewCondition", "UsedCondition", "DamagedCondition", "RefurbishedCondition"}
_PRICE = re.compile(r"\d+(?:\.\d+)?")
_ENUM_URL = re.compile(r"(?:https?://schema\.org/)?([A-Za-z]+)")


def valid_offer_value(field: str, value: Any) -> bool:
    """True when `value` is usable for this Offer property: numeric price, ISO 4217 currency, schema.org enum URLs."""
    if isinstance(value, bool) or value in (None, ""):
        return False
    if field == "price":
        return bool(_PRICE.fullmatch(str(value).strip()))
    if field == "priceCurrency":
        return bool(re.fullmatch(r"[A-Z]{3}", str(value)))
    if field in ("availability", "itemCondition"):
        match = _ENUM_URL.fullmatch(str(value).strip())
        return bool(match) and match.group(1) in (_AVAILABILITY if field == "availability" else _CONDITION)
    return True
