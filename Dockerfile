FROM python:3.9

WORKDIR /app

ENV PYTHONPATH=/app

# Устанавливаем зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev \
    netcat-openbsd  # ✅ правильный пакет

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "while ! nc -z db 5432; do sleep 1; done && alembic upgrade head && python -m bot.main"]
