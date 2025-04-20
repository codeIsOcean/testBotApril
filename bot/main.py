import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN
from bot.database import engine, async_session
from bot.models import Base
from bot.middlewares.db_session import DbSessionMiddleware
from bot.utils.logger import TelegramLogHandler
from bot.handlers import router


# главная асинхронная функция, запускающая бота
async def main():
    # Логгер
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = TelegramLogHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # ✅ (Опционально) создаём таблицы в БД на основе моделей (если они не существуют)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ✅ Создание бота по токену из .env
    bot = Bot(token=BOT_TOKEN)
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
