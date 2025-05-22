import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
# При инициализации бота добавьте параметр timeout
from aiogram.client.session.aiohttp import AiohttpSession

from bot.handlers import handlers_router
from bot.services.redis_conn import test_connection

from bot.config import BOT_TOKEN
from bot.database import engine, async_session
from bot.database.models import Base
from bot.middlewares.db_session import DbSessionMiddleware  # Добавляем импорт DbSessionMiddleware

# Логгер
import logging
from bot.utils.logger import TelegramLogHandler

# Настройка логгера
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Создаем обработчик для консоли
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Настройка Telegram-логгера для важных сообщений
tg_handler = TelegramLogHandler()
tg_handler.setLevel(logging.ERROR)  # Отправляем только ERROR и выше
tg_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
tg_handler.setFormatter(tg_formatter)
logger.addHandler(tg_handler)

# Настройка логгеров aiogram - только консоль для обычных логов
for logger_name in ("aiogram", "aiogram.dispatcher", "aiogram.event"):
    log = logging.getLogger(logger_name)
    log.addHandler(console_handler)
    # Для критических ошибок добавляем Telegram-логгер
    aiogram_tg_handler = TelegramLogHandler()
    aiogram_tg_handler.setLevel(logging.ERROR)
    aiogram_tg_handler.setFormatter(tg_formatter)
    log.addHandler(aiogram_tg_handler)
    log.propagate = False

# определяем, где мы запускаемся
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)  # Добавляем поддержку пароля


# главная асинхронная функция, запускающая бота
async def main():
    logging.info("🤖 Бот успешно запущен и готов к работе.")

    # Создаем отказоустойчивое хранилище - если Redis недоступен, используем MemoryStorage
    try:
        # пробуем подключиться к Redis
        await test_connection()
        redis_url = f"redis://{':' + REDIS_PASSWORD + '@' if REDIS_PASSWORD else ''}{REDIS_HOST}:{REDIS_PORT}"
        storage = RedisStorage.from_url(redis_url)
    except Exception as e:
        # В случае ошибки подключения к Redis используем MemoryStorage
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()
        logging.warning(f"⚠️ Ошибка подключения к Redis: {e}")
        logging.info("ℹ️ Используется MemoryStorage для хранения состояний (данные будут утеряны при перезапуске)")

    # ✅ (Опционально) создаём таблицы в БД на основе моделей (если они не существуют)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # ✅ Создание бота по токену из .env
    session = AiohttpSession(timeout=60.0)
    bot = Bot(token=BOT_TOKEN, session=session)
    # ✅ Создание диспетчера с хранилищем состояний и sessionmaker
    dp = Dispatcher(storage=storage)

    # ✅ Подключение middleware — будет автоматически прокидывать сессию в каждый хендлер
    dp.update.middleware(DbSessionMiddleware(async_session))

    # ✅ Подключение всех маршрутов (хендлеров), которые ты заранее определил
    dp.include_router(handlers_router)
    print(f"Подключен: {handlers_router}")
    # ✅ Запуск бота в режиме polling (опрос Telegram-серверов)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
