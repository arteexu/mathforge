"""SQLite persistence layer (SQLModel/SQLAlchemy engine + sessions).

The default database lives at ``./mathforge.db`` in the current working
directory, overridable with the ``MATHFORGE_DB`` environment variable or by
passing an explicit URL to :func:`get_engine`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Import models so they register with ``SQLModel.metadata`` before create_all.
from mathforge import schema as _schema  # noqa: F401

__all__ = [
    "default_db_url",
    "get_engine",
    "init_db",
    "get_session",
    "session_scope",
    "training_problems_select",
    "count_by_split",
]


def default_db_url() -> str:
    """Resolve the database URL from ``MATHFORGE_DB`` or fall back to a file."""
    env = os.environ.get("MATHFORGE_DB")
    if env:
        return env
    return "sqlite:///mathforge.db"


@lru_cache(maxsize=None)
def get_engine(url: str | None = None, echo: bool = False) -> Engine:
    """Create (and cache) an engine for ``url`` (defaults to :func:`default_db_url`)."""
    resolved = url or default_db_url()
    connect_args = (
        {"check_same_thread": False} if resolved.startswith("sqlite") else {}
    )
    return create_engine(resolved, echo=echo, connect_args=connect_args)


def init_db(url: str | None = None, echo: bool = False) -> Engine:
    """Create all tables (and add any missing columns) for the resolved engine."""
    engine = get_engine(url, echo=echo)
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine


def _add_missing_columns(engine: Engine) -> None:
    """Lightweight additive migration: ``ALTER TABLE ... ADD COLUMN`` for new
    model fields not yet present in an existing table.

    Handles the common dev case where the schema gains nullable columns after a
    database already exists. Only additive (never drops/renames); safe on SQLite.
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    insp = sa_inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" '
                        f'ADD COLUMN "{col.name}" {coltype}'
                    )
                )


def get_session(url: str | None = None) -> Session:
    """Return a new :class:`~sqlmodel.Session` bound to the resolved engine.

    ``expire_on_commit`` is disabled so already-loaded attributes remain
    accessible after ``commit()`` (relationships still lazy-load only while the
    session is open).
    """
    return Session(get_engine(url), expire_on_commit=False)


def training_problems_select():
    """A ``select(Problem)`` restricted to the TRAIN split (never eval/frozen).

    This is the single chokepoint every upstream stage (annotate, generate,
    export, insight mining) must use so the frozen eval set can never leak into
    training or generation.
    """
    from sqlmodel import select

    from mathforge.schema import DataSplit, Problem

    return select(Problem).where(
        Problem.split == DataSplit.TRAIN, Problem.frozen == False  # noqa: E712
    )


def count_by_split(url: str | None = None) -> dict[str, int]:
    """Return ``{"train": n, "eval": m, "frozen": k}`` problem counts."""
    from sqlmodel import select

    from mathforge.schema import DataSplit, Problem

    with session_scope(url) as session:
        rows = session.exec(select(Problem.split, Problem.frozen)).all()
    counts = {DataSplit.TRAIN.value: 0, DataSplit.EVAL.value: 0, "frozen": 0}
    for split, frozen in rows:
        counts[split.value if hasattr(split, "value") else str(split)] += 1
        if frozen:
            counts["frozen"] += 1
    return counts


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """Transactional session context: commit on success, rollback on error."""
    session = get_session(url)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
