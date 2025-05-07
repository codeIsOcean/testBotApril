# Обработчик удаления фотографий с запрещённым контентом
import asyncio
import re
import os
import aiohttp
import tempfile
from datetime import datetime, timedelta
from PIL import Image
from aiogram import Router, F
from aiogram.types import Message
from aiogram.types import ChatPermissions
from sqlalchemy import select, insert
import pytesseract

from bot.database.models import ChatSettings, UserRestriction
from bot.database.session import get_session
from bot.config import BOT_TOKEN

import logging
from bot.utils.logger import TelegramLogHandler
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# Настройка логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    telegram_handler = TelegramLogHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    telegram_handler.setFormatter(formatter)
    logger.addHandler(telegram_handler)

photo_del_router = Router()

FORBIDDEN_WORDS = [
    'доставка', 'работаем', 'ищите', 'поиск', 'поиске', 'в поиске', 'впоиске',
    'гарантия', 'отзывы', 'отработки', 'клад', 'закладки', 'закладка', 'кладмен',
    'бот', 'бота', 'сделка', 'работа', 'сотрудничество', 'вакансии', 'ассортимент',
    'прайс', 'меню', 'каталог', 'выбор', 'сорт', 'дозы', 'нарк', 'меф', 'мефедрон',
    'соль', 'скорость', 'амф', 'амфетамин', 'героин', 'спайс', 'лсд', 'экстази',
    'мдма', 'mdma', 'мет', 'meth', 'травка', 'марихуана', 'косяк', 'дурь', 'гашиш',
    'кокаин', 'крэк', 'порошок', 'таблетки', 'капсулы', 'фен', 'нюдс', 'nudes',
    '18+', 'порно', 'секс', 'эротика', 't.me', '@', '.onion', '.tor', 'чат',
    'саппорт', 'свяжитесь', 'телега', 'telegram', 'телеграм', 'вк', 'insta',
    'whatsapp', 'вайбер', 'вебкам', 'закрытая группа', 'клуб', 'схема', 'точка',
    'шишки', 'грибочки', 'блант', 'кристаллы', 'таблэт', 'план', 'тг бот',
    'скидка', 'проверено', 'опт', 'оптом', 'курьер', 'заказ', 'клиент',
    'тестеры', 'прием'
]
FORBIDDEN_PATTERNS = [re.compile(re.escape(word), re.IGNORECASE) for word in FORBIDDEN_WORDS]
FORBIDDEN_TAGS = ['drugs', 'narcotic', 'weapon', 'nude', 'porn', 'nsfw', 'adult content']


