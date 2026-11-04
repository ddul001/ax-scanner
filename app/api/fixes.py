"""Fix endpoints: list proposals, approve/reject them, export the approved bundle, draft a fix prompt."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.repo.models import Fix, Scan, Site
from app.services.meta_llm import LlmError, MetaLlm

router = APIRouter(prefix="/api", tags=["fixes"])
NL = chr(10)
NL2 = NL * 2

FIX_PROMPT_SYSTEM = (Path(__file__).resolve().parent.parent / "prompts" / "fix_prompt.md").read_text(encoding="utf-8")
FOOTER = "Built with Meta Model API · Muse Spark by Aivexia Tech - https://aivexia.ro"


class FixPromptOut(BaseModel):
    prompt: str


def _nf(what: str) -> HTTPException:
    return HTTPException(404, {"code": "NOT_FOUND", "message": f"{what} not found"})


def serialize_fix(fix: Fix) -> dict[str, Any]:
    return {
        "id": fix.id, "scan_id": fix.scan_id, "check_id": fix.check_id, "type": fix.type, "title": fix.title,
        "target_url": fix.target_url, "status": fix.status, "est_gain": fix.est_gain, **fix.payload,
    }


@router.get("/scans/{scan_id}/fixes")
def list_fixes(scan_id: int, request: Request) -> dict[str, Any]:
    with Session(request.app.state.engine) as session:
        if session.get(Scan, scan_id) is None:
            raise _nf("Scan")
        fixes = session.exec(select(Fix).where(Fix.scan_id == scan_id).order_by(Fix.id)).all()  # type: ignore[arg-type]
        return {
            "fixes": [serialize_fix(f) for f in fixes],
            "total_est_gain": round(sum(f.est_gain for f in fixes if f.status != "rejected"), 1),
        }


@router.post("/fixes/{fix_id}/approve")
def approve_fix(fix_id: int, request: Request) -> dict[str, Any]:
    with Session(request.app.state.engine) as session:
        fix = session.get(Fix, fix_id)
        if fix is None:
            raise _nf("Fix")
        if fix.payload.get("errors"):
            raise HTTPException(409, {"code": "FIX_INVALID", "message": "; ".join(fix.payload["errors"])})
        if fix.status in ("proposed", "rejected"):  # a rejected fix can be reconsidered
            fix.status, fix.approved_at = "approved", datetime.now(timezone.utc)
            session.add(fix)
            session.commit()
            session.refresh(fix)
        return serialize_fix(fix)


@router.post("/fixes/{fix_id}/reject")
def reject_fix(fix_id: int, request: Request) -> dict[str, Any]:
    """Reject a proposal. It is never exported and its gain no longer counts."""
    with Session(request.app.state.engine) as session:
        fix = session.get(Fix, fix_id)
        if fix is None:
            raise _nf("Fix")
        if fix.status == "exported":
            raise HTTPException(409, {"code": "ALREADY_EXPORTED", "message": "This fix was already exported"})
        if fix.status != "rejected":
            fix.status, fix.approved_at = "rejected", None
            session.add(fix)
            session.commit()
            session.refresh(fix)
        return serialize_fix(fix)


@router.get("/scans/{scan_id}/export")
def export_fixes(scan_id: int, request: Request) -> dict[str, Any]:
    """Bundle of APPROVED fixes only. Nothing is exported until a human approved it."""
    with Session(request.app.state.engine) as session:
        if session.get(Scan, scan_id) is None:
            raise _nf("Scan")
        fixes = session.exec(
            select(Fix).where(Fix.scan_id == scan_id, Fix.status.in_(("approved", "exported")))  # type: ignore[attr-defined]
            .order_by(Fix.id)  # type: ignore[arg-type]
        ).all()
        if not fixes:
            raise HTTPException(409, {"code": "NO_APPROVED_FIXES", "message": "Approve at least one fix first"})
        files = []
        readme = ["# AX Scanner fix bundle", ""]
        ld = []
        for n, fix in enumerate(fixes, 1):
            payload = fix.payload
            if fix.type == "jsonld":
                kind = "dealer" if fix.check_id == "id.schema_dealer" else "vehicle"
                path = f"jsonld/{n:02d}-{kind}.json"
                ld.append(payload["snippet"])
            else:
                path = payload["filename"]
            files.append({"path": path, "content_type": payload["content_type"], "content": payload["content"]})
            readme += [f"## {path}", f"Publish at: {fix.target_url}", f"Placement: {payload.get('placement', '')}", ""]
            readme += [f"- Verify: {a}" for a in payload.get("assumptions", [])]
            readme += [f"- Complete manually: {t}" for t in payload.get("todo", [])] + [""]
            fix.status = "exported"
            session.add(fix)
        if ld:
            files.append({"path": "snippets.html", "content_type": "text/html", "content": NL2.join(ld)})
        files.append({"path": "README.md", "content_type": "text/markdown", "content": NL.join(readme)})
        session.commit()
        return {"scan_id": scan_id, "files": files}


def _prompt_context(scan: Scan, site: Site, fixes: list[Fix]) -> dict[str, Any]:
    rep = scan.report or {}
    problems = [
        {"check": r.get("check_id"), "layer": r.get("layer"), "status": r.get("status"), "summary": r.get("summary")}
        for r in rep.get("results", []) if r.get("status") in ("fail", "warn")
    ][:25]
    return {
        "domain": site.domain, "site_type": site.type, "brands": site.brands, "language": site.language,
        "ax_score": scan.ax_score, "grade": scan.grade, "failed_or_warned_checks": problems,
        "fixes": [
            {
                "id": n, "title": f.title, "type": f.type, "target_url": f.target_url, "estimated_gain": f.est_gain,
                "placement": f.payload.get("placement"), "assumptions": f.payload.get("assumptions", []),
                "todo": f.payload.get("todo", []),
            }
            for n, f in enumerate(fixes, 1)
        ],
    }


def _template_prompt(ctx: dict[str, Any]) -> str:
    """Used when the model is unavailable: same structure, filled from the data."""
    lines = [
        "You are helping me improve how AI agents read and use my website. Work in this site's repository.", "",
        "## Context",
        f"- Site: {ctx['domain']} ({ctx['site_type'] or 'unknown type'})" + (f", brands: {', '.join(ctx['brands'])}" if ctx["brands"] else ""),
        f"- AX Scanner score: {round(ctx['ax_score'])} (grade {ctx['grade']})" if ctx["ax_score"] is not None else "- AX Scanner score: n/a",
        "- The scanner checks whether AI assistants can find, understand and act on the site. These fixes close the gaps it found.", "",
        "## Tasks",
    ]
    for fix in ctx["fixes"]:
        lines.append(
            f"{fix['id']}. Fix {fix['id']}: {fix['title']} ({fix['type']}). "
            f"Publish at {fix['target_url']}. {fix['placement'] or ''} Use the code under Fix {fix['id']} below.".rstrip()
        )
        lines += [f"   - Verify: {a}" for a in fix["assumptions"]] + [f"   - Fill in: {t}" for t in fix["todo"]]
    lines += [
        "", "## Constraints",
        "- Do not invent facts (prices, addresses, phone numbers, VINs). Take values from the codebase or ask me.",
        "- Keep the existing design and routes. Change only what the tasks need.",
        "- JSON-LD must be valid JSON. Keep robots.txt changes minimal.", "",
        "## Done when",
        "- Each file or snippet is live at its target URL, JSON-LD parses, and a new AX Scanner scan shows a higher score.",
    ]
    return NL.join(lines)


@router.post("/scans/{scan_id}/fix-prompt")
async def fix_prompt(scan_id: int, request: Request) -> dict[str, Any]:
    """A prompt for a coding assistant to apply the (non-rejected) fixes. Written by the Meta model, with a template fallback."""
    app = request.app
    app.state.page_limiter.check(request.client.host if request.client else "unknown")
    with Session(app.state.engine) as session:
        scan = session.get(Scan, scan_id)
        site = session.get(Site, scan.site_id) if scan else None
        if scan is None or site is None:
            raise _nf("Scan")
        fixes = [
            f for f in session.exec(select(Fix).where(Fix.scan_id == scan_id).order_by(Fix.id)).all()  # type: ignore[arg-type]
            if f.status != "rejected"
        ]
        if not fixes:
            raise HTTPException(409, {"code": "NO_FIXES", "message": "There are no fixes to write a prompt for"})
        ctx = _prompt_context(scan, site, fixes)
        code = [(n, f.title, f.payload.get("content", "")) for n, f in enumerate(fixes, 1)]
    source, text = "template", _template_prompt(ctx)
    if not (app.state.deps.llm_factory is MetaLlm and not settings.meta_api_key):
        llm = app.state.deps.llm_factory()
        if llm is not None:
            try:
                out = await llm.structured(FIX_PROMPT_SYSTEM, json.dumps(ctx, ensure_ascii=False), FixPromptOut, name="fix_prompt")
                if out.prompt.strip():
                    source, text = "meta", out.prompt.strip()
            except LlmError:
                pass
            finally:
                await llm.aclose()
    parts = [text, "", "## Code for each fix", ""]
    for n, title, content in code:
        parts += [f"### Fix {n}: {title}", "```", content, "```", ""]
    parts += ["---", FOOTER]
    return {"prompt": NL.join(parts), "source": source, "fixes": len(code)}
