from aiogram import Router, types, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
import logging
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select # для того чтобы опят не добавлять тех же юзеров в бд

from bot.config import ADMIN_IDS
from bot.models import User
from keyboards.main_menu_keyboard import get_main_menu_buttons
from texts import messages
from keyboards import main_menu_keyboard
from texts.messages import SUPPORT_TEXT, INFORMATION_TEXT

cmd_start_router = Router()
ALLOWED_USERS = ADMIN_IDS


@cmd_start_router.message(Command("start"))
async def cmd_start(message: types.Message, session: AsyncSession):
    logging.info(f"👋 Пользователь {message.from_user.full_name} (ID: {message.from_user.id}) отправил команду /start.")
    # проверка есть ли пользователь
    stmt = select(User).where(User.user_id == message.from_user.id)
    result = await session.execute(stmt)
    existing_user = result.scalar_one_or_none()
    # если нет в бд - добавить
    if not existing_user:
        user = User(
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )
        session.add(user)
        await session.commit()

    # прописываем чтобы после нажатия бот отвечал
    await message.answer(
        text=f"*{message.from_user.full_name}* 👋 Добро пожаловать! Я бот-модератор. Используйте кнопки ниже для "
             f"управления:",
        reply_markup=get_main_menu_buttons()
    )


# хэндлеры вызова главного меню

# хэндлер показа всех групп в которых состоит пользователь или является админом
@cmd_start_router.callback_query(F.data == "add_group")
async def add_bot_group_callback(call: CallbackQuery):
    text = "\ud83d\udd17 Вот список групп, где вы админ или участник (эмуляция)."


# хэндлер для обработки клавиши support в main menu
@cmd_start_router.callback_query(F.data == "support")
async def support_callback(call: CallbackQuery):
    await call.message.edit_text(SUPPORT_TEXT)


# хэндлер обработки клавиши information
@cmd_start_router.callback_query(F.data == "information")
async def information_callback(call: CallbackQuery):
    await call.message.edit_text(INFORMATION_TEXT)


# хэндлер проверки добавления бота в группу, что бот стал администратором
@cmd_start_router.my_chat_member()
async def check_bot_added_to_group(event: ChatMemberUpdated):
    # проверка, что бот стал админом
    if event.new_chat_member.status in ("administrator", "member"):
        user = event.from_user
        chat = event.chat
        logging.info(f"Бот добавлен в группу {chat.title} (ID: {chat.id} от {user.full_name} (User ID: {user.id})")
