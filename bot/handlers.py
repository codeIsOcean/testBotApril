from aiogram import Router, types
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import User

router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message, session: AsyncSession):
    user = User(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    session.add(user)
    await session.commit()

    await message.answer(f"Привет, {message.from_user.full_name}! Твои данные сохранены в БД.")