@photo_del_router.message(F.photo)
async def handle_photo(message: Message):
    if message.chat.type not in ['group', 'supergroup']:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    async with get_session() as session:
        result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
        settings = result.scalar_one_or_none()
        if not settings or not settings.enable_photo_filter:
            return

    chat_member = await message.chat.get_member(user_id)
    if chat_member.status in ['creator', 'administrator'] and settings.admins_bypass_photo_filter:
        return

    forbidden_content_found = False
    reason = ""

    if message.caption:
        caption_lower = message.caption.lower()
        for pattern, word in zip(FORBIDDEN_PATTERNS, FORBIDDEN_WORDS):
            if pattern.search(caption_lower):
                forbidden_content_found = True
                reason = f"Запрещённый контент в подписи: {word}"
                break

    if not forbidden_content_found:
        try:
            photo = message.photo[-1]
            file = await message.bot.get_file(photo.file_id)
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

            is_forbidden, image_reason = await check_image_content(file_url)
            if is_forbidden:
                forbidden_content_found = True
                reason = image_reason
            else:
                image_text = await extract_text_from_image(file_url)
                logger.info(f"OCR текст: {image_text}")
                for pattern, word in zip(FORBIDDEN_PATTERNS, FORBIDDEN_WORDS):
                    if pattern.search(image_text.lower()):
                        forbidden_content_found = True
                        reason = f"Запрещённое слово на изображении: {word}"
                        break
        except Exception as e:
            logger.error(f"Ошибка при анализе изображения: {e}")

    if forbidden_content_found:
        try:
            await message.delete()
            # Определяем время мута
            if settings.photo_filter_mute_minutes == 0:  # 0 означает мут навсегда
                until_date = None  # None для вечного мута
            else:
                until_date = datetime.now() + timedelta(minutes=int(settings.photo_filter_mute_minutes) if isinstance(settings.photo_filter_mute_minutes, (int, str)) and str(settings.photo_filter_mute_minutes).isdigit() else 60)

            await message.chat.restrict(
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )

            async with get_session() as session:
                await session.execute(insert(UserRestriction).values(
                    user_id=user_id, chat_id=chat_id, restriction_type="mute",
                    reason=reason, expires_at=until_date))
                await session.commit()

                # Отправляем уведомление в логи/канал вместо группы
                log_message = (
                    f"🚫 <b>Фильтр фото сработал</b>\n"
                    f"👤 Пользователь: {message.from_user.full_name} (<code>{user_id}</code>)\n"
                    f"👥 Группа: {message.chat.title} (<code>{chat_id}</code>)\n"
                    f"⏱ Мут на: {int(settings.photo_filter_mute_minutes) if isinstance(settings.photo_filter_mute_minutes, (int, str)) and str(settings.photo_filter_mute_minutes).isdigit() else 60} минут\n"
                    f"📝 Причина: {reason}"
                )

                # Отправка в специальный канал для логов вместо группы
                log_channel_id = settings.log_channel_id
                if log_channel_id:
                    try:
                        await message.bot.send_message(log_channel_id, log_message, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Ошибка отправки в канал логов: {e}")

                # Если в настройках включено отображение в группе, показываем сокращенное сообщение
                if settings.show_mute_notifications:
                    group_msg = await message.answer(
                        f"🚫 {message.from_user.mention_html()} получил мут за запрещенное содержимое.",
                        parse_mode="HTML"
                    )
                    asyncio.create_task(delete_message_after_delay(message.bot, chat_id, group_msg.message_id, 30))

                logger.info(f"Наказан пользователь {user_id} в чате {chat_id}: {reason}")
            logger.info(f"Удалено сообщение от {user_id} в чате {chat_id}: {reason}")
        except Exception as e:
            logger.error(f"Ошибка при применении наказания: {e}")


async def delete_message_after_delay(bot, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Ошибка удаления уведомления: {e}")


async def extract_text_from_image(image_url: str) -> str:
    tmp_file_path, _ = await download_image(image_url)
    if not tmp_file_path:
        return ""
    try:
        if not os.path.exists(pytesseract.pytesseract.tesseract_cmd):
            logger.warning("Tesseract не установлен, OCR будет пропущен")
            return ""
        image = Image.open(tmp_file_path)
        return pytesseract.image_to_string(image, lang='rus+eng')
    except Exception as e:
        logger.error(f"Ошибка OCR: {e}")
        return ""
    finally:
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

async def check_image_with_yolov5(image_url: str) -> tuple[bool, str]:
    tmp_file_path, _ = await download_image(image_url)
    if not tmp_file_path:
        return False, ""
    try:
        from ultralytics import YOLO
        model = YOLO('yolov5su.pt')
        results = model(tmp_file_path)
        for result in results:
            for cls, conf in zip(result.boxes.cls.tolist(), result.boxes.conf.tolist()):
                class_name = model.names[int(cls)]
                if class_name.lower() in FORBIDDEN_TAGS and conf > 0.5:
                    return True, f"Обнаружен объект: {class_name}"
        return False, ""
    except Exception as e:
        logger.error(f"YOLOv5 ошибка: {e}")
        return False, ""
    finally:
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)


async def check_image_with_opennsfw2(image_url: str) -> tuple[bool, str]:
    # Комментируем весь функционал NSFW проверки
    # tmp_file_path, img_bytes = await download_image(image_url)
    # if not tmp_file_path:
    #     return False, ""
    #
    # try:
    #     import numpy as np
    #     import tensorflow as tf
    #     from tensorflow.keras.models import load_model
    #     from tensorflow.keras.applications import VGG16
    #     from tensorflow.keras.layers import Dense, Dropout, GlobalAveragePooling2D
    #     from tensorflow.keras.models import Model
    #
    #     model_path = os.path.join('models', 'open_nsfw_weights.h5')
    #     os.makedirs(os.path.dirname(model_path), exist_ok=True)
    #
    #     # Проверка наличия модели или её создание
    #     if not os.path.exists(model_path) or os.path.getsize(model_path) < 100000:
    #         logger.warning("Модель OpenNSFW2 не найдена или повреждена. Используем заглушку.")
    #         # Используем заглушку на основе вероятностного анализа изображения
    #         image = Image.open(tmp_file_path)
    #         # Простая проверка на основе цветового анализа (очень упрощённо)
    #         img_array = np.array(image)
    #         skin_tone_ratio = np.sum((img_array[:, :, 0] > 60) & (img_array[:, :, 0] < 200) &
    #                                  (img_array[:, :, 1] > 40) & (img_array[:, :, 1] < 170) &
    #                                  (img_array[:, :, 2] > 20) & (img_array[:, :, 2] < 170)) / img_array.size
    #
    #         nsfw_score = min(skin_tone_ratio * 4, 0.5)  # Искусственное ограничение вероятности
    #
    #         if nsfw_score > 0.4:
    #             return True, f"Возможный NSFW контент (приблизительная оценка {nsfw_score:.2f})"
    #
    #         return False, ""
    #
    #     # Загрузка модели
    #     model = load_model(model_path, compile=False)
    #
    #     def preprocess_image(image, target_size):
    #         if image.mode != "RGB":
    #             image = image.convert("RGB")
    #         image = image.resize(target_size, Image.NEAREST)
    #         return np.expand_dims(np.array(image) / 255.0, axis=0)
    #
    #     image = Image.open(tmp_file_path)
    #     prediction = model.predict(preprocess_image(image, (224, 224)))[0]
    #     nsfw_score = float(prediction[1]) if len(prediction) > 1 else 0.0
    #
    #     if nsfw_score > 0.6:
    #         return True, f"NSFW контент (вероятность {nsfw_score:.2f})"
    #
    #     return False, ""
    # except Exception as e:
    #     logger.error(f"OpenNSFW2 ошибка: {e}")
    #     return False, ""
    # finally:
    #     if os.path.exists(tmp_file_path):
    #         os.remove(tmp_file_path)

    # Возвращаем всегда отрицательный результат, чтобы не мешать тестированию
    logger.info("NSFW проверка временно отключена")
    return False, ""


async def check_image_content(image_url: str) -> tuple[bool, str]:
    try:
        is_forbidden, reason = await check_image_with_yolov5(image_url)
        if is_forbidden:
            return True, reason

        # Временно отключаем проверку NSFW
        # is_forbidden, reason = await check_image_with_opennsfw2(image_url)
        # if is_forbidden:
        #     return True, reason

        return False, ""
    except Exception as e:
        logger.error(f"Ошибка анализа изображения: {e}")
        return False, ""


async def download_image(image_url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка загрузки изображения. Код: {resp.status}")
                    return None, None
                img_bytes = await resp.read()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                    tmp_file.write(img_bytes)
                    return tmp_file.name, img_bytes
    except Exception as e:
        logger.error(f"Ошибка загрузки изображения: {e}")
        return None, None
