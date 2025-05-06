# Обработчик удаления фотографий с запрещенным контентом
import asyncio  # Для асинхронных задач и задержек
import re  # Для регулярных выражений при поиске запрещенных слов
import io  # Для работы с байтовыми данными
import aiohttp  # Для асинхронных HTTP-запросов к API компьютерного зрения
from datetime import datetime, timedelta  # Для работы с датами и временем
from aiogram import Router, F  # Основные компоненты для создания обработчиков сообщений
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery  # Типы данных Telegram
from sqlalchemy import select, insert, update, delete  # Операции с базой данных

from bot.database.models import ChatSettings, UserRestriction  # Модели данных для БД
from bot.database.connection import get_session  # Получение сессии для работы с БД
from bot.services.settings_service import get_chat_settings  # Сервис для получения настроек чата
from bot.utils.logger import get_logger  # Логгер для записи событий
from bot.config import config  # Конфигурация бота (токены, ключи API)

# Создаем роутер для обработки сообщений
photo_del_router = Router()
logger = get_logger(__name__)

# Список запрещенных слов для проверки в текстовых сообщениях
FORBIDDEN_WORDS = [
    'наркота', 'нарк', 'меф', 'мефедрон', 'секс', 'порно', '18+',
    'спайс', 'гашиш', 'кокаин', 'марихуана', 'травка', 'закладк'
]

# Список запрещенных тегов для анализа изображений через API компьютерного зрения
FORBIDDEN_TAGS = ['drugs', 'narcotic', 'weapon', 'nude', 'porn', 'nsfw', 'adult content']


# Обработчик фотографий - срабатывает при отправке фото в чат
@photo_del_router.message(F.photo)
async def handle_photo(message: Message):
    """Обработчик фотографий с проверкой на запрещенный контент"""
    # Проверяем, что сообщение отправлено в групповой чат
    if message.chat.type in ['group', 'supergroup']:
        chat_id = message.chat.id
        user_id = message.from_user.id

        # Проверяем, включена ли функция в настройках чата
        async with get_session() as session:
            settings = await get_chat_settings(session, chat_id)
            if not settings or not settings.enable_photo_filter:
                return  # Если функция отключена - завершаем обработку

            # Если отправитель админ и настройка разрешает админам отправлять фото - не проверяем их сообщения
            chat_member = await message.chat.get_member(user_id)
            if chat_member.status in ['creator', 'administrator'] and settings.admins_bypass_photo_filter:
                return

        forbidden_content_found = False  # Флаг наличия запрещенного контента
        reason = ""  # Причина блокировки
        found_words = []  # Найденные запрещенные слова

        # ЭТАП 1: Проверяем текст подписи к фото (если есть)
        if message.caption:
            # Преобразуем текст в нижний регистр для нечувствительного к регистру поиска
            caption_lower = message.caption.lower()

            # Проверяем каждое запрещенное слово
            for word in FORBIDDEN_WORDS:
                # Используем регулярное выражение для поиска целых слов (а не части слов)
                if re.search(r'\b' + re.escape(word) + r'\b', caption_lower):
                    found_words.append(word)

            # Если найдены запрещенные слова - помечаем контент как запрещенный
            if found_words:
                forbidden_content_found = True
                reason = f"Запрещенный контент в подписи к фото: {', '.join(found_words)}"

        # ЭТАП 2: Если по тексту ничего не нашли, проверяем само изображение через API
        if not forbidden_content_found:
            # Получаем фото в максимальном качестве (последний элемент в списке - самый большой размер)
            photo = message.photo[-1]
            file_id = photo.file_id

            # Проверяем само изображение через API компьютерного зрения
            try:
                # Получаем файл через Telegram Bot API
                file = await message.bot.get_file(file_id)
                file_path = file.file_path
                # Формируем URL для скачивания файла
                file_url = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file_path}"

                # Отправляем изображение на проверку
                is_forbidden, image_reason = await check_image_content(file_url)
                if is_forbidden:
                    forbidden_content_found = True
                    reason = image_reason
            except Exception as e:
                logger.error(f"Ошибка при проверке содержимого изображения: {str(e)}")

        # ЭТАП 3: Если найден запрещенный контент, принимаем меры
        if forbidden_content_found:
            try:
                # Удаляем сообщение с запрещенным контентом
                await message.delete()

                # Определяем длительность мута из настроек чата
                async with get_session() as session:
                    settings = await get_chat_settings(session, chat_id)
                    mute_minutes = settings.photo_filter_mute_minutes if settings else 60

                # Рассчитываем время окончания мута
                until_date = datetime.now() + timedelta(minutes=mute_minutes)

                # Мутим пользователя в чате
                await message.chat.restrict(
                    user_id,
                    permissions=message.chat.permissions.model_copy(
                        update={"can_send_messages": False}
                    ),
                    until_date=until_date
                )

                # Сохраняем информацию о муте в базу данных
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

                # Отправляем уведомление в чат о применённых мерах
                notification = await message.answer(
                    f"❌ Пользователь {message.from_user.mention_html()} отправил фото с запрещенным содержанием.\n"
                    f"🔇 Выдан мут на {mute_minutes} минут."
                )

                # Удаляем уведомление через 30 секунд для чистоты чата
                asyncio.create_task(
                    delete_message_after_delay(message.bot, chat_id, notification.message_id, 30)
                )

                # Логируем событие
                logger.info(
                    f"Удалено фото с запрещенным содержанием от пользователя {user_id} в чате {chat_id}: {reason}"
                )

            except Exception as e:
                logger.error(f"Ошибка при удалении фото с запрещенным содержанием: {str(e)}")


