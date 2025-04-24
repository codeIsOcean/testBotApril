from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import os
from dotenv import load_dotenv

from bot.config import DATABASE_URL

# загружаем .env
load_dotenv(dotenv_path=os.getenv("ENV_PATH", "env.dev"))

DATABASE_URL = os.getenv("DATABASE_URL")

# создаем движок и фабрику сессий
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)