from __future__ import annotations

from functools import lru_cache
import os

from psycopg import Connection
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.engine import make_url

from backend.settings import get_settings


@lru_cache(maxsize=1)
def get_agent_checkpointer() -> PostgresSaver:
    # psycopg_pool's worker threads do not establish a usable connection in
    # this Windows runtime even though a normal psycopg connection succeeds;
    # its PoolTimeout then looks like an unreachable model gateway. The
    # PostgresSaver already serializes access with its internal lock, so keep
    # one direct connection here instead of adding a second failure-prone pool.
    try:
        connect_timeout = max(1, int(os.getenv("PAPER_CLAW_DB_CONNECT_TIMEOUT_SECONDS", "5")))
    except ValueError:
        connect_timeout = 5
    conn = Connection.connect(
        _psycopg_connection_string(get_settings().database_url),
        connect_timeout=connect_timeout,
        row_factory=dict_row,
        autocommit=True,
        prepare_threshold=0,
    )
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()
    return checkpointer


def clear_agent_checkpointer_cache() -> None:
    get_agent_checkpointer.cache_clear()


def _psycopg_connection_string(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql+psycopg":
        url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)
