import logging
import os
import aiohttp
import asyncio

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")


class TelegramLogHandler(logging.Handler):
    def __init__(self, level=logging.INFO):
        super().__init__(level)

    async def send_log(self, message: str):
        if not BOT_TOKEN or not LOG_CHANNEL_ID:
            print("❗ BOT_TOKEN или LOG_CHANNEL_ID не установлены")
            return

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": LOG_CHANNEL_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
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
            # Безопасное получение времени (проверяем, есть ли formatter)
            if self.formatter:
                timestamp = self.formatter.formatTime(record, "%Y-%m-%d %H:%M:%S")
            else:
                # Если formatter не установлен, используем стандартный формат
                timestamp = logging.Formatter().formatTime(record, "%Y-%m-%d %H:%M:%S")

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
                f"{icon} {level} | {timestamp}\n"
                f"{record.getMessage()}"
            )

            # Не отправлять в Telegram стандартные информационные сообщения о капче
            if (
                    "успешно прошел капчу" not in record.getMessage() and
                    "Отправлена капча пользователю" not in record.getMessage() and
                    "не решил капчу вовремя" not in record.getMessage()
            ):
                asyncio.create_task(self.send_log(message))

        except Exception as e:
            print("❌ Ошибка логгера:", e)


# ==== СПЕЦИАЛЬНЫЕ ФОРМАТИРОВАННЫЕ ЛОГИ ДЛЯ TELEGRAM ====

async def send_formatted_log(message):
    """Отправляет отформатированное сообщение в канал логов в Telegram"""
    if not BOT_TOKEN or not LOG_CHANNEL_ID:
        print("❗ BOT_TOKEN или LOG_CHANNEL_ID не установлены")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": LOG_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    async with aiohttp.ClientSession() as session:
        try:
            resp = await session.post(url, data=payload)
            if resp.status != 200:
                text = await resp.text()
                print(f"❌ Telegram API Error: {resp.status} — {text}")
        except Exception as e:
            print(f"❌ Ошибка при отправке лога в Telegram: {e}")


def log_new_user(username, user_id, chat_name, chat_id, message_id=None):
    """Отправляет лог о новом пользователе с хэштегами"""
    # Проверяем, является ли username строкой (защита от None)
    user_display = f"<a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a>"

    msg = (
        f"➕ #НОВЫЙ_ПОЛЬЗОВАТЕЛЬ 🟢\n"
        f"• Кто: {user_display} [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
    )

    if message_id:
        msg += f"• 👀 Посмотреть сообщения (http://t.me/c/{str(chat_id).replace('-100', '')}/{message_id})\n"

    msg += f"#id{user_id}"

    # Выводим в консоль для информации
    print(f"📱 Логируем нового пользователя: {username} в группе {chat_name}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_captcha_solved(username, user_id, chat_name, chat_id, method="Кнопка"):
    """Отправляет лог об успешном решении капчи"""
    msg = (
        f"✅ #КАПЧА_РЕШЕНА 🟢\n"
        f"• Кто: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"• Метод: {method}\n"
        f"#id{user_id}"
    )

    # Выводим в консоль для информации
    print(f"📱 Капча решена пользователем: {username} в группе {chat_name}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_user_banned(username, user_id, chat_name, chat_id, reason="Спам"):
    """Отправляет лог о бане пользователя"""
    msg = (
        f"🚫 #ПОЛЬЗОВАТЕЛЬ_ЗАБАНЕН 🔴\n"
        f"• Кто: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"• Причина: {reason}\n"
        f"#id{user_id}"
    )

    # Выводим в консоль для информации
    print(f"📱 Пользователь {username} забанен в группе {chat_name}: {reason}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_join_request(username, user_id, chat_name, chat_id):
    """Отправляет лог о запросе на вступление в группу"""
    msg = (
        f"📬 #ЗАПРОС_НА_ВСТУПЛЕНИЕ 🔵\n"
        f"• Кто: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"#id{user_id}"
    )

    # Выводим в консоль для информации
    print(f"📱 Запрос на вступление от {username} в группу {chat_name}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_captcha_failed(username, user_id, chat_name, chat_id, method="Кнопка"):
    """Отправляет лог о неудачной попытке решения капчи"""
    msg = (
        f"📬 #ЗАПРОС_НА_ВСТУПЛЕНИЕ 🔴 #капчанерешена\n"
        f"• Кто: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"#id{user_id} #КАПЧА_НЕ_УДАЛАСЬ #{method}"
    )

    # Выводим в консоль для информации
    print(f"📱 Капча не решена пользователем: {username} в группе {chat_name}, метод: {method}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))

def log_captcha_sent(username, user_id, chat_name, chat_id):
    """Отправляет лог об отправке капчи пользователю"""
    msg = (
        f"📢 #КАПЧА_ОТПРАВЛЕНА 🟡\n"
        f"• Кому: <a href='tg://user?id={user_id}'>{username if username else f'id{user_id}'}</a> [{user_id}]\n"
        f"• Группа: <a href='https://t.me/c/{str(chat_id).replace('-100', '')}/{str(chat_id).replace('-100', '')}'>{chat_name}</a> [{chat_id}]\n"
        f"#id{user_id}"
    )

    # Выводим в консоль для информации
    print(f"📱 Отправлена капча пользователю: {username} для входа в группу {chat_id}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))


def log_telegram_error(error_message, module_name="Не указан"):
    """Отправляет лог об ошибке Telegram API"""
    msg = (
        f"❌ #ОШИБКА_TELEGRAM 🔴\n"
        f"• Модуль: {module_name}\n"
        f"• Описание: {error_message}\n"
        f"#error #telegram_api"
    )

    # Выводим в консоль для информации
    print(f"📱 Ошибка Telegram API: {error_message}")
    # Создаем задачу для асинхронной отправки в Telegram
    asyncio.create_task(send_formatted_log(msg))