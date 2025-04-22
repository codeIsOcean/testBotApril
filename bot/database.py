from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from bot.config import DATABASE_URL

# тут файл для движка и сессии
print("DEBUG: DATABASE_URL =", DATABASE_URL)

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)