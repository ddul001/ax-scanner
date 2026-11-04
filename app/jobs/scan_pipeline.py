"""Scan job. For now only Step 0 (classification); later stages hook in after `classified`."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.checks.context import ScanContext, build_context
from app.checks.engine import IMPLEMENTED_TYPES, load_template, make_report, run_checks
from app.config import settings
from app.domain.models import CLASSIFICATION_VERSION
from app.domain.scoring import Report
from app.fixes.base import FixDraft
from app.fixes.engine import generate_all
from app.repo.models import Fix, Scan, Site
from app.services.classifier import run_step0
from app.services.crawler import SafeFetcher, acquire_homepage
from app.services.discovery_view import attach_usage
from app.services.meta_llm import MetaLlm
from app.services.renderer import Renderer, render_html
from app.services.robots_report import robots_report
from app.services.url_normalizer import ScanError, Target

log = logging.getLogger(__name__)


@dataclass
class Deps:
    fetcher_factory: Callable[..., SafeFetcher] = SafeFetcher
    llm_factory: Callable[[], MetaLlm | None] = MetaLlm
    renderer: Renderer | None = render_html
    run_checks: bool = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _set_status(session: Session, scan: Scan, status: str, **fields: Any) -> None:
    scan.status = status
    scan.updated_at = _now()
    for name, value in fields.items():
        setattr(scan, name, value)
    session.add(scan)
    session.commit()


def cached_classification(session: Session, site_id: int) -> Scan | None:
    cutoff = _now() - timedelta(days=settings.classification_cache_days)
    rows = session.exec(
        select(Scan)
        .where(Scan.site_id == site_id, Scan.classification != None)  # noqa: E711
        .order_by(Scan.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    for row in rows:
        if _aware(row.created_at) >= cutoff and row.classification_version == CLASSIFICATION_VERSION:
            return row
    return None


async def run_scan_step0(scan_id: int, engine: Engine, deps: Deps, *, force: bool = False) -> None:
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if scan is None:
            return
        site = session.get(Site, scan.site_id)
        assert site is not None
        _set_status(session, scan, "classifying")

        if not force and (prev := cached_classification(session, site.id)) is not None and prev.id != scan.id:
            classification = dict(prev.classification or {})
            classification["from_cache"] = True
            _finish(session, scan, site, classification, prev.fetch_log or [], site.canonical_origin)
            return

        fetcher = deps.fetcher_factory()
        llm = deps.llm_factory()
        try:
            target = Target(host=site.domain, origin=f"https://{site.domain}")
            async with asyncio.timeout(settings.step0_budget_s):
                result = await run_step0(
                    target, fetcher=fetcher, llm=llm, renderer=deps.renderer, hint=scan.type_hint,
                    ignore_robots=scan.ignore_robots,
                )
            _finish(
                session, scan, site, result.classification.model_dump(), result.fetch_log, result.canonical_origin
            )
        except ScanError as e:
            if e.code == "BLOCKED_BY_ROBOTS" and getattr(e, "robots", None) is not None:
                _robots_partial(session, scan, e, fetcher.log)  # still useful: what robots.txt says about AI agents
            else:
                _set_status(session, scan, "failed", error_code=e.code, error_message=e.message, fetch_log=fetcher.log)
        except TimeoutError:
            _set_status(
                session, scan, "failed", error_code="TIMEOUT",
                error_message=f"Classification exceeded {settings.step0_budget_s:g}s", fetch_log=fetcher.log,
            )
        except Exception:  # noqa: BLE001
            log.exception("step0 crashed for scan %s", scan_id)
            _set_status(session, scan, "failed", error_code="INTERNAL", error_message="Unexpected error")
        finally:
            await fetcher.aclose()
            if llm is not None:
                await llm.aclose()


def _ai_usage(scan: Scan, ctx: ScanContext, report: Report) -> dict[str, Any]:
    """Which Meta Model API capabilities actually ran for this scan (shown in the report, so nothing is implied that did not happen)."""
    used = []
    if "llm" in str((scan.classification or {}).get("method", "")):
        used.append("site classification")
    if (ctx.discovery or {}).get("mode") == "llm_first":
        used.append("page discovery")
    if any(r.method == "J" and r.status != "skipped" for r in report.results):
        used.append("agent journey")
    if any(r.check_id == "trust.policies_text" and r.status != "skipped" for r in report.results):
        used.append("policy reading")
    return {"provider": "Meta Model API", "model": settings.meta_model, "used_for": used}


def _robots_partial(session: Session, scan: Scan, error: ScanError, fetch_log: list[dict[str, Any]]) -> None:
    """robots.txt closes the site to our scanner: report what robots.txt says per AI agent instead of failing."""
    report = {
        "partial": True, "reason": "BLOCKED_BY_ROBOTS", "message": error.message,
        "robots": robots_report(error.robots, error.origin),
        "not_evaluated": ("Everything except what robots.txt itself declares: this scanner respects robots.txt, so the pages were not read. "
                          "The owner can allow the scanner, or the scan can be repeated ignoring robots.txt for a site you own or may scan."),
    }
    _set_status(session, scan, "completed", report=report, error_code=None, error_message=None, fetch_log=fetch_log)


def _finish(
    session: Session, scan: Scan, site: Site, classification: dict[str, Any],
    fetch_log: list[dict[str, Any]], origin: str,
) -> None:
    needs = bool(classification.get("needs_confirmation"))
    site = _adopt_canonical_origin(session, scan, site, origin)
    site.brands = classification.get("brands", [])
    site.language = classification.get("language")
    site.type = None if needs else classification.get("type")
    session.add(site)
    _set_status(
        session, scan, "needs_confirmation" if needs else "classified",
        classification=classification, classification_version=classification.get("version"), fetch_log=fetch_log,
    )


def _adopt_canonical_origin(session: Session, scan: Scan, site: Site, origin: str) -> Site:
    """Point the scan at the site's canonical origin (post-redirect), merging alias rows."""
    if origin == site.canonical_origin:
        return site
    existing = session.exec(select(Site).where(Site.canonical_origin == origin)).first()
    if existing is None:
        site.canonical_origin = origin
        return site
    scan.site_id = existing.id  # same site reached through another alias (www / redirect)
    session.add(scan)
    session.flush()
    if not session.exec(select(Scan).where(Scan.site_id == site.id)).first():
        session.delete(site)
    return existing


