from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, insert, update, delete

from bot.handlers.new_member_requested_mute import new_member_requested_handler
from bot.services.redis_conn import redis
from bot.database.session import *
from bot.database.models import User, Group, CaptchaSettings, CaptchaAnswer, CaptchaMessageId
from bot.database.models import UserGroup


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
        parse_mode="Markdown",
        disable_web_page_preview=True
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

    await callback.message.edit_text(
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
        ]),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await callback.answer()


# В обработчике toggle_captcha_callback замените
@settings_inprivate_handler.callback_query(F.data == "toggle_captcha")
async def toggle_captcha_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Получаем привязанную группу из Redis
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе")
        await callback.answer()
        return

    group_id = int(group_id)

    # Инвертируем состояние капчи в БД
    async with get_session() as session:
        query = select(CaptchaSettings.is_enabled).where(CaptchaSettings.group_id == group_id)
        result = await session.execute(query)
        current_state = result.scalar_one_or_none()

        if current_state is None:
            # если записи нет, создаём включённую капчу
            await session.execute(
                insert(CaptchaSettings).values(group_id=group_id, is_enabled=True)
            )
            new_state = True
        else:
            new_state = not current_state
            await session.execute(
                update(CaptchaSettings).where(CaptchaSettings.group_id == group_id).values(is_enabled=new_state)
            )

        await session.commit()

    # ✅ Обновляем Redis
    await redis.hset(f"group:{group_id}", "captcha_enabled", "1" if new_state else "0")

    # Отправляем уведомление
    status_text = "включена ✅" if new_state else "отключена ❌"
    await callback.answer(f"Капча для новых пользователей {status_text}", show_alert=True)

    # Возвращаем обновлённое меню капчи
    await captcha_settings_callback(callback)


