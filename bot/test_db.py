import os
import asyncio
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()


async def main():
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        print("✅ Успешное подключение к базе данных!")
        await conn.close()
    except Exception as e:
        print("❌ Ошибка подключения:", e)


asyncio.run(main())
