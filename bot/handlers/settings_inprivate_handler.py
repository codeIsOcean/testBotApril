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
        "- 🤖 Настроить капчу для новых участников\n"
        "- 🔚 Выйти из режима настройки (/cancel)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Настройки Мута Новых Пользователей",
                                  callback_data="new_member_requested_handler_settings")],
            [InlineKeyboardButton(text="Настройки Капчи", callback_data="captcha_settings")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()


@settings_inprivate_handler.callback_query(F.data == "captcha_settings")
async def captcha_settings_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе")
        await callback.answer()
        return

    # Проверяем текущее состояние настройки капчи
    captcha_enabled = await redis.hget(f"group:{group_id}", "captcha_enabled") or "0"
    status = "✅ Включена" if captcha_enabled == "1" else "❌ Отключена"

    await callback.message.answer(
        f"⚙️ Настройки математической капчи\n\n"
        f"Текущий статус: {status}\n\n"
        f"При включении этой функции новые пользователи получат математическую капчу "
        f"при запросе на вход в группу. Только те, кто правильно решит задачу, "
        f"смогут присоединиться к группе без мута.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Включить капчу" if captcha_enabled != "1" else "❌ Отключить капчу",
                callback_data="toggle_captcha"
            )],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_settings")]
        ])
    )
    await callback.answer()


@settings_inprivate_handler.callback_query(F.data == "toggle_captcha")
async def toggle_captcha_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе")
        await callback.answer()
        return

    # Инвертируем текущее состояние
    current_state = await redis.hget(f"group:{group_id}", "captcha_enabled") or "0"
    new_state = "0" if current_state == "1" else "1"

    # Сохраняем новое состояние
    await redis.hset(f"group:{group_id}", "captcha_enabled", new_state)

    status = "включена ✅" if new_state == "1" else "отключена ❌"
    await callback.message.answer(f"✅ Капча для новых пользователей {status}")

    # Возвращаемся к настройкам капчи
    await captcha_settings_callback(callback)
