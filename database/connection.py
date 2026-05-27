from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shared.config import settings
from shared.logging import get_logger

logger = get_logger(__name__)


def create_engine() -> AsyncEngine:
    logger.info("Creating async database engine")
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    logger.info("Creating async session factory")
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@asynccontextmanager
async def get_db(session_factory: async_sessionmaker[AsyncSession]):
    logger.debug("Opening database session")
    session: AsyncSession = session_factory()

    try:
        yield session

    finally:
        await session.close()
        logger.debug("Database session closed")