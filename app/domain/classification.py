"""Pure scoring: signals -> heuristic type probabilities, and heuristic+LLM combination."""
from __future__ import annotations

import math

from app.domain.models import (
    SIGNAL_NAMES,
    SITE_TYPES,
    Classification,
    EvidenceItem,
    HeuristicResult,
    LlmClassification,
    Signals,
)

AUTO_SCHEMA_TYPES = {"AutoDealer", "AutomotiveBusiness", "AutoRepair", "MotorcycleDealer"}
TEMPERATURE = 2.0
EVIDENCE_SATURATION = 5.0  # top raw score at which heuristic confidence is no longer discounted
SECONDARY_MIN_SCORE = 4.0
AGREEMENT_BONUS = 0.05  # added when the heuristic backs Muse (scaled by its own confidence)
DISAGREEMENT_WEIGHT = 0.25  # confidence removed per unit of heuristic confidence when it contradicts Muse
HINT_BONUS = 0.10


def is_unsupported(signals: Signals) -> bool:
    """No automotive signal at all (and we have actually seen page content)."""
    if signals.js_shell or signals.finance_hits >= 3:
        return False
    return signals.auto_hits == 0 and signals.vin_count == 0 and signals.vehicle_schema_count == 0


def heuristic(signals: Signals) -> HeuristicResult:
    stock = signals.url_patterns.get("stock", 0)
    models = signals.url_patterns.get("models", 0)
    products = signals.url_patterns.get("products", 0)
    dealers = signals.url_patterns.get("dealers", 0)
    listings = signals.url_patterns.get("listings", 0)
    types = set(signals.schema_types)
    notes: list[str] = []
    scores = {t: 0.0 for t in SITE_TYPES}

    def add(target: str, pts: float, note: str) -> None:
        scores[target] += pts
        notes.append(f"{target} +{pts:g}: {note}")

    # dealer
    if signals.vin_count >= 1:
        add("dealer", 3, f"{signals.vin_count} VIN-like identifiers")
    if stock >= 3:
        add("dealer", 2, f"{stock} stock/inventory URLs")
    if signals.has_service_booking:
        add("dealer", 2, "service booking link")
    if signals.vehicle_schema_count >= 1:
        add("dealer", 2, "Car/Vehicle schema.org")
    if AUTO_SCHEMA_TYPES & types:
        add("dealer", 1, "AutoDealer/AutomotiveBusiness schema.org")
    if signals.price_count >= 3 and signals.km_mentions >= 1 and signals.vin_count >= 1:
        add("dealer", 1, "per-vehicle prices with mileage")
    if 1 <= signals.locations <= 5:
        add("dealer", 0.5, f"{signals.locations} location(s)")

    # importer
    if signals.has_dealer_locator:
        add("importer", 3, "dealer locator")
    if dealers >= 1:
        add("importer", 1, f"{dealers} dealer-network URLs")
    if signals.has_configurator:
        add("importer", 2, "configurator")
    if models >= 3:
        add("importer", 2, f"{models} model-range URLs")
    if signals.price_style == "from" and signals.vin_count == 0:
        add("importer", 2, "'from X' pricing without VIN stock")
    if "Organization" in types and signals.vin_count == 0 and not signals.cart_hits:
        add("importer", 1, "Organization schema.org")
    if "Brand" in types and signals.vin_count == 0 and not signals.cart_hits:
        add("importer", 1, "Brand schema.org")
    if signals.locations > 5:
        add("importer", 1, f"{signals.locations} locations listed")

    # e-commerce
    if signals.cart_hits >= 1:
        add("ecommerce", 4, "cart / add-to-cart")
    if signals.product_schema_count >= 1:
        add("ecommerce", 3, "Product schema.org")
    if "OnlineStore" in types:
        add("ecommerce", 2, "OnlineStore schema.org")
    if products >= 3:
        add("ecommerce", 2, f"{products} product URLs")
    if signals.shipping_returns_hits >= 4:
        add("ecommerce", 1, "shipping/returns content")

    # marketplace: many sellers, public "post an ad", listing pages
    if signals.has_post_listing:
        add("marketplace", 4, "'post an ad' / 'sell your car' link")
    if listings >= 3:
        add("marketplace", 2, f"{listings} classified-listing URLs")
    if signals.seller_mentions >= 3:
        add("marketplace", 1, f"{signals.seller_mentions} seller mentions")
    if signals.make_count >= 8:
        add("marketplace", 2, f"{signals.make_count} different car makes")
    if signals.make_count >= 15:
        add("marketplace", 3, "aggregates a very wide range of makes")

    # finance: banks, leasing/renting, consumer credit, captive finance
    if signals.finance_hits >= 3:
        add("finance", 3, f"{signals.finance_hits} finance terms in title/navigation/legal text")
    if signals.finance_hits >= 6:
        add("finance", 2, "dense finance vocabulary")

    def penalise(target: str, pts: float, note: str) -> None:
        if scores[target] > 0:
            scores[target] = max(0.0, scores[target] - pts)
            notes.append(f"{target} -{pts:g}: {note}")

    # cross-penalties from the decision table
    if signals.vin_count >= 3 and not signals.cart_hits:
        penalise("importer", 2, "VIN-level stock is atypical for importers")
    if signals.cart_hits and signals.vin_count == 0 and signals.vehicle_schema_count == 0:
        penalise("dealer", 2, "cart without vehicle stock")
    if (
        signals.finance_hits >= 3
        and signals.vin_count == 0
        and signals.url_patterns.get("stock", 0) < 3
        and not signals.cart_hits
    ):
        penalise("dealer", 2, "finance vocabulary without vehicle stock")
        penalise("importer", 2, "finance vocabulary without a brand range")
        penalise("marketplace", 2, "finance vocabulary without third-party listings")
    if signals.make_count >= 8:
        penalise("importer", 2, "an importer represents one brand, not many makes")
    if signals.has_post_listing:
        penalise("dealer", 2, "open ad posting means many sellers, not one stock")
        penalise("importer", 2, "open ad posting means many sellers, not one brand")

    final_scores = dict(scores)
    exps = {k: math.exp(v / TEMPERATURE) for k, v in final_scores.items()}
    total = sum(exps.values())
    probs = {k: v / total for k, v in exps.items()}
    ranked = sorted(SITE_TYPES, key=lambda k: (final_scores[k], probs[k]), reverse=True)
    top = ranked[0]
    margin = probs[top] - probs[ranked[1]]
    confidence = probs[top] * min(1.0, final_scores[top] / EVIDENCE_SATURATION)
    secondary = [
        k for k in ranked[1:] if final_scores[k] >= max(SECONDARY_MIN_SCORE, 0.5 * final_scores[top])
    ]
    return HeuristicResult(
        scores={k: round(v, 2) for k, v in final_scores.items()},
        probs={k: round(v, 3) for k, v in probs.items()},
        top=top,  # type: ignore[arg-type]
        margin=round(margin, 3),
        confidence=round(confidence, 3),
        secondary=secondary,  # type: ignore[arg-type]
        notes=notes,
    )


