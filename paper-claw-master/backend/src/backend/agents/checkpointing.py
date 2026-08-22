from __future__ import annotations

from functools import lru_cache

from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.engine import make_url

from backend.settings import get_settings


@lru_cache(maxsize=1)
def get_agent_checkpointer() -> PostgresSaver:
    pool = ConnectionPool(_psycopg_connection_string(get_settings().database_url), kwargs={"autocommit": True, "prepare_threshold": 0})
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    return checkpointer


def clear_agent_checkpointer_cache() -> None:
    get_agent_checkpointer.cache_clear()


def _psycopg_connection_string(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql+psycopg":
        url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)
