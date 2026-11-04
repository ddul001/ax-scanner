"""Pure scoring for check results (docs/checks/README.md section 1). No I/O."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["pass", "warn", "fail", "na", "skipped"]
STATUS_VALUE: dict[str, float] = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
SEVERITY_WEIGHT: dict[str, int] = {"CRITICAL": 4, "HIGH": 3, "MAJOR": 2, "MINOR": 1, "INFO": 0}
GRADES: list[tuple[str, float]] = [("A", 90), ("B", 75), ("C", 60), ("D", 40), ("F", 0)]
GATE_CAP = "C"  # a failed CRITICAL check caps the grade here
CHECKS_VERSION = "mvp-1"
# Bump on ANY change that can move a score (checks, weights, page discovery, verification rules). The leaderboard marks scans
# made with another version as outdated, so rankings never silently mix old and new rules.
SCORING_VERSION = "2026-11-02.2"


class CheckResult(BaseModel):
    check_id: str
    layer: str
    severity: str
    method: str
    status: Status
    version: str = CHECKS_VERSION
    summary: str = ""
    pages: list[str] = Field(default_factory=list)
    found: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    snippet: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    not_adopted: bool = False  # opportunity (e.g. no AAP card yet), not counted against the grade gate


class LayerScore(BaseModel):
    layer: str
    weight: float
    score: float | None  # None when no applicable check
    checks: int
    applicable: int


class Report(BaseModel):
    site_type: str
    readiness: float
    ax_score: float
    visibility: float | None = None
    grade: str
    grade_before_gate: str
    gate_applied: bool
    gate_checks: list[str] = Field(default_factory=list)
    layers: list[LayerScore]
    results: list[CheckResult]
    coverage: dict[str, Any] = Field(default_factory=dict)
    version: str = CHECKS_VERSION
    scoring_version: str = SCORING_VERSION


def counts(result: CheckResult) -> bool:
    """Whether a result feeds the score (scored status and a weighted severity)."""
    return result.status in STATUS_VALUE and SEVERITY_WEIGHT.get(result.severity, 0) > 0


def layer_score(results: list[CheckResult]) -> float | None:
    """sum(sev * status) / sum(applicable sev) * 100; None if nothing applicable."""
    applicable = [r for r in results if counts(r)]
    denom = sum(SEVERITY_WEIGHT[r.severity] for r in applicable)
    if denom == 0:
        return None
    return sum(SEVERITY_WEIGHT[r.severity] * STATUS_VALUE[r.status] for r in applicable) / denom * 100


def grade_for(score: float) -> str:
    for letter, floor in GRADES:
        if score >= floor:
            return letter
    return "F"


def cap_grade(grade: str, cap: str = GATE_CAP) -> str:
    order = [g for g, _ in GRADES]
    return grade if order.index(grade) >= order.index(cap) else cap


def build_report(
    site_type: str,
    weights: dict[str, float],
    results: list[CheckResult],
    *,
    visibility: float | None = None,
) -> Report:
    layers: list[LayerScore] = []
    weighted = 0.0
    used_weight = 0.0
    for layer, weight in weights.items():
        in_layer = [r for r in results if r.layer == layer]
        score = layer_score(in_layer)
        layers.append(
            LayerScore(
                layer=layer,
                weight=weight,
                score=None if score is None else round(score, 1),
                checks=len(in_layer),
                applicable=sum(1 for r in in_layer if counts(r)),
            )
        )
        if score is not None:
            weighted += score * weight
            used_weight += weight
    readiness = round(weighted / used_weight, 1) if used_weight else 0.0  # layers without checks are renormalised away
    ax = readiness if visibility is None else round(0.6 * readiness + 0.4 * visibility, 1)
    before = grade_for(ax)
    gate = [
        r.check_id for r in results
        if r.severity == "CRITICAL" and r.status == "fail" and not r.not_adopted
    ]
    final = cap_grade(before) if gate else before
    skipped = [r.check_id for r in results if r.status == "skipped"]
    na = [r.check_id for r in results if r.status == "na"]
    return Report(
        site_type=site_type,
        readiness=readiness,
        ax_score=ax,
        visibility=visibility,
        grade=final,
        grade_before_gate=before,
        gate_applied=final != before,
        gate_checks=gate,
        layers=layers,
        results=results,
        coverage={
            "total": len(results),
            "scored": sum(1 for r in results if counts(r)),
            "skipped": skipped,
            "na": na,
            "partial": bool(skipped),
        },
    )
