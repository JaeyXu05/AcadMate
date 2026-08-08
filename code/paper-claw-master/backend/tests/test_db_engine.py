from __future__ import annotations

from sqlalchemy import text


def test_postgres_engine_and_pgvector(engine):
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        assert connection.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'")).scalar_one() == "vector"


def test_session_commit_and_rollback(session):
    from backend.db.models import Thread

    session.add(Thread(title="commit test"))
    session.commit()
    assert session.query(Thread).count() == 1

    session.add(Thread(title="rollback test"))
    session.rollback()
    assert session.query(Thread).count() == 1
