# ✅ Обновлён: 02.05.25
from aiogram import Router, types, F
from aiogram.types import CallbackQuery, ChatMemberUpdated
import logging
from aiogram.filters import Command, CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from aiogram.utils.deep_linking import decode_payload
from bot.services.redis_conn import redis


from bot.config import ADMIN_IDS
from bot.database.models import User
from keyboards.main_menu_keyboard import get_main_menu_buttons
from texts.messages import SUPPORT_TEXT, INFORMATION_TEXT

cmd_start_router = Router()
ALLOWED_USERS = ADMIN_IDS


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

            await message.answer(
                f"🔧 Вы начали настройку группы с ID: {group_id}\n"
                "Используйте доступные команды или /cancel для отмены."
            )
            return

    # Обычное приветствие
    await message.answer(
        text=f"*{message.from_user.full_name}* 👋 Добро пожаловать! Я бот-модератор. Используйте кнопки ниже для "
             f"управления:",
        reply_markup=get_main_menu_buttons(),
        parse_mode="Markdown"
    )

# обработка команды /start
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

    await message.answer(
        text=f"*{message.from_user.full_name}* 👋 Добро пожаловать! Я бот-модератор. Используйте кнопки ниже для "
             f"управления:",
        reply_markup=get_main_menu_buttons(),
        parse_mode="Markdown"
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


@cmd_start_router.my_chat_member()
async def check_bot_added_to_group(event: ChatMemberUpdated):
    if event.new_chat_member.status in ("administrator", "member"):
        user = event.from_user
        chat = event.chat
        logging.info(f"Бот добавлен в группу {chat.title} (ID: {chat.id}) от {user.full_name} (User ID: {user.id})")
