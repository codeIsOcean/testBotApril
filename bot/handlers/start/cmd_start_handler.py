# ✅ Обновлён: 04.05.25
from aiogram import Router, types, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ChatMemberUpdated
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.fsm.context import FSMContext
import logging
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем бизнес-логику
from bot.services.start_logic import (
    check_and_create_user,
    process_setup_deeplink,
    process_captcha_deeplink,
    process_bot_added_to_group,
    get_support_text,
    get_information_text,
    get_available_groups,
    get_settings_keyboard
)
from bot.keyboards.main_menu_keyboard import get_main_menu_buttons
# новый импорт после универсального дип линк
from bot.services.start_logic import check_and_create_user, get_available_groups
from bot.keyboards.main_menu_keyboard import get_main_menu_buttons


cmd_start_router = Router()


@cmd_start_router.message(CommandStart(deep_link=True))
async def cmd_start(message: types.Message, command: CommandStart, session: AsyncSession):
    """Обработка команды /start с deep_link"""
    logging.info(f"👋 Пользователь {message.from_user.full_name} (ID: {message.from_user.id}) отправил команду /start.")

    # Проверка пользователя и прав администратора
    is_admin = await check_and_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
        session
    )

    if not is_admin:
        await message.answer("Извините, на данный момент бот работает в тестовом режиме. По вопросам можете написать "
                             "@texas_dev")
        return

    # Обработка deep link на настройку
    if command.args:
        if command.args.startswith("setup_"):
            group_id = command.args.replace("setup_", "")

            # Обрабатываем setup deep link
            result = await process_setup_deeplink(message.bot, message.from_user.id, group_id)

            if not result["success"]:
                await message.answer(result["message"])
                return

            # Отправляем приветственное сообщение с кликабельной ссылкой
            await message.answer(
                result["message"],
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

            # Получаем клавиатуру с настройками
            settings_keyboard = await get_settings_keyboard()
            await message.answer(
                "👇 Нажмите, чтобы открыть меню настроек:",
                reply_markup=settings_keyboard
            )
            return

        # Обработка deep link для капчи
        if command.args.startswith("captcha_"):
            # Обрабатываем captcha deep link
            result = await process_captcha_deeplink(message.bot, message.from_user.id, command.args)

            if not result["success"]:
                await message.answer(result["message"])
                return

            captcha_data = result["captcha_data"]
            # Отправляем капчу пользователю
            await message.answer(
                f"Для вступления в группу {captcha_data['group_name']} решите задачу:\n\n"
                f"<b>{captcha_data['num1']} {captcha_data['operation']} {captcha_data['num2']} = ?</b>\n\n"
                f"Выберите правильный ответ:",
                reply_markup=captcha_data['keyboard'],
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return

    # Обычное приветствие для администраторов
    await message.answer(
        text=f"*{message.from_user.full_name}* 👋 Добро пожаловать! Я бот-модератор. Используйте кнопки ниже для "
             f"управления:",
        reply_markup=get_main_menu_buttons(),
        parse_mode="Markdown"
    )


@cmd_start_router.message(CommandStart())
async def start_without_args(message: types.Message, session: AsyncSession):
    """Обработка простой команды /start без аргументов"""
    logging.info(f"👋 Пользователь {message.from_user.full_name} (ID: {message.from_user.id}) отправил обычный /start.")

    # Проверка пользователя и прав администратора
    is_admin = await check_and_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
        session
    )

    if not is_admin:
        await message.answer(
            "Извините, на данный момент бот работает в тестовом режиме. По вопросам можете написать @texas_dev")
        return

    # Обычное приветствие для администраторов
    await message.answer(
        text=f"*{message.from_user.full_name}* 👋 Добро пожаловать! Я бот-модератор. Используйте кнопки ниже для "
             f"управления:",
        reply_markup=get_main_menu_buttons(),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


@cmd_start_router.callback_query(F.data == "add_group")
async def add_bot_group_callback(call: CallbackQuery):
    """Обработка запроса на добавление бота в группу"""
    # Получаем доступные группы через сервисную функцию
    text = await get_available_groups(call.from_user.id)
    await call.message.answer(text)


@cmd_start_router.callback_query(F.data == "support")
async def support_callback(call: CallbackQuery):
    """Обработка запроса на информацию о поддержке"""
    # Получаем текст поддержки через сервисную функцию
    support_text = await get_support_text()
    await call.message.edit_text(support_text)


@cmd_start_router.callback_query(F.data == "information")
async def information_callback(call: CallbackQuery):
    """Обработка запроса на получение информации о боте"""
    # Получаем информационный текст через сервисную функцию
    info_text = await get_information_text()
    await call.message.edit_text(info_text)


@cmd_start_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=True))
async def bot_chat_member_update(event: ChatMemberUpdated):
    """Обработка события добавления бота в группу"""
    # Бот был добавлен в группу
    if event.new_chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
        # Делегируем обработку бизнес-логике
        await process_bot_added_to_group(
            event.bot,
            event.from_user.id,
            event.chat.id,
            event.chat.title
        )