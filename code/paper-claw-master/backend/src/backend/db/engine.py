from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg://paper_claw:paper_claw@localhost:5432/paper_claw"
DATABASE_URL_ENV = "PAPER_CLAW_DATABASE_URL"


def get_database_url() -> str:
    return os.getenv(DATABASE_URL_ENV, DEFAULT_DATABASE_URL)


def create_engine_from_url(database_url: str | None = None, **kwargs: object) -> Engine:
    return create_engine(database_url or get_database_url(), **kwargs)