def deterministic_evidence(signals: Signals, heur: HeuristicResult) -> list[EvidenceItem]:
    items = [EvidenceItem(signal=k, value=v) for k, v in signals.evidence.items()]
    items.extend(EvidenceItem(signal="heuristic", value=n) for n in heur.notes[:6])
    return items


def validated_llm_evidence(llm: LlmClassification) -> list[EvidenceItem]:
    """Keep only LLM evidence that points at a real signal name (anti-hallucination)."""
    out = []
    for ev in llm.evidence:
        name = ev.signal.split(".", 1)[0]
        if name in SIGNAL_NAMES:
            out.append(EvidenceItem(signal=ev.signal, value=ev.value[:200], source="llm"))
    return out


def filter_brands(llm_brands: list[str], signals: Signals) -> list[str]:
    """LLM brands are accepted only if they literally appear in what we showed it."""
    haystack = " ".join(
        [signals.title, signals.description, " ".join(signals.nav_items), signals.text_excerpt]
        + [" ".join(signals.brands)]
    ).lower()
    return [b for b in llm_brands if b.strip() and b.lower() in haystack]


def combine(
    signals: Signals,
    heur: HeuristicResult,
    llm: LlmClassification | None,
    *,
    hint: str | None = None,
    threshold: float = 0.7,
    js_rendered: bool = False,
) -> Classification:
    if is_unsupported(signals):
        # Page has real content and no automotive signal: nothing to scan.
        return _build(
            signals, heur, llm, "unsupported", 0.9, [], hint, threshold, js_rendered,
            force_confirm=False,
        )

    notes: list[str] = []
    if llm is None:
        typ, conf = heur.top, heur.confidence
        secondary = list(heur.secondary)
    else:
        # Muse decides the type; the heuristic only adjusts confidence (it is much weaker on thin or mixed pages).
        typ = llm.type
        secondary = [t for t in llm.secondary_types if t != typ]
        for t in fact_supported_types(llm):
            if t != typ and t not in secondary:
                secondary.append(t)
        if heur.top == typ:
            conf = llm.confidence + AGREEMENT_BONUS * heur.confidence
        elif heur.top in secondary:
            conf = llm.confidence  # heuristic found a role Muse also reports as secondary: not a conflict
            notes.append(f"heuristic leaned {heur.top} (also a secondary role per Muse)")
        else:
            conf = llm.confidence - DISAGREEMENT_WEIGHT * heur.confidence
            notes.append(f"heuristic disagreed: {heur.top} (confidence {heur.confidence:g}) vs Muse {typ}")

    if typ == "unsupported" and llm is not None and llm.facts is not None and llm.facts.is_automotive_related:
        # a car-related site that fits no type clearly (e.g. a quote-only wheel catalog): let the user choose, do not refuse
        typ = heur.top
        conf = min(conf, threshold - 0.05)
        notes.append("Muse labelled the site unsupported although it is automotive-related: asking for confirmation")

    if hint == typ:
        conf += HINT_BONUS
    conf = round(min(1.0, max(0.0, conf)), 2)
    out = _build(signals, heur, llm, typ, conf, secondary, hint, threshold, js_rendered)
    out.evidence += [EvidenceItem(signal="heuristic", value=n) for n in notes]
    return out


