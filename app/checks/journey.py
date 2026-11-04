"""Agent UX layer: a real LLM agent tries the task; we verify its claims against the pages (ux.j_*)."""
from __future__ import annotations

from typing import Any

from app.checks.context import ScanContext
from app.checks.util import prices_in_text, res
from app.config import settings
from app.domain.scoring import CheckResult
from app.journey.agent import run_journey
from app.journey.browser import HttpBrowser
from app.journey.tasks import (
    DEALER_TASKS, importer_task, market_city, shop_budget, shop_task, verify_act, verify_dealer, verify_find, verify_product,
)

VERIFIERS = {"find": verify_find, "act": verify_act}
RANK = {"pass": 3, "warn": 2, "fail": 1, "skipped": 0}
RETRY_HINT = (
    " A previous attempt did not finish (it got stuck or an error interrupted it). Take a different route from the "
    "homepage and do not reopen pages you already visited."
)


def _hint_urls(ctx: ScanContext) -> list[str]:
    """Pages the discovery step identified (dealer locator, test drive, contact, ...): shown first in the agent's link list."""
    return [
        entry["url"]
        for role, entry in ctx.link_resolution.items()
        if role != "model" and isinstance(entry, dict) and entry.get("url")
    ]


async def _attempt(
    ctx: ScanContext, spec: dict[str, Any], task: str, goal: str | None, budget: int | None
) -> tuple[CheckResult, str]:
    """One run of the agent. Returns the check result and why the run stopped (finished, loop, llm_error, ...)."""
    llm = ctx.llm
    if llm is None or not getattr(llm, "configured", False):
        return res(spec, "skipped", "Agent Journey needs Muse Spark (META_API_KEY not configured)."), "not_configured"
    fetcher = ctx.fetcher_factory()
    try:
        browser = HttpBrowser(
            fetcher, ctx.robots, ctx.host, delay_s=settings.journey_delay_s, site_type=ctx.site_type,
            priority_urls=frozenset(_hint_urls(ctx)),
        )
        run = await run_journey(
            spec["id"], goal or DEALER_TASKS[task], ctx.home.url, browser, llm,
            max_steps=settings.journey_max_steps, budget_s=settings.journey_budget_s,
            effort=settings.journey_reasoning_effort or None,
        )
        if run.stop_reason == "llm_error":
            return res(spec, "skipped", f"Agent Journey could not run: Muse call failed ({run.error}).",
                       details={"journey": run.model_dump()}), run.stop_reason
        if task == "dealer":
            verdict = await verify_dealer(run.answer, browser, market_city(ctx.host))
        elif task == "shop":
            verdict = await verify_product(run.answer, browser, budget)
        else:
            verdict = await VERIFIERS[task](run.answer, browser)
    finally:
        await fetcher.aclose()
    why = "" if run.stop_reason == "finished" else f" Run stopped early: {run.stop_reason}."
    status = verdict.pop("status")
    summary = verdict.pop("summary")
    return res(spec, status, f"{summary}{why} ({len(run.steps) - 1} steps, {run.duration_ms // 1000}s)",
               pages=run.path[:8], missing=run.blockers, details={"journey": run.model_dump(), "verification": verdict}), run.stop_reason


async def _journey(
    ctx: ScanContext, spec: dict[str, Any], task: str, goal: str | None = None, budget: int | None = None
) -> CheckResult:
    """The question is whether an agent CAN do the task: a run that ended in a loop or a Muse error gets one more attempt and the
    best verdict counts. Both attempts are recorded in details.attempts."""
    base_goal = goal or DEALER_TASKS[task]
    best, stop = await _attempt(ctx, spec, task, base_goal, budget)
    attempts = [{"status": best.status, "stop_reason": stop, "summary": best.summary[:160]}]
    if settings.journey_retry and best.status != "pass" and stop in ("loop", "llm_error"):
        second, stop2 = await _attempt(ctx, spec, task, base_goal + RETRY_HINT, budget)
        attempts.append({"status": second.status, "stop_reason": stop2, "summary": second.summary[:160]})
        if RANK[second.status] > RANK[best.status]:
            best = second
            best.summary += " (second attempt)"
    best.details = {**best.details, "attempts": attempts}
    return best


async def j_find(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    return await _journey(ctx, spec, "find")


async def j_act(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    return await _journey(ctx, spec, "act")


def _model_name(ctx: ScanContext) -> str | None:
    """A model the brand sells, read from the first model page we crawled (h1), to make the task concrete."""
    for page in ctx.ok_by_role("model"):
        h1 = page.tree.css_first("h1")
        name = " ".join(h1.text(strip=True).split()) if h1 else ""
        if 2 <= len(name) <= 40:
            return name
    return None


async def j_dealer(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    return await _journey(ctx, spec, "dealer", importer_task(ctx.host, _model_name(ctx)))


def _shop_reference(ctx: ScanContext) -> tuple[int | None, str, str | None]:
    """(budget, currency, example name) from the product pages crawled: a task grounded in what this shop sells."""
    seen: list[tuple[float, str]] = []
    for page in ctx.ok_by_role("product"):
        prices = prices_in_text(page.text)
        h1 = page.tree.css_first("h1")
        name = " ".join(h1.text(strip=True).split())[:60] if h1 else ""
        if prices and name:
            seen.append((min(prices), name))
    products = ctx.ok_by_role("product")
    currency = "EUR" if any("€" in p.text or "eur" in p.text.lower() for p in products) else "RON"
    if not seen:
        return None, currency, None
    cheapest = min(seen)
    return shop_budget([x[0] for x in seen]), currency, cheapest[1]


async def j_find_shop(ctx: ScanContext, spec: dict[str, Any]) -> CheckResult:
    budget, currency, example = _shop_reference(ctx)
    return await _journey(ctx, spec, "shop", shop_task(budget, currency, example), budget=budget)
