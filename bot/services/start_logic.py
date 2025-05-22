# services/start_logic.py
import logging
from typing import Dict, Tuple, Optional, Any, Union

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.services.redis_conn import redis
from bot.database.models import User
from bot.keyboards.main_menu_keyboard import get_main_menu_buttons
from bot.config import ADMIN_IDS as ALLOWED_USERS
from bot.texts.messages import SUPPORT_TEXT, INFORMATION_TEXT


async def check_and_create_user(user_id: int, username: str, full_name: str, session: AsyncSession) -> bool:
    """
    Проверяет наличие пользователя в БД и создает его, если не существует
    Возвращает True, если это админ
    """
    # Проверка, есть ли пользователь в базе
    stmt = select(User).where(User.user_id == user_id)
    result = await session.execute(stmt)
    existing_user = result.scalar_one_or_none()

    if not existing_user:
        user = User(
            user_id=user_id,
            username=username,
            full_name=full_name
        )
        session.add(user)
        await session.commit()

    # Проверка, является ли пользователь администратором
    return user_id in ALLOWED_USERS


async def process_setup_deeplink(bot: Bot, user_id: int, group_id: str) -> Dict[str, Any]:
    """
    Обрабатывает deep link для настройки группы
    Возвращает словарь с результатами проверки и данными
    """
    result = {"success": False, "message": "", "title": "", "group_id": group_id}

    try:
        member = await bot.get_chat_member(int(group_id), user_id)
        if member.status not in ("administrator", "creator"):
            result["message"] = "❌ Вы не являетесь администратором этой группы и не можете настраивать бота."
            return result
    except Exception as e:
        logging.warning(f"Ошибка при проверке админства: {e}")
        result["message"] = "⚠️ Не удалось проверить ваши права в группе. Убедитесь, что бот добавлен в неё."
        return result

    await redis.hset(f"user:{user_id}", "group_id", group_id)

    # получаем название группы и отображение пользователю
    try:
        chat = await bot.get_chat(int(group_id))
        if chat.username:
            link = f"https://t.me/{chat.username}"
            title = f"[{chat.title}]({link})"
        else:
            title = f"{chat.title} (ID: `{group_id}`)"
        result["title"] = title
    except Exception:
        result["title"] = f"ID: `{group_id}`"

    result["success"] = True
    result[
        "message"] = (f"🔧 Вы начали настройку группы: {result['title']}\nИспользуйте доступные команды или /cancel "
                      f"для отмены.")
    return result


async def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру с кнопкой настроек"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть меню", callback_data="show_settings")]
    ])


async def process_captcha_deeplink(bot: Bot, user_id: int, deep_link_args: str) -> Dict[str, Any]:
    """
    Обрабатывает deep link для капчи
    Возвращает словарь с результатами проверки и данными
    """
    result = {"success": False, "message": "", "captcha_data": None}

    try:
        parts = deep_link_args.split("_")
        if len(parts) != 3:
            result["message"] = "❌ Неверный формат данных капчи."
            return result

        _, user_id_str, chat_id_str = parts
        target_user_id = int(user_id_str)
        chat_id = int(chat_id_str)

        # Проверяем, что запрос пришел от правильного пользователя
        if user_id != target_user_id:
            result["message"] = "⚠️ Эта ссылка не предназначена для вас."
            return result

        # Проверяем наличие активной капчи в Redis
        captcha_exists = await redis.get(f"captcha:{user_id}:{chat_id}")
        if not captcha_exists:
            result["message"] = "⏱️ Срок действия капчи истек или она уже решена. Отправьте новый запрос в группу."
            return result

        # Импортируем здесь чтобы избежать циклического импорта
        from bot.services.captcha import generate_pm_captcha
        captcha_data = await generate_pm_captcha(bot, user_id, chat_id)
        if not captcha_data:
            result["message"] = "⚠️ Произошла ошибка при генерации капчи. Попробуйте отправить запрос в группу снова."
            return result

        result["success"] = True
        result["captcha_data"] = captcha_data
        logging.info(f"Отправлена капча через deep link для пользователя {user_id}, группа {chat_id}")
        return result
    except Exception as e:
        logging.error(f"Ошибка при обработке deep link капчи: {str(e)}")
        result["message"] = "⚠️ Произошла ошибка при обработке запроса. Попробуйте позже."
        return result


async def process_bot_added_to_group(bot: Bot, user_id: int, chat_id: int, chat_title: str) -> bool:
    """
    Обрабатывает добавление бота в группу
    Возвращает True, если пользователь имеет права на добавление
    """
    logging.info(f"Бот добавлен в группу {chat_title} (ID: {chat_id}) от пользователя (User ID: {user_id})")

    # Проверяем, является ли добавивший пользователь администратором бота
    if user_id not in ALLOWED_USERS:
        try:
            await bot.send_message(
                chat_id,
                "Извините, на данный момент бот работает в тестовом режиме. По вопросам можете написать @texas_dev"
            )
            # Можно также добавить выход из группы, если требуется:
            # await bot.leave_chat(chat_id)
            return False
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения в группу {chat_id}: {e}")
            return False
    return True


async def get_support_text() -> str:
    """Возвращает текст поддержки"""
    return SUPPORT_TEXT


async def get_information_text() -> str:
    """Возвращает информационный текст"""
    return INFORMATION_TEXT


async def get_available_groups(user_id: int) -> str:
    """
    Получает список доступных групп для пользователя
    В текущей реализации возвращает эмуляцию
    """
    # Здесь можно добавить логику получения групп из БД
    return "🔗 Вот список групп, где вы админ или участник (эмуляция)."
