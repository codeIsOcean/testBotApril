from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy import select, insert, update
from aiogram.exceptions import TelegramBadRequest

from bot.services.redis_conn import redis
from bot.database.session import *
from bot.database.models import (Group, CaptchaSettings, ChatSettings,
                                 UserGroup)
from bot.handlers.captcha.visual_captcha_handler import visual_captcha_handler_router

import logging

logger = logging.getLogger(__name__)

settings_inprivate_handler = Router()


@settings_inprivate_handler.callback_query(F.data == "show_settings")
async def show_settings_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        logger.error(f"❌ Не найден group_id для пользователя {user_id}")
        await callback.message.answer("❌ Не удалось найти привязку к группе. Сначала нажмите 'настроить' в группе.")
        await callback.answer()
        return

    try:
        group_id = int(group_id)
        chat = await callback.bot.get_chat(group_id)

        if chat.username:
            link = f"https://t.me/{chat.username}"
            title = f"[{chat.title}]({link})"
        else:
            title = f"{chat.title} (ID: `{group_id}`)"

    except Exception as e:
        logger.exception(f"💥 Ошибка в show_settings_callback: {e}")
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
            [InlineKeyboardButton(text="Настройки Капчи", callback_data="redirect:captcha_settings")],
            [InlineKeyboardButton(text="Настройки Визуальной Капчи", callback_data="redirect:visual_captcha_settings")],
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
    logger.info(f"🔄 Пользователь {user_id} меняет настройки капчи")

    group_id = await redis.hget(f"user:{user_id}", "group_id")
    if not group_id:
        logger.error("❌ group_id не найден в Redis")
        await callback.answer("❌ Ошибка: группа не найдена", show_alert=True)
        return

    try:
        group_id = int(group_id)
        async with get_session() as session:
            # Логируем текущее состояние
            current_state = await session.execute(
                select(CaptchaSettings.is_enabled).where(CaptchaSettings.group_id == group_id)
            )
            current_state = current_state.scalar_one_or_none()
            logger.debug(f"📌 Текущее состояние капчи: {current_state}")

            new_state = not current_state if current_state is not None else True
            logger.info(f"🔄 Установка нового состояния: {new_state}")

            # Обновляем БД
            if current_state is None:
                await session.execute(
                    insert(CaptchaSettings).values(group_id=group_id, is_enabled=True)
                )
            else:
                await session.execute(
                    update(CaptchaSettings)
                    .where(CaptchaSettings.group_id == group_id)
                    .values(is_enabled=new_state)
                )
            await session.commit()

        # Обновляем Redis
        await redis.hset(f"group:{group_id}", "captcha_enabled", "1" if new_state else "0")
        logger.debug("✅ Состояние капчи сохранено в Redis")

        await callback.answer(f"Капча {'включена' if new_state else 'отключена'}", show_alert=True)
        await captcha_settings_callback(callback)  # Обновляем меню

    except Exception as e:
        logger.exception(f"💥 Ошибка при переключении капчи: {e}")
        await callback.answer("⚠️ Произошла ошибка", show_alert=True)


# # Обработчик для отображения настроек капчи
# @settings_inprivate_handler.callback_query(F.data == "captcha_settings")
async def captcha_settings_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось найти привязку к группе", show_alert=True)
        return

    try:
        group_id = int(group_id)

        # deep link для ручной проверки капчи
        deep_link = await create_start_link(callback.bot, f"captcha_{user_id}_{group_id}", encode=True)

        async with get_session() as session:
            settings_result = await session.execute(
                select(CaptchaSettings).where(CaptchaSettings.group_id == group_id)
            )
            settings = settings_result.scalar_one_or_none()
            is_enabled = settings.is_enabled if settings else False

        # Получаем значение captcha_in_pm из Redis
        captcha_in_pm = await redis.hget(f"group:{group_id}", "captcha_in_pm")
        captcha_in_pm = captcha_in_pm == "1" if captcha_in_pm else False

        text = (
            f"⚙️ *Настройки капчи для группы*\n\n"
            f"*ID группы:* `{group_id}`\n"
            f"*Статус:* {'✅ Включена' if is_enabled else '❌ Отключена'}\n"
            f"*Капча в ЛС:* {'✅ Включена' if captcha_in_pm else '❌ Отключена'}"
        )

        # Используем новую функцию для создания клавиатуры
        keyboard = await get_captcha_settings_keyboard(group_id, is_enabled, captcha_in_pm)

        # Добавляем кнопку проверки капчи
        keyboard.inline_keyboard.insert(1, [
            InlineKeyboardButton(
                text="🧩 Проверить капчу через ЛС",
                url=deep_link
            )
        ])

        try:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer("⚠️ Уже актуально", show_alert=False)
            else:
                raise

    except Exception as e:
        logger.exception(f"💥 Ошибка в captcha_settings_callback: {e}")
        await callback.answer("⚠️ Ошибка при обновлении", show_alert=True)


