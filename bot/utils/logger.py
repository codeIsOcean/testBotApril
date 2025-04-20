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
            "text": f"<b>Log:</b>\n<pre>{message}</pre>",
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
            log_entry = self.format(record)
            print("🔧 Отправляем лог в Telegram:", log_entry)
            asyncio.create_task(self.send_log(log_entry))
        except Exception as e:
            print("❌ Ошибка логгера:", e)