# Функция для проверки содержимого изображения через API компьютерного зрения
async def check_image_content(image_url):
    """
    Проверяет изображение на запрещенный контент через API компьютерного зрения

    Возвращает: (bool, str) - (найден ли запрещенный контент, причина)
    """
    try:
        # Интеграция с Azure Computer Vision API (пример)
        async with aiohttp.ClientSession() as session:
            # API ключ и заголовки запроса
            headers = {
                'Ocp-Apim-Subscription-Key': config.VISION_API_KEY,
                'Content-Type': 'application/json'
            }

            # Формируем запрос к API
            vision_url = f"{config.VISION_API_ENDPOINT}/vision/v3.1/analyze"
            # Запрашиваем анализ содержимого для взрослого контента и описание изображения
            params = {'visualFeatures': 'Adult,Tags,Description'}
            body = {"url": image_url}

            # Отправляем запрос и получаем результат
            async with session.post(vision_url, headers=headers, params=params, json=body) as response:
                if response.status == 200:
                    result = await response.json()

                    # Проверяем на взрослый контент (порно, 18+)
                    if 'adult' in result:
                        adult_data = result['adult']
                        # Проверяем метрики оценки взрослого контента с высоким порогом уверенности
                        if adult_data.get('isAdultContent', False) and adult_data.get('adultScore', 0) > 0.7:
                            return True, "Обнаружен взрослый контент на изображении"
                        if adult_data.get('isRacyContent', False) and adult_data.get('racyScore', 0) > 0.8:
                            return True, "Обнаружен неприемлемый контент на изображении"

                    # Проверяем на запрещенные теги (наркотики, оружие и т.д.)
                    if 'tags' in result:
                        for tag in result['tags']:
                            # Проверяем совпадение с запрещенными тегами
                            if any(forbidden.lower() in tag['name'].lower() for forbidden in FORBIDDEN_TAGS) and tag[
                                'confidence'] > 0.7:
                                return True, f"Обнаружен запрещенный контент: {tag['name']}"

                    # Проверяем описание изображения
                    if 'description' in result and 'captions' in result['description']:
                        for caption in result['description']['captions']:
                            caption_text = caption['text'].lower()
                            # Проверяем совпадение описания с запрещенными словами
                            for word in FORBIDDEN_WORDS:
                                if word.lower() in caption_text and caption['confidence'] > 0.7:
                                    return True, f"Обнаружен запрещенный контент в изображении: {word}"

        # Здесь можно добавить проверки через другие API для большей точности

        # Если запрещенный контент не найден
        return False, ""

    except Exception as e:
        logger.error(f"Ошибка при проверке изображения: {str(e)}")
        # В случае ошибки пропускаем изображение (разрешаем)
        return False, ""


# Вспомогательная функция для удаления сообщений с задержкой
async def delete_message_after_delay(bot, chat_id, message_id, delay_seconds):
    """Удаляет сообщение после указанной задержки"""
    await asyncio.sleep(delay_seconds)  # Ждем указанное время
    try:
        await bot.delete_message(chat_id, message_id)  # Удаляем сообщение
        print(f"✅ Сообщение {message_id} удалено из чата {chat_id} после задержки {delay_seconds} сек")
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения {message_id} в чате {chat_id}: {str(e)}")
        print(f"❌ Ошибка при удалении сообщения {message_id} в чате {chat_id}: {str(e)}")


# УПРАВЛЕНИЕ НАСТРОЙКАМИ ФИЛЬТРА ФОТОГРАФИЙ

