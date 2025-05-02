from redis.asyncio import Redis
import logging

logger = logging.getLogger(__name__)

try:
    redis = Redis(host='localhost', port=6379, db=0, decode_responses=True)


    # Проверяем подключение при запуске
    async def test_connection():
        try:
            await redis.ping()
            logger.info("✅ Соединение с Redis установлено")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Redis: {e}")
except Exception as e:
    logger.error(f"❌ Критическая ошибка Redis при инициализации: {e}")
    redis = None
