"""FastAPI dependency injection for database sessions."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for a single request."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
