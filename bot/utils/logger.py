import logging
import os
import aiohttp
import asyncio

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")


class TelegramLogHandler(logging.Handler):
    def __init__(self, level=logging.INFO):  # теперь ловим всё, не только ошибки
        super().__init__(level)

    async def send_log(self, message: str):
        if not BOT_TOKEN or not LOG_CHANNEL_ID:
            print("❗ BOT_TOKEN или LOG_CHANNEL_ID не установлены")
            return

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": LOG_CHANNEL_ID,
            "text": f"🧾 <b>Log Entry:</b>\n<pre>{message}</pre>",
            "parse_mode": "HTML"
        }

        async with aiohttp.ClientSession() as session:
            try:
                resp = await session.post(url, data=payload)
                if resp.status != 200:
                    text = await resp.text()
                    print(f"❌ Telegram API Error: {resp.status} — {text}")
            except Exception as e:
                print(f"❌ Ошибка при отправке лога в Telegram: {e}")

    def emit(self, record):
        try:
            # ✅ Правильное форматирование времени через связанный formatter
            timestamp = self.formatter.formatTime(record, "%Y-%m-%d %H:%M:%S")
            level = record.levelname
            emojis = {
                "DEBUG": "🔍",
                "INFO": "📢",
                "WARNING": "⚠️",
                "ERROR": "❗",
                "CRITICAL": "🔥"
            }
            icon = emojis.get(level, "📝")

            # 💬 Основной текст
            message = (
                f"{icon} <b>{level}</b> | 🕒 {timestamp}\n"
                f"<pre>{record.getMessage()}</pre>"
            )

            print("🔧 Отправляем лог в Telegram:", message)
            asyncio.create_task(self.send_log(message))

        except Exception as e:
            print("❌ Ошибка логгера:", e)

