from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

from bot.config import DATABASE_URL as CONFIG_DATABASE_URL
from bot.database.models import Base


# Пытаемся загрузить переменные окружения из разных источников
load_dotenv(dotenv_path=os.getenv("ENV_PATH", ".env.dev"))

# Используем URL из переменных окружения или из конфига
DATABASE_URL = os.getenv("DATABASE_URL", CONFIG_DATABASE_URL)

# Добавляем логирование для отладки
print(f"DEBUG: DATABASE_URL = {DATABASE_URL}")


# создаем движок и фабрику сессий
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,  # Проверка соединения перед использованием
    pool_recycle=3600,   # Переподключение каждый час
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session():
    """Асинхронный контекстный менеджер для получения сессии БД"""
    session = async_session()
    try:
        yield session
    finally:
        await session.close()


async def init_db():
    """Инициализация базы данных"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ База данных инициализирована")