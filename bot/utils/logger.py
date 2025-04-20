import logging
import os
import aiohttp

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")


class TelegramLogHandler(logging.Handler):
    def __init__(self, level=logging.ERROR):
        super().__init__(level)

    async def send_log(self, message: str):
        if not BOT_TOKEN or not LOG_CHANNEL_ID:
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": LOG_CHANNEL_ID,
            "text": f"b>Log:</b>\n<pre>{message}</pre>",
            "parse_mode": "HTML"
        }
        async with aiohttp.ClientSession() as session:
            try:
                await session.post(url, data=payload)
            except Exception as e:
                print(f"Log send failed: {e}")

    def emit(self, record):
        try:
            log_entry = self.format(record)
            # запускаем отправку асинхроноо
        except Exception:
            self.handleError(record)