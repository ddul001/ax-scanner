"""Storage models: scanned sites, their scans, and the fixes proposed for them."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Site(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    canonical_origin: str = Field(index=True, unique=True)
    domain: str
    type: str | None = None
    brands: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    language: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Scan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="site.id", index=True)
    status: str = "queued"  # queued|classifying|needs_confirmation|classified|scanning|completed|failed
    error_code: str | None = None
    error_message: str | None = None
    type_hint: str | None = None
    ignore_robots: bool = False  # the requester asked to scan ignoring robots.txt (opt-in, recorded in the report)
    classification: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    classification_version: str | None = None
    fetch_log: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    report: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    readiness: float | None = None
    ax_score: float | None = None
    grade: str | None = None
    created_at: datetime = Field(default_factory=_now, index=True)
    updated_at: datetime = Field(default_factory=_now)


class Fix(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True)
    check_id: str
    type: str = "jsonld"
    title: str
    target_url: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "proposed"  # proposed|approved|exported|rejected
    est_gain: float = 0.0
    created_at: datetime = Field(default_factory=_now)
    approved_at: datetime | None = None
