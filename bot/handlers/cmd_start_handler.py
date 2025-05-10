# ✅ Обновлён: 02.05.25
from aiogram import Router, types, F
from aiogram.types import CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
# Добавляем хендлер для обработки добавления бота в группу
from aiogram.types import ChatMemberUpdated
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter
from aiogram.enums.chat_member_status import ChatMemberStatus
import logging
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.services.redis_conn import redis

from bot.config import ADMIN_IDS as ALLOWED_USERS
from bot.database.models import User
from bot.keyboards.main_menu_keyboard import get_main_menu_buttons
from bot.texts.messages import SUPPORT_TEXT, INFORMATION_TEXT

cmd_start_router = Router()


@cmd_start_router.message(CommandStart(deep_link=True))
async def cmd_start(message: types.Message, command: CommandStart, session: AsyncSession):
    logging.info(f"👋 Пользователь {message.from_user.full_name} (ID: {message.from_user.id}) отправил команду /start.")

    # Проверка, есть ли пользователь в базе
    stmt = select(User).where(User.user_id == message.from_user.id)
    result = await session.execute(stmt)
    existing_user = result.scalar_one_or_none()

    if not existing_user:
        user = User(
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )
        session.add(user)
        await session.commit()

    # Проверка, является ли пользователь администратором
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("Извините, на данный момент бот работает в тестовом режиме. По вопросам можете написать "
                             "@texas_dev")
        return

    # Обработка deep link на настройку
    if command.args:
        if command.args.startswith("setup_"):
            group_id = command.args.replace("setup_", "")

            try:
                member = await message.bot.get_chat_member(int(group_id), message.from_user.id)
                if member.status not in ("administrator", "creator"):
                    await message.answer("❌ Вы не являетесь администратором этой группы и не можете настраивать бота.")
                    return
            except Exception as e:
                logging.warning(f"Ошибка при проверке админства: {e}")
                await message.answer("⚠️ Не удалось проверить ваши права в группе. Убедитесь, что бот добавлен в неё.")
                return

            await redis.hset(f"user:{message.from_user.id}", "group_id", group_id)

            # получаем название группы и отображение пользователю
            try:
                chat = await message.bot.get_chat(int(group_id))
                if chat.username:
                    link = f"https://t.me/{chat.username}"
                    title = f"[{chat.title}]({link})"
                else:
                    title = f"{chat.title} (ID: `{group_id}`)"
            except Exception:
                title = f"ID: `{group_id}`"

            # отправляем приветственное сообщение с кликабельной ссылкой
            await message.answer(
                f"🔧 Вы начали настройку группы: {title}\n"
                "Используйте доступные команды или /cancel для отмены.",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            await message.answer(
                "👇 Нажмите, чтобы открыть меню настроек:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Открыть меню", callback_data="show_settings")]
                ])
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
    logging.info(f"👋 Пользователь {message.from_user.full_name} (ID: {message.from_user.id}) отправил обычный /start.")

    # Проверка пользователя в БД
    stmt = select(User).where(User.user_id == message.from_user.id)
    result = await session.execute(stmt)
    existing_user = result.scalar_one_or_none()
    if not existing_user:
        user = User(
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )
        session.add(user)
        await session.commit()

    # Проверка, является ли пользователь администратором
    if message.from_user.id not in ALLOWED_USERS:
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
    text = "🔗 Вот список групп, где вы админ или участник (эмуляция)."
    await call.message.answer(text)


@cmd_start_router.callback_query(F.data == "support")
async def support_callback(call: CallbackQuery):
    await call.message.edit_text(SUPPORT_TEXT)


@cmd_start_router.callback_query(F.data == "information")
async def information_callback(call: CallbackQuery):
    await call.message.edit_text(INFORMATION_TEXT)


@cmd_start_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=True))
async def bot_chat_member_update(event: ChatMemberUpdated):
    # Бот был добавлен в группу
    if event.new_chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
        user = event.from_user
        chat = event.chat
        logging.info(f"Бот добавлен в группу {chat.title} (ID: {chat.id}) от {user.full_name} (User ID: {user.id})")

        # Проверяем, является ли добавивший пользователь администратором бота
        if user.id not in ALLOWED_USERS:
            try:
                await event.bot.send_message(
                    chat.id,
                    "Извините, на данный момент бот работает в тестовом режиме. По вопросам можете написать @texas_dev"
                )
                # Можно также добавить выход из группы, если требуется:
                # await event.bot.leave_chat(chat.id)
            except Exception as e:
                logging.error(f"Ошибка при отправке сообщения в группу {chat.id}: {e}")
