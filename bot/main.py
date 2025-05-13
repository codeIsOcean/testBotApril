import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
# При инициализации бота добавьте параметр timeout
from aiogram.client.session.aiohttp import AiohttpSession

from bot.services.redis_conn import test_connection

from bot.config import BOT_TOKEN
from bot.database import engine, async_session
from bot.database.models import Base
from bot.handlers.group_add_handler import group_add_handler
from bot.handlers.settings_inprivate_handler import settings_inprivate_handler
from bot.middlewares.db_session import DbSessionMiddleware
from bot.handlers.cmd_start_handler import cmd_start_router
from bot.handlers.group_setup_handler import group_setup_handler
from bot.handlers.new_member_requested_mute import new_member_requested_handler
from bot.handlers.user_captcha_handler import captcha_handler
from bot.handlers.group_settings_handler import group_settings_handler
from bot.handlers.photo_del_handler import photo_del_router

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
REDIS_HOST = "localhost" if os.getenv("LOCAL_RUN") else "redis"


@settings_inprivate_handler.callback_query()
async def fallback_callback_handler(callback: CallbackQuery):
    print(f"❌ Неверный формат данных в callback: {callback.data}")
    await callback.answer("⚠️ Неизвестная команда", show_alert=True)


# главная асинхронная функция, запускающая бота
async def main():
    logging.info("🤖 Бот успешно запущен и готов к работе.")
    await test_connection() # проверка подключения redis в redis_conn.py
    # ✅ (Опционально) создаём таблицы в БД на основе моделей (если они не существуют)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # подключение к Redis
    storage = RedisStorage.from_url(f"redis://{REDIS_HOST}:6379")
    # ✅ Создание бота по токену из .env
    session = AiohttpSession(timeout=60.0)
    bot = Bot(token=BOT_TOKEN, session=session)
    # ✅ Создание диспетчера с хранилищем состояний и sessionmaker
    dp = Dispatcher(storage=storage, sessionmaker=async_session)

    # ✅ Подключение middleware — будет автоматически прокидывать сессию в каждый хендлер
    dp.update.middleware(DbSessionMiddleware(async_session))
    # вложенные роутеры
    # 📦 Сначала подключаем settings_inprivate внутрь group_settings
    group_settings_handler.include_router(settings_inprivate_handler)

    # ✅ Подключение всех маршрутов (хендлеров), которые ты заранее определил
    dp.include_router(group_add_handler)
    dp.include_router(cmd_start_router)
    dp.include_router(group_setup_handler)
    dp.include_router(new_member_requested_handler)
    dp.include_router(captcha_handler)
    dp.include_router(photo_del_router)
    dp.include_router(group_settings_handler)

    print("✅ Бот запущен, все роутеры подключены")

    # ✅ Запуск бота в режиме polling (опрос Telegram-серверов)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