# Обработчик включения/выключения фильтра фото в настройках
@photo_del_router.callback_query(F.data == "toggle_photo_filter")
async def toggle_photo_filter(callback: CallbackQuery):
    """Включение/выключение фильтра фото"""
    # Проверяем, что колбэк пришел в приватном чате (настройки доступны только в личке с ботом)
    if callback.message and callback.message.chat.id == callback.from_user.id:
        # Получаем ID чата, для которого меняются настройки
        chat_id = int(callback.data.split('_')[-1]) if '_' in callback.data else None

        if not chat_id:
            await callback.answer("Ошибка: не удалось определить идентификатор чата", show_alert=True)
            return

        # Получаем текущие настройки и инвертируем состояние фильтра
        async with get_session() as session:
            settings = await get_chat_settings(session, chat_id)
            new_state = not (settings.enable_photo_filter if settings else False)

            # Обновляем настройки в БД
            if settings:
                await session.execute(
                    update(ChatSettings).where(
                        ChatSettings.chat_id == chat_id
                    ).values(
                        enable_photo_filter=new_state
                    )
                )
            else:
                # Если настройки не существуют, создаем их
                await session.execute(
                    insert(ChatSettings).values(
                        chat_id=chat_id,
                        enable_photo_filter=new_state
                    )
                )

            await session.commit()

        # Показываем уведомление о смене настройки
        await callback.answer(
            f"Фильтр фото {'включен' if new_state else 'выключен'} для выбранного чата",
            show_alert=True
        )

        # Здесь должна быть функция обновления клавиатуры настроек


# Обработчик для изменения времени мута за запрещенные фото
@photo_del_router.callback_query(F.data == "set_photo_filter_mute_time")
async def set_photo_filter_mute_time(callback: CallbackQuery):
    """Изменение времени мута за запрещенные фото"""
    if callback.message and callback.message.chat.id == callback.from_user.id:
        chat_id = int(callback.data.split('_')[-1]) if '_' in callback.data else None

        if not chat_id:
            await callback.answer("Ошибка: не удалось определить идентификатор чата", show_alert=True)
            return

        # Создаем клавиатуру с временными интервалами
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="15 минут", callback_data=f"set_photo_mute_time_15_{chat_id}"),
                InlineKeyboardButton(text="30 минут", callback_data=f"set_photo_mute_time_30_{chat_id}")
            ],
            [
                InlineKeyboardButton(text="1 час", callback_data=f"set_photo_mute_time_60_{chat_id}"),
                InlineKeyboardButton(text="3 часа", callback_data=f"set_photo_mute_time_180_{chat_id}")
            ],
            [
                InlineKeyboardButton(text="1 день", callback_data=f"set_photo_mute_time_1440_{chat_id}"),
                InlineKeyboardButton(text="Назад", callback_data=f"chat_settings_{chat_id}")
            ]
        ])

        # Обновляем сообщение с новой клавиатурой
        await callback.message.edit_text(
            "Выберите время мута за отправку запрещенных фотографий:",
            reply_markup=keyboard
        )

        await callback.answer()


# Обработчик выбора времени мута
@photo_del_router.callback_query(lambda c: c.data.startswith("set_photo_mute_time_"))
async def process_photo_mute_time(callback: CallbackQuery):
    """Установка времени мута"""
    if callback.message and callback.message.chat.id == callback.from_user.id:
        # Разбираем данные из callback_data
        parts = callback.data.split('_')
        if len(parts) >= 5:
            minutes = int(parts[4])  # Количество минут мута
            chat_id = int(parts[5])  # ID чата

            # Сохраняем настройку в БД
            async with get_session() as session:
                settings = await get_chat_settings(session, chat_id)

                if settings:
                    # Обновляем существующие настройки
                    await session.execute(
                        update(ChatSettings).where(
                            ChatSettings.chat_id == chat_id
                        ).values(
                            photo_filter_mute_minutes=minutes
                        )
                    )
                else:
                    # Создаем новые настройки
                    await session.execute(
                        insert(ChatSettings).values(
                            chat_id=chat_id,
                            photo_filter_mute_minutes=minutes
                        )
                    )

                await session.commit()

            # Преобразуем минуты в удобочитаемый формат для уведомления
            time_text = f"{minutes} минут" if minutes < 60 else f"{minutes // 60} час(ов)" if minutes < 1440 else f"{minutes // 1440} день(дней)"

            # Показываем уведомление об изменении настройки
            await callback.answer(f"Время мута установлено: {time_text}", show_alert=True)

            # Здесь должен быть возврат в меню настроек чата
