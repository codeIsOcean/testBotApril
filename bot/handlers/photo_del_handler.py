# Обработчик удаления фотографий с запрещенным контентом
import asyncio  # Для асинхронных задач и задержек
import re  # Для регулярных выражений при поиске запрещенных слов
import io  # Для работы с байтовыми данными
import os  # Для работы с файловой системой
import aiohttp  # Для асинхронных HTTP-запросов к API компьютерного зрения
import tempfile  # Для создания временных файлов
from datetime import datetime, timedelta  # Для работы с датами и временем
import pytesseract  # Для извлечения текста из изображений
from PIL import Image  # Для обработки изображений
from aiogram import Router, F  # Основные компоненты для создания обработчиков сообщений
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery  # Типы данных Telegram
from sqlalchemy import select, insert, update, delete  # Операции с базой данных

from bot.database.models import ChatSettings, UserRestriction  # Модели данных для БД
from bot.database.session import get_session  # Получение сессии для работы с БД
from bot.config import BOT_TOKEN

import logging
from bot.utils.logger import TelegramLogHandler

# Настраиваем логгер
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Проверяем, есть ли уже обработчики у логгера
if not logger.handlers:
    telegram_handler = TelegramLogHandler()
    logger.addHandler(telegram_handler)


# Создаем роутер для обработки сообщений
photo_del_router = Router()


# Общая функция для загрузки изображения по URL
async def download_image(image_url):
    tmp_file_path = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    return None, None
                img_bytes = await resp.read()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                    tmp_file.write(img_bytes)
                    tmp_file_path = tmp_file.name
                return tmp_file_path, img_bytes
    except Exception as e:
        logger.error(f"Ошибка при загрузке изображения: {str(e)}")
        return None, None
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.unlink(tmp_file_path)
            except Exception as e:
                logger.error(f"Ошибка при удалении временного файла: {str(e)}")


FORBIDDEN_WORDS = [
    'наркота', 'нарк', 'меф', 'мефедрон', 'секс', 'порно', '18+',
    'спайс', 'гашиш', 'кокаин', 'марихуана', 'травка', 'закладк',
    'клад', 'кладмен', 'телеграм', 't.me', '@', 'закладки', 'бот', 'соль', 'экстази',
    'weed', 'mdma', 'meth', 'amphetamine', 'кристалл', 'нюдс', 'nudes', 'cocaine'
]
FORBIDDEN_PATTERNS = [re.compile(r'\b' + re.escape(word) + r'\b') for word in FORBIDDEN_WORDS]
FORBIDDEN_TAGS = ['drugs', 'narcotic', 'weapon', 'nude', 'porn', 'nsfw', 'adult content']


@photo_del_router.message(F.photo)
async def handle_photo(message: Message):
    if message.chat.type in ['group', 'supergroup']:
        chat_id = message.chat.id
        user_id = message.from_user.id

        async with get_session() as session:
            query = select(ChatSettings).where(ChatSettings.chat_id == chat_id)
            result = await session.execute(query)
            settings = result.scalar_one_or_none()
            if not settings or not settings.enable_photo_filter:
                return

            chat_member = await message.chat.get_member(user_id)
            if chat_member.status in ['creator', 'administrator'] and settings.admins_bypass_photo_filter:
                return

        forbidden_content_found = False
        reason = ""
        found_words = []

        if message.caption:
            caption_lower = message.caption.lower()
            for pattern, word in zip(FORBIDDEN_PATTERNS, FORBIDDEN_WORDS):
                if pattern.search(caption_lower):
                    found_words.append(word)
            if found_words:
                forbidden_content_found = True
                reason = f"Запрещенный контент в подписи к фото: {', '.join(found_words)}"

        if not forbidden_content_found:
            photo = message.photo[-1]
            file_id = photo.file_id
            try:
                file = await message.bot.get_file(file_id)
                file_path = file.file_path
                file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

                is_forbidden, image_reason = await check_image_content(file_url)
                if is_forbidden:
                    forbidden_content_found = True
                    reason = image_reason

                if not forbidden_content_found:
                    image_text = await extract_text_from_image(file_url)
                    if image_text:
                        image_text_lower = image_text.lower()
                        for pattern, word in zip(FORBIDDEN_PATTERNS, FORBIDDEN_WORDS):
                            if pattern.search(image_text_lower):
                                forbidden_content_found = True
                                reason = f"Обнаружено запрещенное слово на изображении: {word}"
                                break
            except Exception as e:
                logger.error(f"Ошибка при проверке содержимого изображения: {str(e)}")

        if forbidden_content_found:
            try:
                await message.delete()

                async with get_session() as session:
                    query = select(ChatSettings).where(ChatSettings.chat_id == chat_id)
                    result = await session.execute(query)
                    settings = result.scalar_one_or_none()
                    mute_minutes = settings.photo_filter_mute_minutes if settings else 60

                until_date = datetime.now() + timedelta(minutes=mute_minutes)

                await message.chat.restrict(
                    user_id,
                    permissions=message.chat.permissions.model_copy(update={"can_send_messages": False}),
                    until_date=until_date
                )

                async with get_session() as session:
                    await session.execute(
                        insert(UserRestriction).values(
                            user_id=user_id,
                            chat_id=chat_id,
                            restriction_type="mute",
                            reason=reason,
                            expires_at=until_date
                        )
                    )
                    await session.commit()

                notification = await message.answer(
                    f"❌ Пользователь {message.from_user.mention_html()} отправил фото с запрещенным содержанием.\n"
                    f"🔇 Выдан мут на {mute_minutes} минут."
                )

                asyncio.create_task(delete_message_after_delay(message.bot, chat_id, notification.message_id, 30))

                logger.info(
                    f"Удалено фото с запрещенным содержанием от пользователя {user_id} в чате {chat_id}: {reason}"
                )

            except Exception as e:
                logger.error(f"Ошибка при удалении фото с запрещенным содержанием: {str(e)}")
