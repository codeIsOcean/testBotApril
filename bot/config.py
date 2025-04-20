from dotenv import load_dotenv
import os

load_dotenv()

# тут файл для конфиги и .env


BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")