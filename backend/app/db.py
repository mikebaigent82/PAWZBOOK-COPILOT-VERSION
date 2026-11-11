from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_Session: sessionmaker[Session] | None = None


def configure(url: str | None = None):
    """(Re)create the engine. Called lazily and by tests."""
    global _engine, _Session
    url = url or get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _enforce_foreign_keys(dbapi_conn, _record):  # SQLite ignores ON DELETE CASCADE unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    _Session = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine():
    if _engine is None:
        configure()
    return _engine


def get_db() -> Iterator[Session]:
    if _Session is None:
        configure()
    assert _Session is not None
    db = _Session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