def fact_supported_types(llm: LlmClassification) -> list[str]:
    facts = llm.facts
    if facts is None:
        return []
    pairs = [
        ("finance", facts.is_financial_institution),
        ("importer", facts.is_manufacturer_or_official_importer),
        ("marketplace", facts.hosts_third_party_listings),
        ("dealer", facts.owns_vehicle_stock),
        ("ecommerce", facts.sells_auto_parts_online),
    ]
    return [t for t, on in pairs if on]


def _build(
    signals: Signals,
    heur: HeuristicResult,
    llm: LlmClassification | None,
    typ: str,
    conf: float,
    secondary: list[str],
    hint: str | None,
    threshold: float,
    js_rendered: bool,
    force_confirm: bool | None = None,
) -> Classification:
    ranked = sorted(heur.probs, key=lambda k: heur.probs[k], reverse=True)[:2]
    evidence = deterministic_evidence(signals, heur)
    brands = list(signals.brands)
    locations = signals.locations
    if llm:
        evidence += validated_llm_evidence(llm)
        known = {x.lower() for x in brands}
        brands += [b for b in filter_brands(llm.brands, signals) if b.lower() not in known]
        if llm.locations is not None and not locations:
            locations = llm.locations
    needs = (conf < threshold) if force_confirm is None else force_confirm
    if typ == "unsupported":
        needs = False
    return Classification(
        type=typ,  # type: ignore[arg-type]
        confidence=conf,
        secondary_types=secondary,  # type: ignore[arg-type]
        brands=brands[:10],
        locations=locations,
        language=signals.language,
        method="deterministic+llm" if llm else "deterministic",
        needs_confirmation=needs,
        alternatives=[{"type": k, "probability": heur.probs[k]} for k in ranked],
        evidence=evidence,
        signals=signals.model_dump(exclude={"text_excerpt"}),
        heuristic=heur.model_dump(),
        llm=llm.model_dump() if llm else None,
        user_hint=hint,
        js_rendered=js_rendered,
    )
