# tests/database/test_connection.py

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from shared.config import settings
from database.connection import create_engine, create_session_factory, get_db


# ── create_engine behavior ────────────────────────────────────

class TestCreateEngine:

    def test_returns_async_engine(self):
        engine = create_engine()
        assert isinstance(engine, AsyncEngine)

    def test_two_calls_return_separate_instances(self):
        e1 = create_engine()
        e2 = create_engine()
        assert e1 is not e2

    def test_engine_uses_configured_database_url(self):
        engine = create_engine()
        assert engine.url.host == "localhost"
        assert engine.url.database == "a2a_travel"
        assert engine.url.drivername == "postgresql+asyncpg"


# ── create_session_factory behavior ──────────────────────────

class TestCreateSessionFactory:

    def test_returns_session_maker(self):
        engine = create_engine()
        factory = create_session_factory(engine)
        assert isinstance(factory, async_sessionmaker)

    def test_factory_produces_async_sessions(self):
        engine = create_engine()
        factory = create_session_factory(engine)
        session = factory()
        assert isinstance(session, AsyncSession)

    def test_two_factories_from_same_engine_are_independent(self):
        engine = create_engine()
        f1 = create_session_factory(engine)
        f2 = create_session_factory(engine)
        assert f1 is not f2


# ── get_db behavior ───────────────────────────────────────────

@pytest.mark.asyncio
class TestGetDb:

    async def test_yields_async_session(self):
        engine = create_engine()
        factory = create_session_factory(engine)

        async with get_db(factory) as session:
            assert isinstance(session, AsyncSession)

    async def test_two_context_manager_calls_yield_different_sessions(self):
        engine = create_engine()
        factory = create_session_factory(engine)

        async with get_db(factory) as s1:
            async with get_db(factory) as s2:
                assert s1 is not s2