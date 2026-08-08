from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.db.base import Base
from backend.db.engine import DEFAULT_DATABASE_URL, DATABASE_URL_ENV, create_engine_from_url
from backend.db.models import *  # noqa: F403
from backend.settings import clear_settings_cache
from backend.tools.context import set_tool_session_factory

TEST_DATABASE_NAME = "paper_claw_test"


def _configured_test_database_url() -> str:
    configured = os.getenv(DATABASE_URL_ENV)
    url = make_url(configured or DEFAULT_DATABASE_URL)
    if TEST_DATABASE_NAME not in str(url.database):
        url = url.set(database=TEST_DATABASE_NAME)
    return url.render_as_string(hide_password=False)


os.environ[DATABASE_URL_ENV] = _configured_test_database_url()


def test_database_url() -> str:
    url = make_url(os.environ[DATABASE_URL_ENV])
    if TEST_DATABASE_NAME not in str(url.database):
        raise RuntimeError(f"Refusing to run destructive tests against non-test database: {url.render_as_string(hide_password=True)}")
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def engine():
    engine = create_engine_from_url(test_database_url())
    assert_test_database(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    yield engine
    engine.dispose()


def assert_test_database(engine) -> None:
    with engine.connect() as connection:
        database_name = connection.execute(text("select current_database()")).scalar_one()
    if TEST_DATABASE_NAME not in database_name:
        raise RuntimeError(f"Refusing to reset non-test database: {database_name}")


def reset_schema(engine) -> None:
    assert_test_database(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


@pytest.fixture()
def isolated_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    storage_root = data_dir / "files"
    monkeypatch.setenv("PAPER_CLAW_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PAPER_CLAW_STORAGE_ROOT", str(storage_root))
    clear_settings_cache()
    try:
        yield storage_root
    finally:
        clear_settings_cache()


@pytest.fixture()
def session(engine, isolated_storage: Path):
    reset_schema(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    set_tool_session_factory(factory)
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
        finally:
            set_tool_session_factory(None)
            session.rollback()
    reset_schema(engine)