async def run_scan(scan_id: int, engine: Engine, deps: Deps, *, force: bool = False) -> None:
    """Whole pipeline: Step 0 (classification) then, for implemented site types, Step 1 (crawl + checks)."""
    await run_scan_step0(scan_id, engine, deps, force=force)
    await maybe_run_checks(scan_id, engine, deps)


async def _safe_drafts(
    ctx: ScanContext, report: Report, template: dict[str, Any], brands: list[str]
) -> list[FixDraft]:
    """Fix generation must never sink a finished scan."""
    try:
        return await generate_all(ctx, report.results, template["weights"], list(brands))
    except Exception:  # noqa: BLE001
        log.exception("fix generation failed")
        return []


def _store_fixes(session: Session, scan: Scan, drafts: list[FixDraft]) -> None:
    for draft in drafts:
        session.add(Fix(scan_id=scan.id, check_id=draft.check_id, type=draft.type, title=draft.title,
                        target_url=draft.target_url, payload=draft.payload(), est_gain=draft.est_gain))


async def maybe_run_checks(scan_id: int, engine: Engine, deps: Deps) -> None:
    if not deps.run_checks:
        return
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        typ = (scan.classification or {}).get("type") if scan else None
        if scan is None or scan.status != "classified":
            return
        if typ not in IMPLEMENTED_TYPES:
            _fail_unsupported(session, scan, typ)
            return
    await run_scan_checks(scan_id, engine, deps)


async def run_scan_checks(scan_id: int, engine: Engine, deps: Deps) -> None:
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        site = session.get(Site, scan.site_id)  # type: ignore[arg-type]
        assert scan is not None and site is not None
        typ = (scan.classification or {})["type"]
        _set_status(session, scan, "scanning")
        fetcher = deps.fetcher_factory()
        llm = deps.llm_factory()
        try:
            async with asyncio.timeout(settings.scan_budget_s):
                acquired = await acquire_homepage(
                    fetcher, Target(host=site.domain, origin=f"https://{site.domain}"),
                    ignore_robots=scan.ignore_robots,
                )
                ctx = await build_context(acquired, site.domain, typ, fetcher, deps.fetcher_factory, llm=llm)
                ctx.llm = llm
                template = load_template(typ)
                report = make_report(typ, template, await run_checks(ctx, template))
                if scan.ignore_robots:  # transparent: the report says the scan did not follow robots.txt, and whether it would have had to
                    report.coverage["robots"] = {
                        "ignored": True,
                        "disallowed_for_scanner": not acquired.robots.allowed(
                            acquired.origin + "/", user_agent=settings.bot_user_agent.split("/")[0]),
                    }
                report.coverage["ai"] = _ai_usage(scan, ctx, report)
                if ctx.discovery:
                    attach_usage(ctx.discovery, report.results)
                    report.coverage["discovery"] = ctx.discovery
                if ctx.link_resolution:  # how brand-site pages were found (LLM pick, rules, or both) - evidence for the reader
                    report.coverage["link_resolution"] = ctx.link_resolution
                drafts = await _safe_drafts(ctx, report, template, site.brands or [])
            _store_fixes(session, scan, drafts)
            _set_status(
                session, scan, "completed", report=report.model_dump(), readiness=report.readiness,
                ax_score=report.ax_score, grade=report.grade, fetch_log=(scan.fetch_log or []) + fetcher.log,
            )
        except ScanError as e:
            _set_status(session, scan, "failed", error_code=e.code, error_message=e.message)
        except TimeoutError:
            _set_status(session, scan, "failed", error_code="TIMEOUT",
                        error_message=f"Scan exceeded {settings.scan_budget_s:g}s")
        except Exception:  # noqa: BLE001
            log.exception("checks crashed for scan %s", scan_id)
            _set_status(session, scan, "failed", error_code="INTERNAL", error_message="Unexpected error")
        finally:
            await fetcher.aclose()
            if llm is not None:
                await llm.aclose()


def _fail_unsupported(session: Session, scan: Scan, typ: str | None) -> None:
    _set_status(session, scan, "failed", error_code="TYPE_NOT_SUPPORTED",
                error_message=f"Detected as {typ}. This version scores dealer, brand/importer and online-shop sites.")


def fail_interrupted(engine: Engine) -> int:
    """Scans run as in-process background tasks, so any scan still in flight at startup belongs to a dead process."""
    with Session(engine) as session:
        stuck = session.exec(select(Scan).where(Scan.status.in_(("queued", "classifying", "scanning")))).all()  # type: ignore[attr-defined]
        for scan in stuck:
            scan.status, scan.error_code = "failed", "INTERRUPTED"
            scan.error_message = "The server restarted while this scan was running. Please run it again."
            session.add(scan)
        session.commit()
        # classified scans of a type without checks would otherwise sit there forever
        parked = session.exec(select(Scan).where(Scan.status == "classified")).all()
        n = 0
        for scan in parked:
            typ = (scan.classification or {}).get("type")
            if typ not in IMPLEMENTED_TYPES:
                _fail_unsupported(session, scan, typ)
                n += 1
        return len(stuck) + n
