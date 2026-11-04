"""All fix generators in one entry point."""
from __future__ import annotations

from app.checks.context import AI_ROBOT_TOKENS, ScanContext
from app.domain.scoring import CheckResult
from app.fixes.base import FixDraft
from app.fixes.files import build_llms, build_robots
from app.fixes.jsonld import _gain, generate_fixes as jsonld_fixes


async def generate_all(
    ctx: ScanContext, results: list[CheckResult], weights: dict[str, float], brands: list[str] | None = None
) -> list[FixDraft]:
    if ctx.site_type != "dealer":  # generators are written for dealer sites (stock/service/VDP); no brand fixes yet
        return []
    by_id = {r.check_id: r for r in results}
    drafts = jsonld_fixes(ctx, results, weights, brands)

    llms = by_id.get("disc.llms_txt")
    if llms and llms.status in ("warn", "fail"):
        draft = await build_llms(ctx)
        draft.est_gain = _gain(ctx.site_type, weights, results, {"disc.llms_txt"})
        drafts.append(draft)

    robots = by_id.get("disc.robots_ai")
    if robots and robots.status == "fail":  # warn = training-only blocks: a policy decision, no fix proposed
        blocked = robots.details.get("blocked", {})
        bots = [b for b in AI_ROBOT_TOKENS["retrieval"] if b in blocked]
        if bots and robots.pages:
            draft = build_robots(ctx, bots, robots.pages)
            draft.est_gain = _gain(ctx.site_type, weights, results, {"disc.robots_ai"})
            drafts.append(draft)
    return drafts
