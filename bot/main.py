import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from bot.config import BOT_TOKEN
from bot.database import engine, async_session
from bot.database.models import Base
from bot.handlers.group_add_handler import group_add_handler
from bot.middlewares.db_session import DbSessionMiddleware
from bot.handlers.cmd_start_handler import cmd_start_router
from bot.handlers.group_setup_handler import group_setup_handler

# Логгер
import logging
from bot.utils.logger import TelegramLogHandler

# Настройка логгера
logger = logging.getLogger()
logger.setLevel(logging.INFO)

tg_handler = TelegramLogHandler()
tg_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
tg_handler.setFormatter(formatter)

logger.addHandler(tg_handler)

# Подключаем обработчик также ко всем aiogram-логгерам
for logger_name in ("aiogram", "aiogram.dispatcher", "aiogram.event"):
    log = logging.getLogger(logger_name)
    log.addHandler(tg_handler)
    log.propagate = False

# определяем, где мы запускаемся
REDIS_HOST = "localhost" if os.getenv("LOCAL_RUN") else "redis"


# главная асинхронная функция, запускающая бота
async def main():
    logging.info("🤖 Бот успешно запущен и готов к работе.")

    # ✅ (Опционально) создаём таблицы в БД на основе моделей (если они не существуют)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # подключение к Redis
    storage = RedisStorage.from_url(f"redis://{REDIS_HOST}:6379")
    # ✅ Создание бота по токену из .env
    bot = Bot(token=BOT_TOKEN)
    # ✅ Создание диспетчера с хранилищем состояний и sessionmaker
    dp = Dispatcher(storage=storage, sessionmaker=async_session)

    # ✅ Подключение middleware — будет автоматически прокидывать сессию в каждый хендлер
    dp.update.middleware(DbSessionMiddleware(async_session))

    # ✅ Подключение всех маршрутов (хендлеров), которые ты заранее определил
    dp.include_router(group_add_handler)
    dp.include_router(cmd_start_router)
    dp.include_router(group_setup_handler)

    print("✅ Бот запущен, все роутеры подключены")

    # ✅ Запуск бота в режиме polling (опрос Telegram-серверов)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
