from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, insert, update, delete

from bot.handlers.new_member_requested_mute import new_member_requested_handler
from bot.services.redis_conn import redis
from bot.database.session import *
from bot.database.models import (User, Group, CaptchaSettings, CaptchaAnswer, CaptchaMessageId, ChatSettings,
                                 UserRestriction, UserGroup)
from bot.handlers.photo_del_handler import check_image_with_yolov5, check_image_with_opennsfw2

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
            [InlineKeyboardButton(text="Настройки Капчи", callback_data="captcha_settings")],
            [InlineKeyboardButton(text="Фильтр Фотографий", callback_data="photo_filter_settings")]
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



# Обработчик для отображения настроек капчи
@settings_inprivate_handler.callback_query(F.data == "captcha_settings")
async def captcha_settings_callback(callback: CallbackQuery):
    """Отображает меню настроек капчи для выбранной группы"""
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось найти привязку к группе")
        return

    group_id = int(group_id)

    # Получаем текущее состояние капчи
    async with get_session() as session:
        query = select(CaptchaSettings).where(CaptchaSettings.group_id == group_id)
        result = await session.execute(query)
        settings = result.scalar_one_or_none()

        is_enabled = settings.is_enabled if settings else False

    # Формируем текст статуса
    status = "✅ Включена" if is_enabled else "❌ Отключена"

    # Создаем сообщение с настройками и клавиатурой
    await callback.message.edit_text(
        f"⚙️ Настройки капчи для новых участников\n\n"
        f"Текущий статус: {status}\n\n"
        f"Капча помогает защитить вашу группу от спам-ботов, требуя от новых участников "
        f"решить простую математическую задачу перед тем, как получить доступ к группе.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Включить капчу" if not is_enabled else "❌ Отключить капчу",
                callback_data="toggle_captcha"
            )],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_settings")]
        ]),
        parse_mode="Markdown"
    )

    await callback.answer()

# УПРАВЛЕНИЕ НАСТРОЙКАМИ ФИЛЬТРА ФОТОГРАФИЙ

# Обработчик включения/выключения фильтра фото в настройках
@settings_inprivate_handler.callback_query(F.data == "toggle_photo_filter")
async def toggle_photo_filter(callback: CallbackQuery):
    """Включение/выключение фильтра фото"""
    user_id = callback.from_user.id

    # Получаем привязанную группу из Redis
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось найти привязку к группе", show_alert=True)
        return

    group_id = int(group_id)

    # Получаем текущие настройки и инвертируем состояние фильтра
    async with get_session() as session:
        query = select(ChatSettings).where(ChatSettings.chat_id == group_id)
        result = await session.execute(query)
        settings = result.scalar_one_or_none()

        new_state = not (settings.enable_photo_filter if settings else False)

        # Обновляем настройки в БД
        if settings:
            await session.execute(
                update(ChatSettings).where(
                    ChatSettings.chat_id == group_id
                ).values(
                    enable_photo_filter=new_state
                )
            )
        else:
            # Если настройки не существуют, создаем их
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=group_id,
                    enable_photo_filter=new_state
                )
            )

        await session.commit()

    # Показываем уведомление о смене настройки
    await callback.answer(
        f"Фильтр фото {'включен' if new_state else 'выключен'} для группы",
        show_alert=True
    )

    # Обновляем меню настроек
    await photo_filter_settings_callback(callback)


