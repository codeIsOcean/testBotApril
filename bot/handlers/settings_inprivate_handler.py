from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from bot.services.redis_conn import redis

# чисто логика настроек (в личке с ботом)
settings_inprivate_handler = Router()


@settings_inprivate_handler.message(Command("settings"))
async def handle_settings_command(message: Message):
    user_id = message.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await message.answer("❌ Вы не начали настройку группы. Сначала нажмите кнопку 'настроить' в группе.")
        return

    await message.answer(
        f"🛠 Настройки для группы ID: `{group_id}`\n\n"
        "Здесь вы можете:\n"
        "- ⚙️ Изменить параметры\n"
        "- 👮 Управлять администраторами\n"
        "- 🚫 Забанить пользователя\n"
        "- 🔚 Выйти из режима настройки (/cancel)",
        parse_mode="Markdown"
    )


@settings_inprivate_handler.message(Command("debug"))
async def debug_redis(message: Message):
    from redis.asyncio import Redis
    redis = Redis(host='localhost', port=6379, db=0, decode_responses=True)

    user_id = message.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")
    await message.answer(f"🧪 Redis: `group_id = {group_id}`", parse_mode="Markdown")
