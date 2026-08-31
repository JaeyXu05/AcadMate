from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg://paper_claw:paper_claw@localhost:5432/paper_claw"
DATABASE_URL_ENV = "PAPER_CLAW_DATABASE_URL"


def get_database_url() -> str:
    return os.getenv(DATABASE_URL_ENV, DEFAULT_DATABASE_URL)


def create_engine_from_url(database_url: str | None = None, **kwargs: object) -> Engine:
    """Create the shared SQLAlchemy engine with fail-fast Postgres defaults.

    The previous defaults left psycopg waiting on both localhost addresses for a
    long time when Docker/Postgres was down.  That made every A-side endpoint
    look like it had hung.  Keep SQLite/test engines untouched and only apply
    these settings to PostgreSQL URLs.
    """
    url = database_url or get_database_url()
    if url.startswith("postgresql"):
        try:
            connect_timeout = max(1, int(os.getenv("PAPER_CLAW_DB_CONNECT_TIMEOUT_SECONDS", "5")))
        except ValueError:
            connect_timeout = 5
        try:
            pool_size = max(2, int(os.getenv("PAPER_CLAW_DB_POOL_SIZE", "10")))
        except ValueError:
            pool_size = 10
        try:
            max_overflow = max(0, int(os.getenv("PAPER_CLAW_DB_MAX_OVERFLOW", "20")))
        except ValueError:
            max_overflow = 20
        connect_args = dict(kwargs.get("connect_args") or {})
        connect_args.setdefault("connect_timeout", connect_timeout)
        kwargs["connect_args"] = connect_args
        kwargs.setdefault("pool_pre_ping", True)
        kwargs.setdefault("pool_timeout", connect_timeout)
        # One background workflow holds one SQLAlchemy session while the D
        # side polls status/events.  The old 5+10 pool exhausted under a few
        # concurrent PDF/report/mentor runs and surfaced as apparent hangs.
        kwargs.setdefault("pool_size", pool_size)
        kwargs.setdefault("max_overflow", max_overflow)
    return create_engine(url, **kwargs)
