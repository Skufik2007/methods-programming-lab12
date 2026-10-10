"""Асинхронный engine SQLAlchemy, фабрика сессий и зависимость ``get_session``.

Транзакциями управляет вызывающий код (сервисы / роуты): ``get_session`` сам ничего
не коммитит. Незавершённая транзакция откатывается при закрытии сессии.
"""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


def create_engine(database_url: str) -> AsyncEngine:
    """Создаёт async engine.

    Для SQLite (тесты) включается ``PRAGMA foreign_keys=ON``: по умолчанию SQLite
    не проверяет внешние ключи, и тесты не ловили бы нарушения ссылочной целостности.
    """
    engine = create_async_engine(database_url, pool_pre_ping=True)

    if make_url(database_url).get_backend_name() == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


engine: AsyncEngine = create_engine(get_settings().database_url.get_secret_value())

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,  # объекты остаются читаемыми после commit без повторного SELECT
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-зависимость: одна сессия на запрос, закрывается после ответа."""
    async with SessionFactory() as session:
        yield session


async def dispose_engine() -> None:
    """Закрывает пул соединений (вызывать при остановке приложения)."""
    await engine.dispose()
