"""Общие помощники слоя БД: коммит с превращением гонки в 409 и поиск без учёта регистра.

``ci_contains`` / ``ci_equals`` сравнивают через ``lower()``. В PostgreSQL ``lower()`` корректно
работает с кириллицей, если база в UTF-8 и локаль не ``C``. Встроенный ``lower()`` SQLite
понимает только ASCII, поэтому для SQLite (тесты) при каждом подключении регистрируется
Python-версия ``lower``: иначе поиск «иванов» не находил бы «Иванов». Обработчик повешен
на класс ``Engine``, так что действует и на движки, которые тесты создают сами. Если
зарегистрировать функцию не удалось, поиск продолжает работать, но регистр игнорируется
только для ASCII.
"""

from typing import Any

from sqlalchemy import ColumnElement, String, event, func
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.errors import ConflictError, is_unique_violation


def _py_lower(value: str | None) -> str | None:
    """Unicode-версия SQL-функции ``lower`` для SQLite."""
    return None if value is None else value.lower()


@event.listens_for(Engine, "connect")
def _register_sqlite_unicode_lower(dbapi_connection: Any, _connection_record: Any) -> None:
    """Подменяет встроенную ASCII-версию ``lower`` в соединениях SQLite (sqlite3 и aiosqlite)."""
    if "sqlite" not in type(dbapi_connection).__module__:
        return
    try:
        dbapi_connection.create_function("lower", 1, _py_lower, deterministic=True)
    except Exception:  # noqa: BLE001 - без регистрации остаётся ASCII-версия, это не авария
        return


def ci_contains(column: InstrumentedAttribute[str], needle: str) -> ColumnElement[bool]:
    """``column`` содержит ``needle`` без учёта регистра; ``%`` и ``_`` в ``needle`` экранируются."""
    return func.lower(column, type_=String).contains(needle.lower(), autoescape=True)


def ci_equals(column: InstrumentedAttribute[str], value: str) -> ColumnElement[bool]:
    """``column`` равна ``value`` без учёта регистра."""
    return func.lower(column, type_=String) == value.lower()


async def commit_or_conflict(session: AsyncSession, conflict_message: str) -> None:
    """Фиксирует транзакцию; нарушение уникальности (гонка за unique-индекс) превращает в 409.

    Любая другая ``IntegrityError`` (внешний ключ, CHECK) - это баг, а не конфликт клиента,
    и пробрасывается как есть.
    """
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if is_unique_violation(exc):
            raise ConflictError(conflict_message) from exc
        raise
