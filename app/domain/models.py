"""Pure data models for Step 0 (site classification). No I/O, no framework imports."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SiteType = Literal["dealer", "importer", "ecommerce", "marketplace", "finance"]
ClassifiedType = Literal["dealer", "importer", "ecommerce", "marketplace", "finance", "unsupported"]
SITE_TYPES: tuple[str, ...] = ("dealer", "importer", "ecommerce", "marketplace", "finance")

CLASSIFICATION_VERSION = "step0-3"


class Signals(BaseModel):
    """Deterministic signals extracted from homepage + sitemap + robots."""

    title: str = ""
    description: str = ""
    language: str | None = None
    nav_items: list[str] = Field(default_factory=list)
    text_excerpt: str = ""
    visible_text_len: int = 0
    js_shell: bool = False

    schema_types: list[str] = Field(default_factory=list)
    vehicle_schema_count: int = 0
    product_schema_count: int = 0
    offer_schema_count: int = 0

    cart_hits: int = 0
    vin_count: int = 0
    km_mentions: int = 0
    has_service_booking: bool = False
    has_dealer_locator: bool = False
    has_configurator: bool = False
    has_test_drive: bool = False
    has_post_listing: bool = False
    finance_hits: int = 0
    jsonld_summary: str = ""
    headings: list[str] = Field(default_factory=list)
    cta_texts: list[str] = Field(default_factory=list)
    footer_text: str = ""
    sitemap_samples: list[str] = Field(default_factory=list)
    seller_mentions: int = 0
    make_count: int = 0
    url_patterns: dict[str, int] = Field(default_factory=dict)  # stock/models/products/dealers
    price_count: int = 0
    price_from_count: int = 0
    price_style: Literal["none", "per_item", "from"] = "none"
    shipping_returns_hits: int = 0

    brands: list[str] = Field(default_factory=list)
    locations: int = 0
    auto_hits: int = 0

    evidence: dict[str, str] = Field(default_factory=dict)  # signal name -> example found


SIGNAL_NAMES: frozenset[str] = (frozenset(Signals.model_fields) - {"evidence", "text_excerpt"}) | {
    "navigation",
    "sample_urls_from_sitemap",
    "main_buttons_and_calls_to_action",
    "schema_org_summary",
}


class HeuristicResult(BaseModel):
    scores: dict[str, float]
    probs: dict[str, float]
    top: SiteType
    margin: float
    confidence: float
    secondary: list[SiteType] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LlmEvidence(BaseModel):
    signal: str
    value: str = ""


class LlmFacts(BaseModel):
    """Yes/no questions the model answers; the type is derived from them deterministically."""

    is_automotive_related: bool
    is_financial_institution: bool = False  # bank, leasing/renting, consumer credit, captive finance, insurer
    is_manufacturer_or_official_importer: bool = False  # the brand itself, not a reseller
    hosts_third_party_listings: bool = False  # many independent sellers publish ads
    owns_vehicle_stock: bool = False  # sells vehicles it owns, per-vehicle listings
    sells_auto_parts_online: bool = False  # webshop for parts/accessories/tyres


def derive_type(facts: LlmFacts) -> str | None:
    """Map fact answers to a site type.

    Priority order matters: a brand site with dealer listings is still an
    importer; a lender with a car catalogue is still finance.
    """
    if facts.is_financial_institution:
        return "finance"
    if facts.is_manufacturer_or_official_importer:
        return "importer"
    if facts.hosts_third_party_listings:
        return "marketplace"
    if facts.owns_vehicle_stock:
        return "dealer"
    if facts.sells_auto_parts_online:
        return "ecommerce"
    if not facts.is_automotive_related:
        return "unsupported"
    return None  # facts inconclusive: keep the model's own label


class LlmClassification(BaseModel):
    type: ClassifiedType
    confidence: float = Field(ge=0, le=1)
    facts: LlmFacts | None = None
    model_type: str | None = None  # label the model gave before facts overrode it
    secondary_types: list[SiteType] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    locations: int | None = None
    evidence: list[LlmEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _lift_flat_facts(cls, data: Any) -> Any:
        """Muse (without structured output) answers the fact booleans at the top level; accept both shapes."""
        if isinstance(data, dict) and not data.get("facts") and "is_automotive_related" in data:
            data = {**data, "facts": {k: data[k] for k in LlmFacts.model_fields if k in data}}
        return data

    @model_validator(mode="after")
    def _derive_from_facts(self) -> LlmClassification:
        if self.facts is not None and self.model_type is None:
            self.model_type = self.type
            derived = derive_type(self.facts)
            if derived:
                self.type = derived  # type: ignore[assignment]
        return self


class EvidenceItem(BaseModel):
    signal: str
    value: str
    source: Literal["deterministic", "llm"] = "deterministic"


class Classification(BaseModel):
    type: ClassifiedType
    confidence: float
    secondary_types: list[SiteType] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    locations: int = 0
    language: str | None = None
    method: Literal["deterministic", "deterministic+llm"]
    needs_confirmation: bool
    alternatives: list[dict[str, Any]] = Field(default_factory=list)  # top-2 [{type, probability}]
    evidence: list[EvidenceItem] = Field(default_factory=list)
    signals: dict[str, Any] = Field(default_factory=dict)
    heuristic: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] | None = None
    user_hint: str | None = None
    confirmed_by_user: bool = False
    js_rendered: bool = False
    version: str = CLASSIFICATION_VERSION
