from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.handlers.new_member_requested_mute import new_member_requested_handler
from bot.services.redis_conn import redis
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

settings_inprivate_handler = Router()


@settings_inprivate_handler.callback_query(F.data == "show_settings")
async def show_settings_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе. Сначала нажмите 'настроить' в группе.")
        await callback.answer()
        return

    try:
        chat = await callback.bot.get_chat(int(group_id))
        if chat.username:
            link = f"https://t.me/{chat.username}"
            title = f"[{chat.title}]({link})"
        else:
            title = f"{chat.title} (ID: `{group_id}`)"
    except Exception:
        title = f"ID: `{group_id}`"

    await callback.message.answer(
        f"🛠 Настройки для группы: {title}\n\n"
        "Здесь вы можете:\n"
        "- 🚫 Забанить пользователя\n"
        "- 🔚 Выйти из режима настройки (/cancel)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Настройки Мута Новых Пользователей",
                                  callback_data="new_member_requested_handler_settings")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()
