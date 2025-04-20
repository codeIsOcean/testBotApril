from aiogram import Router, types
import logging
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import User

cmd_start_router = Router()


@cmd_start_router.message(Command("start"))
async def cmd_start(message: types.Message, session: AsyncSession):
    logging.info(f"👋 Пользователь {message.from_user.full_name} (ID: {message.from_user.id}) отправил команду /start.")
    user = User(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    session.add(user)
    await session.commit()

    await message.answer(f"Привет, {message.from_user.full_name}! Твои данные сохранены в БД.")