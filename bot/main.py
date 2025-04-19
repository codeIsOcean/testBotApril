import asyncio
import os
from typing import Callable, Awaitable, Dict, Any

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import TelegramObject  # базовый тип Telegram событий (сообщения, команды, колбэки и т.д.)
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from bot.handlers import router  # объединённый роутер
from bot.models import Base

# ✅ Загрузка переменных окружения
load_dotenv()


# ✅ Middleware для передачи сессии в хендлеры
class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker):
        super().__init__()
        self.sessionmaker = sessionmaker  #сохраняем фабрику сесси

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
    ) -> Any:
        async with self.sessionmaker() as session:  # открываем сессию на каждый запрос/апдейт
            data["session"] = session  # передаем сессию в хендлер через context data
            return await handler(event, data)  # вызываем хендлер


# главная асинхронная функция, запускающая бота
async def main():
    # ✅ Создание асинхронного движка SQLAlchemy (ссылка из .env -> DATABASE_URL)
    engine = create_async_engine(os.getenv("DATABASE_URL"))
    # Создание sessionmaker — фабрики для создания сессий к БД
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # ✅ (Опционально) создаём таблицы в БД на основе моделей (если они не существуют)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ✅ Создание бота по токену из .env
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    # ✅ Создание диспетчера с хранилищем состояний и sessionmaker
    dp = Dispatcher(storage=MemoryStorage(), sessionmaker=async_session)

    # ✅ Подключение middleware — будет автоматически прокидывать сессию в каждый хендлер
    dp.update.middleware(DbSessionMiddleware(async_session))

    # ✅ Подключение всех маршрутов (хендлеров), которые ты заранее определил
    dp.include_router(router)

    # ✅ Запуск бота в режиме polling (опрос Telegram-серверов)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
