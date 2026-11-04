"""Database engine and schema setup (SQLite by default, Postgres on a public deploy)."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.repo import models  # noqa: F401  (register tables)


def make_engine(url: str | None = None) -> Engine:
    url = url or settings.database_url
    if url.startswith("sqlite"):
        path = make_url(url).database
        if path and path != ":memory:":  # a fresh deploy may not have the folder yet (e.g. before a volume is mounted)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = make_engine()


def _add_missing_columns(eng: Engine) -> None:
    """create_all never alters an existing table: add the columns introduced after a database was created."""
    wanted = {"scan": {"ignore_robots": "BOOLEAN DEFAULT 0 NOT NULL"}}
    insp = inspect(eng)
    with eng.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    if eng.dialect.name == "postgresql":
                        ddl = ddl.replace("DEFAULT 0", "DEFAULT FALSE")
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db(eng: Engine | None = None) -> None:
    eng = eng or engine
    SQLModel.metadata.create_all(eng)
    _add_missing_columns(eng)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
