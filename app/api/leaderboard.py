"""Leaderboard: one row per domain from its latest completed scan, ranked by AX Score."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlmodel import Session, select

from app.domain.scoring import SCORING_VERSION
from app.repo.models import Scan, Site

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("")
def leaderboard(request: Request, type: str | None = None) -> dict[str, Any]:
    """One row per domain: its latest completed scan, ranked by AX Score (best first)."""
    with Session(request.app.state.engine) as session:
        scans = session.exec(
            select(Scan).where(Scan.status == "completed", Scan.ax_score != None).order_by(Scan.id.desc())  # type: ignore[arg-type]  # noqa: E711
        ).all()
        sites = {x.id: x for x in session.exec(select(Site)).all()}
        latest: dict[int, Scan] = {}
        for scan in scans:  # newest first, so the first one seen per site is its latest
            latest.setdefault(scan.site_id, scan)
        rows = []
        for site_id, scan in latest.items():
            site = sites.get(site_id)
            if site is None or (type and site.type != type):
                continue
            rep = scan.report or {}
            layers = [x for x in rep.get("layers", []) if x.get("applicable")]
            weakest = min(layers, key=lambda x: x["score"], default=None)
            rows.append({
                "scan_id": scan.id, "domain": site.domain, "type": site.type,
                "ax_score": scan.ax_score, "grade": scan.grade, "gate_applied": rep.get("gate_applied", False),
                "weakest_layer": weakest["layer"] if weakest else None,
                "weakest_score": weakest["score"] if weakest else None,
                "scanned_at": scan.created_at.isoformat(),
                "scoring_version": rep.get("scoring_version"), "outdated": rep.get("scoring_version") != SCORING_VERSION,
            })
        rows.sort(key=lambda r: (-r["ax_score"], r["domain"]))
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        return {"entries": rows, "current_version": SCORING_VERSION}
