import os
from dotenv import load_dotenv

# Всегда ищем .env относительно корня проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Получаем путь до .env файла
env_path = os.getenv("ENV_PATH", os.path.join(BASE_DIR, ".env.dev"))
print(f"📦 Загрузка env из: {env_path}")
load_dotenv(dotenv_path=env_path)

env_path = os.getenv("ENV_PATH", ".env.dev")
print(f"📦 Загрузка env из: {env_path}")
print(f"📁 Абсолютный путь: {os.path.abspath(env_path)}")
print(f"📂 Текущая рабочая директория: {os.getcwd()}")


# 🔄 Загружаем путь к .env
env_path = os.getenv("ENV_PATH", ".env.dev")
print(f"📦 Загрузка env из: {env_path}")

# ✅ Подгружаем переменные из файла
load_dotenv(dotenv_path=env_path)

# Теперь вытаскиваем переменные из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# ✅ Теперь можно печатать
print(f"🧪 BOT_TOKEN: {BOT_TOKEN}")
print(f"🧪 DATABASE_URL: {DATABASE_URL}")
print(f"🧪 LOG_CHANNEL_ID: {LOG_CHANNEL_ID}")
print(f"[DEBUG] BOT_TOKEN = {repr(BOT_TOKEN)}")

