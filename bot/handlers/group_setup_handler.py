# ✅ Обновлён: 02.05.25
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
import logging
from typing import Optional
from aiogram.utils.deep_linking import create_start_link
from bot.services.redis_conn import redis


from bot.states.group_setup_states import SetupStates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

group_setup_handler = Router()


async def is_user_admin(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception as e:
        logger.error(f"Admin check error: {e}")
        return False


async def set_user_group_data(user_id: int, group_id: int):
    if redis is None:
        logger.error("Redis недоступен, невозможно сохранить данные пользователя")
        return False
    try:
        await redis.hset(f"user:{user_id}", "group_id", str(group_id))
        logger.info(f"Сохранены данные для пользователя {user_id}: группа {group_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в Redis: {e}")
        return False


async def get_user_group_data(user_id: int) -> Optional[int]:
    if redis is None:
        logger.error("Redis недоступен, невозможно получить данные пользователя")
        return None
    try:
        group_id = await redis.hget(f"user:{user_id}", "group_id")
        logger.debug(f"Получены данные из Redis для пользователя {user_id}: группа {group_id}")
        if group_id:
            return int(group_id)
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении данных из Redis: {e}")
        return None


async def clear_user_data(user_id: int):
    if redis is None:
        logger.error("Redis недоступен, невозможно очистить данные пользователя")
        return False
    try:
        await redis.delete(f"user:{user_id}")
        logger.info(f"Данные пользователя {user_id} удалены из Redis")
        return True
    except Exception as e:
        logger.error(f"Ошибка при удалении данных из Redis: {e}")
        return False


@group_setup_handler.callback_query(F.data == "setup_bot")
async def setup_bot_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    logger.info(f"Кнопка настройки нажата пользователем {user_id} в группе {chat_id}")

    if not await is_user_admin(callback.bot, chat_id, user_id):
        await callback.answer("Только администратор может настроить бота", show_alert=True)
        logger.warning(f"Пользователь {user_id} не является администратором группы {chat_id}")
        return

    link = await create_start_link(callback.bot, payload=f"setup_{chat_id}")
    logger.info(f"Отправляем кнопку настройки пользователю {user_id}, глубокая ссылка: {link}")
    await callback.message.answer(
        "Нажмите кнопку ниже для настройки бота в личных сообщениях:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Настроить бота", url=link)]
        ])
    )
    await callback.answer()


@group_setup_handler.message(Command("setup"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def setup_command_in_group(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Команда /setup от пользователя {user_id} в группе {chat_id}")

    if await is_user_admin(message.bot, chat_id, user_id):
        link = await create_start_link(message.bot, payload=f"setup_{chat_id}")
        logger.info(f"Создана глубокая ссылка для группы {chat_id}: {link}")

        setup_button = InlineKeyboardButton(text="⚙️ Настроить бота", url=link)
        setup_markup = InlineKeyboardMarkup(inline_keyboard=[[setup_button]])

        logger.info(f"Отправляем кнопку настройки админу {user_id}")
        await message.answer(
            "Для настройки нажмите кнопку ниже и настройте меня в приватном чате.",
            reply_markup=setup_markup
        )
    else:
        logger.warning(f"Пользователь {user_id} не является администратором группы {chat_id}")
        await message.answer("Эта команда доступна только администраторам группы.")
