"""Фабрика приложения FastAPI.

``create_app()`` собирает приложение: подключает роутеры и обработчики доменных ошибок,
а в ``lifespan`` закрывает пул соединений с БД при остановке. Запуск:
``uvicorn app.main:app`` (или ``uvicorn --factory app.main:create_app``).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import dispose_engine
from app.errors import register_exception_handlers
from app.routers import analytics as analytics_router
from app.routers import appointments as appointments_router
from app.routers import auth as auth_router
from app.routers import doctors as doctors_router
from app.routers import medical_records as medical_records_router
from app.routers import patients as patients_router
from app.routers import prescriptions as prescriptions_router
from app.routers import users as users_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл приложения: при остановке освобождает пул соединений."""
    try:
        yield
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    """Создаёт и настраивает экземпляр приложения."""
    app = FastAPI(title="Clinic management system", version="1.0.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(auth_router.router)
    app.include_router(appointments_router.router)
    app.include_router(users_router.router)
    app.include_router(doctors_router.router)
    app.include_router(patients_router.router)
    app.include_router(prescriptions_router.router)
    app.include_router(medical_records_router.router)
    app.include_router(analytics_router.router)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Проверка живости сервиса (без обращения к БД)."""
        return {"status": "ok"}

    return app


app = create_app()
