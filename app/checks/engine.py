"""Check registry + runner. One engine for all site types: the template (yaml) decides which checks apply."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml

from app.checks import actions_trust_protocol as atp
from app.checks import brand, discovery, identity, inventory, journey, shop, webmcp
from app.checks.context import ScanContext
from app.checks.util import res
from app.domain.scoring import CheckResult, Report, build_report

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

REGISTRY = {
    "disc.robots_ai": discovery.robots_ai,
    "disc.waf_ua": discovery.waf_ua,
    "disc.sitemap": discovery.sitemap,
    "disc.llms_txt": discovery.llms_txt,
    "disc.no_js": discovery.no_js,
    "id.schema_dealer": identity.schema_dealer,
    "id.nap": identity.nap,
    "inv.vdp_urls": inventory.vdp_urls,
    "inv.schema_vehicle": inventory.schema_vehicle,
    "inv.schema_offer": inventory.schema_offer,
    "inv.fields": inventory.fields,
    "inv.price_readable": inventory.price_readable,
    "inv.price_consistency": inventory.price_consistency,
    "act.test_drive": atp.test_drive,
    "act.forms_semantic": atp.forms_semantic,
    "trust.https": atp.https,
    "proto.aap_card": atp.aap_card,
    "ux.j_find": journey.j_find,
    "ux.j_act": journey.j_act,
    "ux.j_dealer": journey.j_dealer,
    **brand.REGISTRY,
    **shop.REGISTRY,
    **webmcp.REGISTRY,
}
TYPE_OVERRIDES = {
    "importer": brand.OVERRIDES,
    # same check id, implementation specific to the site type
    "ecommerce": {**shop.OVERRIDES, "ux.j_find": journey.j_find_shop},
}
IMPLEMENTED_TYPES = ("dealer", "importer", "ecommerce")


def load_template(site_type: str) -> dict[str, Any]:
    return yaml.safe_load((TEMPLATES / f"{site_type}.yaml").read_text(encoding="utf-8"))


async def _one(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    fn = TYPE_OVERRIDES.get(ctx.site_type, {}).get(spec["id"]) or REGISTRY.get(spec["id"])
    if fn is None:
        return res(spec, "skipped", "Not implemented in this build yet.")
    try:
        return await fn(ctx, spec)
    except Exception as e:  # noqa: BLE001 - one broken check must not sink the report
        log.exception("check %s crashed", spec["id"])
        return res(spec, "skipped", f"Check crashed: {type(e).__name__}", details={"error": str(e)[:200]})


async def run_checks(ctx: ScanContext, template: dict[str, Any]) -> list[CheckResult]:
    """Deterministic checks run in order; Agent Journeys (method J, slow LLM loops) run concurrently afterwards."""
    specs = template["checks"]
    plain = [s for s in specs if s["method"] != "J"]
    journeys = [s for s in specs if s["method"] == "J"]
    done = {s["id"]: await _one(ctx, s) for s in plain}
    if journeys:
        for spec, result in zip(journeys, await asyncio.gather(*(_one(ctx, s) for s in journeys))):
            done[spec["id"]] = result
    return [done[s["id"]] for s in specs]  # keep template order


def make_report(site_type: str, template: dict[str, Any], results: list[CheckResult]) -> Report:
    return build_report(site_type, template["weights"], results)