# Функция для создания клавиатуры настроек капчи
async def get_captcha_settings_keyboard(group_id, captcha_enabled=False, captcha_in_pm=False):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"Капча: {'✅' if captcha_enabled else '❌'}",
                callback_data="toggle_captcha"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Капча в ЛС: {'✅' if captcha_in_pm else '❌'}",
                callback_data="toggle_captcha_pm"  # Используем простой формат
            )
        ],
        [
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="show_settings"
            )
        ]
    ])
    return keyboard


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

    group_id = int(group_id)

    # Проверяем, имеет ли пользователь права на изменение настроек
    async with get_session() as session:
        # Проверяем, является ли пользователь администратором в этой группе
        admin_check = await session.execute(
            select(UserGroup).where(
                (UserGroup.user_id == user_id) & (UserGroup.group_id == group_id)
            )
        )
        admin_record = admin_check.scalar_one_or_none()

        # Также проверяем, не является ли он создателем группы
        group_check = await session.execute(
            select(Group).where(
                (Group.chat_id == group_id) & (Group.creator_user_id == user_id)
            )
        )
        creator_record = group_check.scalar_one_or_none()

        if not admin_record and not creator_record:
            await callback.answer("⚠️ У вас нет прав на изменение настроек этой группы", show_alert=True)
            return

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

    # Проверяем права пользователя
    async with get_session() as session:
        # Проверяем, является ли пользователь администратором или создателем
        admin_check = await session.execute(
            select(UserGroup).where(
                (UserGroup.user_id == user_id) & (UserGroup.group_id == group_id)
            )
        )
        admin_record = admin_check.scalar_one_or_none()

        group_check = await session.execute(
            select(Group).where(
                (Group.chat_id == group_id) & (Group.creator_user_id == user_id)
            )
        )
        creator_record = group_check.scalar_one_or_none()

        if not admin_record and not creator_record:
            await callback.answer("⚠️ У вас нет прав на изменение настроек этой группы", show_alert=True)
            return

        # 🛠 Безопасно извлекаем значение минут
        try:
            parts = callback.data.split('_')
            minutes = int(parts[-1])
        except (IndexError, ValueError):
            await callback.answer("❌ Ошибка: неверный формат времени", show_alert=True)
            return

        # 💾 Сохраняем в БД
        result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == group_id))
        settings = result.scalar_one_or_none()

        if settings:
            await session.execute(
                update(ChatSettings).where(ChatSettings.chat_id == group_id).values(
                    photo_filter_mute_minutes=minutes
                )
            )
        else:
            # Создаем новую запись с дефолтными значениями
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=group_id,
                    photo_filter_mute_minutes=minutes,
                    enable_photo_filter=True,  # По умолчанию включаем фильтр
                    admins_bypass_photo_filter=True  # По умолчанию админы могут обходить фильтр
                )
            )
        await session.commit()

        # Также обновляем значения в Redis для быстрого доступа
        await redis.hset(f"group:{group_id}", "photo_filter_mute_minutes", str(minutes))
        logger.info(f"✅ Установлено время мута {minutes} минут для группы {group_id}")

    # ⏱ Уведомление
    time_text = "навсегда" if minutes == 0 else (
        f"{minutes} минут" if minutes < 60 else
        f"{minutes // 60} час(ов)" if minutes < 1440 else
        f"{minutes // 1440} день(дней)"
    )

    await callback.answer(f"Время мута установлено: {time_text}", show_alert=True)
    await photo_filter_settings_callback(callback)


@settings_inprivate_handler.callback_query(
    lambda c: c.data.startswith("redirect:"))
async def redirect_callback(call: CallbackQuery):
    # Проверяем, начинается ли callback с "redirect:"
    original_callback = call.data.split(":", 1)[1]

    # Логируем данные для отладки
    logger.debug(f"🔄 Перенаправление callback: {original_callback} от пользователя {call.from_user.id}")

    if original_callback == "captcha_settings":
        await captcha_settings_callback(call)

    elif original_callback == "visual_captcha_settings":
        from bot.handlers.captcha.visual_captcha_handler import visual_captcha_settings
        await visual_captcha_settings(call)

    elif original_callback == "photo_filter_settings":
        await photo_filter_settings_callback(call)

    elif original_callback == "new_member_requested_handler_settings":
        from bot.handlers.moderation.new_member_requested_mute import new_member_requested_handler_settings
        await new_member_requested_handler_settings(call)
    else:
        logger.error(f"❌ Неизвестный callback для перенаправления: {original_callback}")
        await call.answer("❌ Неизвестная команда", show_alert=True)


@settings_inprivate_handler.callback_query(F.data == "toggle_captcha_pm")
async def toggle_captcha_pm(callback: CallbackQuery):
    user_id = callback.from_user.id
    logger.info(f"🔄 Пользователь {user_id} меняет настройки капчи в ЛС")

    group_id = await redis.hget(f"user:{user_id}", "group_id")
    if not group_id:
        await callback.answer("❌ Не удалось найти привязку к группе", show_alert=True)
        return

    group_key = f"group:{group_id}"
    current = await redis.hget(group_key, "captcha_in_pm")
    current = "0" if current is None else current

    new_value = "0" if current == "1" else "1"
    await redis.hset(group_key, "captcha_in_pm", new_value)
    logger.info(f"🔄 Установка нового состояния: {new_value == '1'}")

    # Получаем текущие настройки для обновления клавиатуры
    captcha_enabled = await redis.hget(group_key, "captcha_enabled")
    captcha_enabled = captcha_enabled == "1"

    # Обновляем интерфейс
    keyboard = await get_captcha_settings_keyboard(group_id, captcha_enabled, new_value == "1")

    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer(f"Капча {'в ЛС включена ✅' if new_value == '1' else 'в ЛС отключена ❌'}")


@settings_inprivate_handler.callback_query(F.data == "unknown")
async def fallback_callback_handler(callback: CallbackQuery):
    print(f"❌ Неизвестный callback: {callback.data}")
    await callback.answer("⚠️ Неизвестная команда", show_alert=True)
