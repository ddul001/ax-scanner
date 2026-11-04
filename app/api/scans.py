"""Scan endpoints: create a scan, follow its progress, confirm its site type, list history."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, func, or_, select

from app.config import settings
from app.domain.models import SITE_TYPES
from app.jobs.scan_pipeline import maybe_run_checks, run_scan
from app.repo.models import Fix, Scan, Site
from app.services.discovery_view import expected_pages
from app.services.meta_llm import MetaLlm
from app.services.url_normalizer import ScanError, normalize_input

router = APIRouter(prefix="/api/scans", tags=["scans"])
ACTIVE = ("queued", "classifying")


class ScanCreate(BaseModel):
    url: str
    type_hint: Literal["dealer", "importer", "ecommerce", "marketplace", "finance"] | None = None
    force: bool = False
    ignore_robots: bool = False  # opt-in: scan although robots.txt disallows our crawler (owners / permitted audits)


class ConfirmBody(BaseModel):
    type: Literal["dealer", "importer", "ecommerce", "marketplace", "finance"]


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            raise HTTPException(429, {"code": "RATE_LIMITED", "message": "Too many scans, try again in a minute"})
        window.append(now)


def _err(error: ScanError) -> HTTPException:
    return HTTPException(422, {"code": error.code, "message": error.message})


def serialize(scan: Scan, site: Site) -> dict[str, Any]:
    typ = site.type or (scan.classification or {}).get("type")
    return {
        "id": scan.id,
        "status": scan.status,
        "site": {"domain": site.domain, "origin": site.canonical_origin, "type": site.type},
        "classification": scan.classification,
        "score": None if scan.ax_score is None else {"ax_score": scan.ax_score, "readiness": scan.readiness, "grade": scan.grade},
        "report": scan.report,
        "expected_pages": expected_pages(typ),
        "ignore_robots": scan.ignore_robots,
        "error": {"code": scan.error_code, "message": scan.error_message} if scan.error_code else None,
        "created_at": scan.created_at.isoformat(),
    }


@router.post("", status_code=202)
def create_scan(body: ScanCreate, request: Request, background: BackgroundTasks) -> dict[str, Any]:
    app = request.app
    if app.state.deps.llm_factory is MetaLlm and not settings.meta_api_key:
        raise HTTPException(503, {
            "code": "LLM_NOT_CONFIGURED",
            "message": "META_API_KEY is not set on the server, so scans are disabled. Set it and restart.",
        })
    if body.ignore_robots and not settings.allow_ignore_robots:
        raise HTTPException(403, {
            "code": "ROBOTS_OVERRIDE_DISABLED",
            "message": "This server does not allow scans that ignore robots.txt.",
        })
    ip = request.client.host if request.client else "unknown"
    app.state.limiter.check(ip)
    try:
        target = normalize_input(body.url)
    except ScanError as e:
        raise _err(e) from None

    with Session(app.state.engine) as session:
        site = session.exec(
            select(Site).where(or_(Site.domain == target.host, Site.canonical_origin == target.origin))
        ).first()
        if site is None:
            site = Site(domain=target.host, canonical_origin=target.origin)
            session.add(site)
            session.commit()
            session.refresh(site)
        recent = datetime.now(timezone.utc) - timedelta(minutes=2)
        active = session.exec(
            select(Scan).where(Scan.site_id == site.id, Scan.status.in_(ACTIVE))  # type: ignore[attr-defined]
        ).all()
        for scan in active:
            created = scan.created_at if scan.created_at.tzinfo else scan.created_at.replace(tzinfo=timezone.utc)
            if created >= recent:
                return {"scan_id": scan.id, "status": scan.status, "deduplicated": True}
        if settings.max_scans_per_day > 0:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            made = session.exec(select(func.count()).select_from(Scan).where(Scan.created_at >= since)).one()  # type: ignore[arg-type]
            if made >= settings.max_scans_per_day:
                raise HTTPException(429, {
                    "code": "DAILY_LIMIT",
                    "message": "This demo has reached its daily scan limit. Browse the existing scans and the leaderboard, or try again tomorrow.",
                })
        scan = Scan(site_id=site.id, type_hint=body.type_hint, ignore_robots=body.ignore_robots)
        session.add(scan)
        session.commit()
        session.refresh(scan)
        scan_id = scan.id

    background.add_task(run_scan, scan_id, app.state.engine, app.state.deps, force=body.force)
    return {"scan_id": scan_id, "status": "queued"}


@router.get("")
def list_scans(request: Request, limit: int = 50) -> dict[str, Any]:
    """Scan history, newest first, with the summary the history page needs (no full reports)."""
    limit = max(1, min(limit, 200))
    with Session(request.app.state.engine) as session:
        scans = session.exec(select(Scan).order_by(Scan.id.desc()).limit(limit)).all()  # type: ignore[attr-defined]
        sites = {x.id: x for x in session.exec(select(Site)).all()}
        counts = dict(session.exec(select(Fix.scan_id, func.count()).group_by(Fix.scan_id)).all())  # type: ignore[arg-type]
        items = []
        for scan in scans:
            site = sites.get(scan.site_id)
            rep = scan.report or {}
            results = rep.get("results", [])
            items.append({
                "id": scan.id, "status": scan.status, "domain": site.domain if site else "",
                "type": site.type if site else None,
                "ax_score": scan.ax_score, "grade": scan.grade, "gate_applied": rep.get("gate_applied", False),
                "checks": {k: sum(1 for r in results if r["status"] == k) for k in ("pass", "warn", "fail")} if results else None,
                "partial": bool(rep.get("partial")),
                "fixes_count": counts.get(scan.id, 0),
                "error": {"code": scan.error_code, "message": scan.error_message} if scan.error_code else None,
                "created_at": scan.created_at.isoformat(),
            })
        return {"scans": items}


@router.get("/{scan_id}")
def get_scan(scan_id: int, request: Request) -> dict[str, Any]:
    with Session(request.app.state.engine) as session:
        scan = session.get(Scan, scan_id)
        if scan is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Scan not found"})
        out = serialize(scan, session.get(Site, scan.site_id))  # type: ignore[arg-type]
        out["fixes_count"] = session.exec(select(func.count()).select_from(Fix).where(Fix.scan_id == scan_id)).one()
        return out


@router.post("/{scan_id}/confirm")
def confirm_scan(scan_id: int, body: ConfirmBody, request: Request, background: BackgroundTasks) -> dict[str, Any]:
    if body.type not in SITE_TYPES:  # defensive; Literal already enforces this
        raise HTTPException(422, {"code": "INVALID_TYPE", "message": "Unknown site type"})
    with Session(request.app.state.engine) as session:
        scan = session.get(Scan, scan_id)
        if scan is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Scan not found"})
        if scan.status != "needs_confirmation":
            raise HTTPException(409, {"code": "NOT_AWAITING_CONFIRMATION", "message": f"Scan is {scan.status}"})
        site = session.get(Site, scan.site_id)
        classification = dict(scan.classification or {})
        classification.update(type=body.type, confirmed_by_user=True, needs_confirmation=False)
        scan.classification = classification
        scan.status = "classified"  # next pipeline stages (crawl, checks) attach here
        scan.updated_at = datetime.now(timezone.utc)
        site.type = body.type  # type: ignore[union-attr]
        session.add(scan)
        session.add(site)
        session.commit()
        session.refresh(scan)
        background.add_task(maybe_run_checks, scan_id, request.app.state.engine, request.app.state.deps)
        return serialize(scan, site)  # type: ignore[arg-type]