# Отображение настроек фильтра фото
@settings_inprivate_handler.callback_query(F.data == "photo_filter_settings")
async def photo_filter_settings_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось найти привязку к группе")
        await callback.answer()
        return

    group_id = int(group_id)

    # Получаем текущие настройки фильтра
    async with get_session() as session:
        query = select(ChatSettings).where(ChatSettings.chat_id == group_id)
        result = await session.execute(query)
        settings = result.scalar_one_or_none()

        filter_enabled = settings.enable_photo_filter if settings else False
        mute_minutes = settings.photo_filter_mute_minutes if settings else 60
        admins_bypass = settings.admins_bypass_photo_filter if settings else False

    # Преобразуем минуты в удобочитаемый формат
    time_text = f"{mute_minutes} минут" if mute_minutes < 60 else f"{mute_minutes // 60} час(ов)" if mute_minutes < 1440 else f"{mute_minutes // 1440} день(дней)"

    status = "✅ Включен" if filter_enabled else "❌ Отключен"
    admins_status = "✅ Да" if admins_bypass else "❌ Нет"

    await callback.message.edit_text(
        f"⚙️ Настройки фильтра фотографий\n\n"
        f"Статус фильтра: {status}\n"
        f"Время мута: {time_text}\n"
        f"Администраторы обходят фильтр: {admins_status}\n\n"
        f"Фильтр автоматически проверяет фотографии на наличие запрещенного контента "
        f"и мутит пользователя, отправившего такое фото.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Включить фильтр" if not filter_enabled else "❌ Отключить фильтр",
                callback_data="toggle_photo_filter"
            )],
            [InlineKeyboardButton(text="⏱ Изменить время мута", callback_data="set_photo_filter_mute_time")],
            [InlineKeyboardButton(text="👮 Настройки для администраторов", callback_data="toggle_admins_bypass")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_settings")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()


# Обработчик для переключения настройки обхода фильтра администраторами
@settings_inprivate_handler.callback_query(F.data == "toggle_admins_bypass")
async def toggle_admins_bypass(callback: CallbackQuery):
    """Включение/выключение обхода фильтра администраторами"""
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось найти привязку к группе", show_alert=True)
        return

    group_id = int(group_id)

    # Инвертируем настройку обхода фильтра администраторами
    async with get_session() as session:
        query = select(ChatSettings).where(ChatSettings.chat_id == group_id)
        result = await session.execute(query)
        settings = result.scalar_one_or_none()

        new_state = not (settings.admins_bypass_photo_filter if settings else False)

        if settings:
            await session.execute(
                update(ChatSettings).where(
                    ChatSettings.chat_id == group_id
                ).values(
                    admins_bypass_photo_filter=new_state
                )
            )
        else:
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=group_id,
                    admins_bypass_photo_filter=new_state
                )
            )

        await session.commit()

    await callback.answer(
        f"Обход фильтра администраторами {'включен' if new_state else 'отключен'}",
        show_alert=True
    )

    # Обновляем меню настроек
    await photo_filter_settings_callback(callback)


# Обработчик для изменения времени мута за запрещенные фото
@settings_inprivate_handler.callback_query(F.data == "set_photo_filter_mute_time")
async def set_photo_filter_mute_time(callback: CallbackQuery):
    """Изменение времени мута за запрещенные фото"""
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось найти привязку к группе", show_alert=True)
        return

    # Создаем клавиатуру с временными интервалами
    # Создаем клавиатуру с временными интервалами
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="15 минут", callback_data="set_photo_mute_time_15"),
            InlineKeyboardButton(text="30 минут", callback_data="set_photo_mute_time_30")
        ],
        [
            InlineKeyboardButton(text="1 час", callback_data="set_photo_mute_time_60"),
            InlineKeyboardButton(text="3 часа", callback_data="set_photo_mute_time_180")
        ],
        [
            InlineKeyboardButton(text="1 день", callback_data="set_photo_mute_time_1440"),
            InlineKeyboardButton(text="Навсегда", callback_data="set_photo_mute_time_0")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="photo_filter_settings")
        ]
    ])

    # Обновляем сообщение с новой клавиатурой
    await callback.message.edit_text(
        "⏱ Выберите время мута за отправку запрещенных фотографий:",
        reply_markup=keyboard
    )

    await callback.answer()


@settings_inprivate_handler.callback_query(lambda c: c.data.startswith("set_photo_mute_time_"))
async def process_photo_mute_time(callback: CallbackQuery):
    """Установка времени мута"""
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось найти привязку к группе", show_alert=True)
        return

    group_id = int(group_id)

    # 🛠 Безопасно извлекаем значение минут
    try:
        parts = callback.data.split('_')
        minutes = int(parts[-1])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка: неверный формат времени", show_alert=True)
        return

    # 💾 Сохраняем в БД
    async with get_session() as session:
        result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == group_id))
        settings = result.scalar_one_or_none()

        if settings:
            await session.execute(
                update(ChatSettings).where(ChatSettings.chat_id == group_id).values(
                    photo_filter_mute_minutes=minutes
                )
            )
        else:
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=group_id,
                    photo_filter_mute_minutes=minutes
                )
            )
        await session.commit()

    # ⏱ Уведомление
    time_text = "навсегда" if minutes == 0 else (
        f"{minutes} минут" if minutes < 60 else
        f"{minutes // 60} час(ов)" if minutes < 1440 else
        f"{minutes // 1440} день(дней)"
    )

    await callback.answer(f"Время мута установлено: {time_text}", show_alert=True)
    await photo_filter_settings_callback(callback)


