from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from redis.asyncio import Redis
import logging
from typing import Optional
from bot.states.group_setup_states import SetupStates

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Убедитесь, что соединение с Redis действительно установлено
try:
    redis = Redis(host='localhost', port=6379, db=0, decode_responses=True)
    logger.info("Соединение с Redis успешно установлено")
except Exception as e:
    logger.error(f"Ошибка подключения к Redis: {e}")
    redis = None

group_setup_handler = Router()


async def is_user_admin(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception as e:
        logger.error(f"Admin check error: {e}")
        return False


async def set_user_group_data(user_id: int, group_id: int):
    """Сохраняем данные о группе в Redis"""
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
    """Получаем данные о группе из Redis"""
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
    """Очищаем данные пользователя в Redis"""
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
    """Обработчик нажатия на кнопку 'Настроить бота' в группе"""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    logger.info(f"Кнопка настройки нажата пользователем {user_id} в группе {chat_id}")

    if not await is_user_admin(callback.bot, chat_id, user_id):
        await callback.answer("Только администратор может настроить бота", show_alert=True)
        logger.warning(f"Пользователь {user_id} не является администратором группы {chat_id}")
        return

    me = await callback.bot.get_me()
    # Формируем корректную глубокую ссылку
    setup_link = f"https://t.me/{me.username}?start={chat_id}"
    logger.info(f"Отправляем кнопку настройки пользователю {user_id}, глубокая ссылка: {setup_link}")
    await callback.message.answer(
        "Нажмите кнопку ниже для настройки бота в личных сообщениях:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Настроить бота", url=setup_link)]
        ])
    )
    await callback.answer()

@group_setup_handler.message(CommandStart())
async def handle_start_command(message: Message, state: FSMContext, command: CommandStart):
    """Обработчик команды /start в личных сообщениях"""
    user_id = message.from_user.id
    logger.info(f"👋 Пользователь {message.from_user.full_name} (ID: {user_id}) отправил команду /start.")

    # Если это личная переписка
    if message.chat.type == ChatType.PRIVATE:

        # Проверяем, есть ли сохраненные данные о группе
        group_id = await get_user_group_data(user_id)
        current_state = await state.get_state()

        if current_state == SetupStates.waiting_for_setup and group_id:
            await message.answer(
                f"✏️ Вы уже в процессе настройки группы {group_id}.\n"
                "Используйте доступные команды или /cancel для отмены."
            )
            await show_setup_menu(message)
        else:
            # Если нет активной настройки
            await state.clear()
            await clear_user_data(user_id)
            await message.answer(
                "👋 Привет! Я бот для модерации групп.\n"
                "Чтобы начать настройку:\n"
                "1. Добавьте меня в группу\n"
                "2. Сделайте меня администратором\n"
                "3. Нажмите 'Настроить бота' в группе или используйте команду /setup"
            )


async def show_setup_menu(message: Message):
    """Показывает меню настройки бота"""
    logger.info(f"Показываем меню настройки пользователю {message.from_user.id}")
    await message.answer(
        "🛠 Меню настройки бота\n\n"
        "Доступные команды:\n"
        "👉 /settings - Основные настройки\n"
        "👥 /admins - Управление администраторами\n"
        "🚫 /cancel - Отменить настройку",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Основные настройки", callback_data="settings")],
            [InlineKeyboardButton(text="👥 Управление админами", callback_data="admins")],
            [InlineKeyboardButton(text="🚫 Отменить настройку", callback_data="cancel_setup")]
        ])
    )


@group_setup_handler.message(Command("cancel"))
async def cancel_setup(message: Message, state: FSMContext):
    """Обработчик команды /cancel"""
    user_id = message.from_user.id
    logger.info(f"Команда /cancel от пользователя {user_id}")

    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        await clear_user_data(user_id)
        await message.answer(
            "✅ Настройка отменена. Чтобы начать заново, вернитесь в группу и нажмите 'Настроить бота'.")
    else:
        await message.answer("❌ Нет активного процесса настройки.")


@group_setup_handler.callback_query(F.data == "cancel_setup")
async def cancel_setup_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки отмены настройки"""
    user_id = callback.from_user.id
    logger.info(f"Кнопка отмены нажата пользователем {user_id}")

    await state.clear()
    await clear_user_data(user_id)
    await callback.message.edit_text(
        "✅ Настройка отменена. Чтобы начать заново, вернитесь в группу и нажмите 'Настроить бота'.")
    await callback.answer()


@group_setup_handler.message(Command("setup"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def setup_command_in_group(message: Message):
    """Обработчик команды /setup в группе"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Команда /setup от пользователя {user_id} в группе {chat_id}")

    # Проверяем, является ли пользователь администратором
    if await is_user_admin(message.bot, chat_id, user_id):
        # Создаем глубокую ссылку с ID группы
        # Создаем глубокую ссылку с ID группы
        bot_info = await message.bot.get_me()
        deep_link = f"https://t.me/{bot_info.username}?start={chat_id}"
        # Логируем созданную ссылку для диагностики
        logger.info(f"Создана глубокая ссылка для группы {chat_id}: {deep_link}")

        # Создаем кнопку для перехода в личный чат с ботом
        setup_button = InlineKeyboardButton(text="⚙️ Настроить бота", url=deep_link)
        setup_markup = InlineKeyboardMarkup(inline_keyboard=[[setup_button]])

        logger.info(f"Отправляем кнопку настройки админу {user_id}")
        await message.answer(
            "Для настройки нажмите кнопку ниже и настройте меня в приватном чате.",
            reply_markup=setup_markup
        )
    else:
        logger.warning(f"Пользователь {user_id} не является администратором группы {chat_id}")
        await message.answer("Эта команда доступна только администраторам группы.")


