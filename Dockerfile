FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libpq-dev \
    netcat-openbsd \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    libtesseract-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Кэшируем зависимости (если requirements.txt не менялся)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем остальной код
COPY . .

# Устанавливаем переменные окружения (если нужно)
ENV PYTHONUNBUFFERED=1

# Команда запуска
CMD ["sh", "-c", "\
    until nc -z db 5432; do echo '⏳ Ждём PostgreSQL...'; sleep 1; done && \
    until nc -z redis 6379; do echo '⏳ Ждём Redis...'; sleep 1; done && \
    echo '✅ Все сервисы готовы! Запускаем миграции и бота...' && \
    alembic upgrade head && \
    python -m bot.main"]
