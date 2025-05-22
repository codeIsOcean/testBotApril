from aiogram import Bot, F
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, ChatMemberUpdated
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert, or_
import logging

from bot.database.models import Group, ChatSettings, UserGroup, User, CaptchaSettings
from bot.handlers.group_management.settings_inprivate_handler import redis
from bot.handlers.group_management.settings_inprivate_handler import photo_filter_settings_callback
from bot.handlers.group_management.settings_inprivate_handler import captcha_settings_callback
from bot.handlers.captcha.visual_captcha_handler import visual_captcha_handler_router
from bot.handlers.captcha.visual_captcha_handler import visual_captcha_settings
from bot.handlers.moderation.new_member_requested_mute import new_member_requested_handler_settings

# файл отвечает за настройки группы при нажатии /settings админами

logger = logging.getLogger(__name__)

group_settings_handler = Router()


# Функции для работы с настройками капчи (синхронизация Redis и БД)
async def get_captcha_settings(session: AsyncSession, group_id: int) -> tuple[bool, bool]:
    """
    Получает настройки капчи из Redis или БД.
    Возвращает (captcha_enabled, captcha_in_pm)
    """
    # Сначала пробуем получить из Redis (быстрый доступ)
    try:
        if redis:
            captcha_enabled = await redis.hget(f"group:{group_id}", "captcha_enabled")
            captcha_in_pm = await redis.hget(f"group:{group_id}", "captcha_in_pm")

            if captcha_enabled is not None and captcha_in_pm is not None:
                return captcha_enabled == "1", captcha_in_pm == "1"
    except Exception as e:
        logger.error(f"Ошибка при получении настроек капчи из Redis: {e}")

    # Если не удалось получить из Redis, получаем из БД
    try:
        result = await session.execute(
            select(CaptchaSettings).where(CaptchaSettings.group_id == group_id)
        )
        settings = result.scalar_one_or_none()

        if settings:
            # Обновляем Redis для будущих быстрых запросов
            if redis:
                await redis.hset(f"group:{group_id}", "captcha_enabled", "1" if settings.is_enabled else "0")
                # Поскольку в БД нет captcha_in_pm, используем значение по умолчанию
                default_in_pm = "0"  # можно изменить на ваше значение по умолчанию
                await redis.hset(f"group:{group_id}", "captcha_in_pm", default_in_pm)

            return settings.is_enabled, False  # False для captcha_in_pm, так как нет в модели

        # Если настроек нет в БД, создаем их с дефолтными значениями
        settings = CaptchaSettings(
            group_id=group_id,
            is_enabled=False
        )
        session.add(settings)
        await session.commit()

        # Обновляем Redis
        if redis:
            await redis.hset(f"group:{group_id}", "captcha_enabled", "0")
            await redis.hset(f"group:{group_id}", "captcha_in_pm", "0")

        return False, False
    except Exception as e:
        logger.error(f"Ошибка при получении настроек капчи из БД: {e}")
        return False, False


async def update_captcha_settings(session: AsyncSession, group_id: int,
                                  setting_key: str, new_value: str):
    """
    Обновляет настройки капчи в Redis и БД
    setting_key: 'captcha_enabled' или 'captcha_in_pm'
    new_value: '0' или '1'
    """
    try:
        # Обновляем Redis для быстрого доступа
        if redis:
            await redis.hset(f"group:{group_id}", setting_key, new_value)

        # Обновляем БД для надежного хранения
        if setting_key == "captcha_enabled":
            # Проверяем существование записи
            result = await session.execute(
                select(CaptchaSettings).where(CaptchaSettings.group_id == group_id)
            )
            settings = result.scalar_one_or_none()

            is_enabled = new_value == "1"

            if settings:
                # Обновляем существующую запись
                await session.execute(
                    update(CaptchaSettings)
                    .where(CaptchaSettings.group_id == group_id)
                    .values(is_enabled=is_enabled)
                )
            else:
                # Создаем новую запись
                session.add(CaptchaSettings(
                    group_id=group_id,
                    is_enabled=is_enabled
                ))

            await session.commit()
            logger.info(f"Настройка капчи (enabled={is_enabled}) сохранена в БД для группы {group_id}")

        # Для captcha_in_pm можно добавить поле в CaptchaSettings, если оно необходимо
        # Это требует изменения модели данных
    except Exception as e:
        logger.error(f"Ошибка при обновлении настроек капчи: {e}")
        await session.rollback()


async def is_user_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Простая проверка на администратора через Telegram API"""
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ("administrator", "creator")
    except Exception as e:
        logger.warning(f"Не удалось проверить права администратора через API: {e}")
        return False


async def is_user_group_admin(bot: Bot, user_id: int, chat_id: int, session: AsyncSession) -> tuple[bool, Group | None]:
    """Проверяет, является ли пользователь администратором группы"""
    logger.info(f"🔍 Проверка админских прав для пользователя {user_id} в группе {chat_id}")

    # Проверяем, является ли пользователь создателем группы
    creator_result = await session.execute(
        select(Group).where(Group.chat_id == chat_id, Group.creator_user_id == user_id)
    )
    group = creator_result.scalar_one_or_none()

    if group:
        logger.info(f"✅ Пользователь {user_id} является создателем группы {chat_id}")
        return True, group

    # Проверяем, есть ли пользователь в таблице UserGroup
    admin_result = await session.execute(
        select(UserGroup).join(Group, Group.chat_id == UserGroup.group_id)
        .where(
            UserGroup.user_id == user_id,
            Group.chat_id == chat_id
        )
    )
    user_group = admin_result.scalar_one_or_none()

    # Получаем информацию о группе, если пользователь найден в UserGroup
    if user_group:
        group_result = await session.execute(
            select(Group).where(Group.chat_id == chat_id)
        )
        group = group_result.scalar_one_or_none()
        if group:
            logger.debug(f"Пользователь {user_id} является администратором группы {chat_id} (из UserGroup)")
            return True, group

    # Дополнительная проверка через API Telegram
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        if chat_member.status in ('administrator', 'creator'):
            # Получаем информацию о группе
            group_result = await session.execute(
                select(Group).where(Group.chat_id == chat_id)
            )
            group = group_result.scalar_one_or_none()

            if group:
                # Добавляем в UserGroup, если еще нет
                await session.execute(
                    insert(UserGroup)
                    .values(user_id=user_id, group_id=chat_id)
                    .on_conflict_do_nothing()
                )
                await session.commit()

                logger.debug(f"Пользователь {user_id} является администратором группы {chat_id} (из Telegram API)")
                return True, group
    except Exception as e:
        # Проверяем, существует ли группа вообще
        try:
            await bot.get_chat(chat_id)
            # Группа существует, но пользователь не имеет доступа
            logger.error(f"Ошибка при проверке прав через API: {e}")
        except Exception:
            # Группа не существует - пометим её неактивной
            if group:
                group.is_active = False
                await session.commit()
                logger.warning(f"Группа {chat_id} помечена как неактивная, так как не существует")

    logger.debug(f"Пользователь {user_id} не является администратором группы {chat_id}")
    return False, None


async def get_user_id_by_redis_key(key: str):
    if redis is None:
        logger.error("Redis недоступен, невозможно получить данные пользователя")
        return None
    try:
        user_id = key.split(":")[1]
        return int(user_id)
    except Exception as e:
        logger.error(f"Ошибка при извлечении user_id из ключа Redis: {e}")
        return None


async def get_user_group_id(user_id: int):
    if redis is None:
        logger.error("Redis недоступен, невозможно получить данные пользователя")
        return None
    try:
        group_id = await redis.hget(f"user:{user_id}", "group_id")
        logger.debug(f"Получены данные из Redis для пользователя {user_id}: группа {group_id}")
        if group_id:
            return int(group_id)
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении данных из Redis: {e}")
        return None


async def clear_user_data(user_id: int):
    if redis is None:
        logger.error("Redis недоступен, невозможно очистить данные пользователя")
        return False
    try:
        await redis.delete(f"user:{user_id}")
        logger.info(f"Данные пользователя {user_id} удалены из Redis")
        return True
    except Exception as e:
        logger.error(f"Ошибка при удалении данных из Redis: {e}")
        return False


@group_settings_handler.callback_query(F.data == "setup_bot")
async def setup_bot_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    logger.info(f"Кнопка настройки нажата пользователем {user_id} в группе {chat_id}")

    if not await is_user_admin(callback.bot, chat_id, user_id):
        await callback.answer("Только администратор может настроить бота", show_alert=True)
        logger.warning(f"Пользователь {user_id} не является администратором группы {chat_id}")
        return

    link = await create_start_link(callback.bot, payload=f"setup_{chat_id}")
    logger.info(f"Отправляем кнопку настройки пользователю {user_id}, глубокая ссылка: {link}")
    await callback.message.answer(
        "Нажмите кнопку ниже для настройки бота в личных сообщениях:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Настроить бота", url=link)]
        ])
    )
    await callback.answer()


@group_settings_handler.message(Command(commands=["setup", "settings"]),
                                F.chat.type.in_({"ChatType.GROUP", "ChatType.SUPERGROUP"}))
async def setup_command_in_group(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Команда {message.text} от пользователя {user_id} в группе {chat_id}")

    if await is_user_admin(message.bot, chat_id, user_id):
        link = await create_start_link(message.bot, payload=f"setup_{chat_id}")
        logger.info(f"Создана глубокая ссылка для группы {chat_id}: {link}")

        setup_button = InlineKeyboardButton(text="⚙️ Настроить бота", url=link)
        setup_markup = InlineKeyboardMarkup(inline_keyboard=[[setup_button]])

        logger.info(f"Отправляем кнопку настройки админу {user_id}")
        await message.answer(
            "Для настройки нажмите кнопку ниже и настройте меня в приватном чате.",
            reply_markup=setup_markup
        )
    else:
        logger.warning(f"Пользователь {user_id} не является администратором группы {chat_id}")
        await message.answer("Эта команда доступна только администраторам группы.")


async def get_group_settings_keyboard(group_id, session: AsyncSession):
    """Возвращает клавиатуру с настройками группы"""
    # Получаем актуальные настройки из БД с синхронизацией через Redis
    captcha_enabled, captcha_in_pm = await get_captcha_settings(session, group_id)

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"Капча: {'✅' if captcha_enabled else '❌'}",
                callback_data=f"toggle_captcha_{'on' if captcha_enabled else 'off'}_{group_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Капча в ЛС: {'✅' if captcha_in_pm else '❌'}",
                callback_data=f"toggle_pm_captcha_{'on' if captcha_in_pm else 'off'}_{group_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="Вернуться",
                callback_data=f"group_settings_{group_id}"
            )
        ]
    ])


# Общий обработчик для переключения настроек
@group_settings_handler.callback_query(F.data.startswith(("toggle_pm_captcha_", "toggle_captcha_")))
async def toggle_group_settings(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    data = callback.data
    parts = data.split("_")

    if len(parts) != 4:
        await callback.answer("Неверный формат данных", show_alert=True)
        return

    setting_type = parts[1]  # "pm_captcha" или "captcha"
    status = parts[2]  # "on" или "off"
    group_id = int(parts[3])

    # Проверка прав администратора
    is_admin, _ = await is_user_group_admin(callback.bot, user_id, group_id, session)
    if not is_admin:
        await callback.answer("У вас нет прав администратора для этой группы", show_alert=True)
        return

    new_status = "1" if status == "off" else "0"
    status_text = "включена" if new_status == "1" else "отключена"

    # Определяем ключ настройки в зависимости от типа
    setting_key = "captcha_in_pm" if setting_type == "pm_captcha" else "captcha_enabled"
    setting_name = "Капча в ЛС" if setting_type == "pm_captcha" else "Капча"

    # Сохраняем настройку в Redis и БД
    await update_captcha_settings(session, group_id, setting_key, new_status)
    logger.info(f"Статус {setting_name.lower()} для группы {group_id} изменен на {status_text}")

    # Создаем обновленную клавиатуру с актуальными настройками
    settings_keyboard = await get_group_settings_keyboard(group_id, session)

    await callback.message.edit_reply_markup(reply_markup=settings_keyboard)
    await callback.answer(f"{setting_name} {status_text} для группы")


@group_settings_handler.message(Command("settings"))
@group_settings_handler.message(
    Command(commands=["start"], magic=lambda cmd: cmd.args and cmd.args.startswith("setup_")))
async def list_groups_of_admin(message: Message, session: AsyncSession, bot: Bot):
    # Проверяем, что сообщение пришло в личных сообщениях или от администратора группы
    if message.chat.type != "private":
        # Проверяем, является ли пользователь администратором группы
        if not await is_user_admin(message.bot, message.chat.id, message.from_user.id):
            # Для обычных пользователей просто игнорируем команду, не отвечая
            return
        await message.answer("Эта команда доступна только в личных сообщениях с ботом.")
        return

    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил список групп для настройки")

    # Обработка глубокой ссылки для настройки конкретной группы
    if message.text.startswith("/start setup_"):
        try:
            chat_id = int(message.text.split("_")[1])
            logger.info(f"Получена глубокая ссылка для настройки группы {chat_id}")

            is_admin, group = await is_user_group_admin(bot, user_id, chat_id, session)
            if not is_admin:
                await message.answer("❌ У вас нет прав администратора в этой группе.")
                return

            call = CallbackQuery(
                id="direct_link",
                from_user=message.from_user,
                chat_instance="direct_link",
                message=message,
                data=f"group_settings:{chat_id}"
            )
            await show_group_settings(call, session, bot)
            return
        except Exception as e:
            logger.error(f"Ошибка обработки глубокой ссылки: {e}")
            await message.answer("⚠️ Произошла ошибка при обработке запроса.")
            return

    try:
        user_result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            user = User(
                user_id=user_id,
                username=message.from_user.username,
                full_name=f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
            )
            session.add(user)
            await session.commit()

        # 🔥 ДОБАВЛЕНО: проверим по всем группам, есть ли пользователь в базе, если он админ
        all_groups = await session.execute(select(Group))
        for group in all_groups.scalars().all():
            try:
                member = await bot.get_chat_member(group.chat_id, user_id)
                if member.status in ("administrator", "creator"):
                    exists = await session.execute(
                        select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == group.chat_id)
                    )
                    if not exists.scalar_one_or_none():
                        session.add(UserGroup(user_id=user_id, group_id=group.chat_id))
                        await session.commit()
                        logger.info(f"📌 Автоматически добавлена связь: user={user_id}, group={group.chat_id}")
            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось проверить админ-права в группе {group.chat_id} для пользователя {user_id}: {e}")

        # Получаем все группы, где пользователь — creator или в UserGroup
        groups_query = (
            select(Group)
            .outerjoin(UserGroup, Group.chat_id == UserGroup.group_id)
            .where(or_(
                Group.creator_user_id == user_id,
                UserGroup.user_id == user_id
            ))
        )
        result = await session.execute(groups_query)
        groups = list(result.scalars().all())

    except Exception as e:
        await message.answer("⚠️ Произошла ошибка при получении списка групп. Попробуйте позже.")
        logger.error(f"Ошибка при получении групп пользователя {user_id}: {e}", exc_info=True)
        return

    if not groups:
        await message.answer(
            "ℹ️ Вы не являетесь администратором ни одной группы с этим ботом. Добавьте бота в группу и назначьте его "
            "администратором.")
        logger.info(f"У пользователя {user_id} нет групп для настройки")
        return

    buttons = [
        [InlineKeyboardButton(text=g.title, callback_data=f"group_settings:{g.chat_id}")]
        for g in groups
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("🔧 Выберите группу для настройки:", reply_markup=kb)
    logger.info(f"Пользователь {user_id} получил список из {len(groups)} групп для настройки")


async def list_groups_of_admin_from_user_id(user_id: int, call: CallbackQuery, session: AsyncSession, bot: Bot):
    """Получает и показывает список групп, администрируемых пользователем"""
    try:
        groups_query = (
            select(Group)
            .outerjoin(UserGroup, Group.chat_id == UserGroup.group_id)
            .where(or_(
                Group.creator_user_id == user_id,
                UserGroup.user_id == user_id
            ))
        )
        result = await session.execute(groups_query)
        groups = list(result.scalars().all())

        if not groups:
            await call.answer("⚠️ У вас нет групп для настройки.", show_alert=True)
            return

        buttons = [
            [InlineKeyboardButton(text=g.title, callback_data=f"group_settings:{g.chat_id}")]
            for g in groups
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

        try:
            await call.message.edit_text("🔧 Выберите группу для настройки:", reply_markup=kb)
        except Exception as e:
            logger.warning(f"❌ Ошибка при попытке отправить сообщение: {e}")
            await call.answer("⚠️ Не удалось обновить сообщение. Возможно, оно устарело.", show_alert=True)

    except Exception as e:
        logger.error(f"❌ Ошибка при формировании списка групп для user_id={user_id}: {e}", exc_info=True)


@group_settings_handler.callback_query(lambda c: c.data.startswith("group_settings:"))
async def show_group_settings(call: CallbackQuery, session: AsyncSession, bot: Bot):
    user_id = call.from_user.id
    chat_id = int(call.data.split(":")[1])

    logger.debug(f"user_id: {user_id}, type: {type(user_id)}")

    # Проверяем, является ли пользователь администратором группы
    is_admin, group = await is_user_group_admin(bot, user_id, chat_id, session)

    if not is_admin or not group:
        await call.answer("❌ У вас нет прав на управление этой группой", show_alert=True)
        return

    # Сохраняем ID группы в Redis для пользователя
    await redis.hset(f"user:{user_id}", "group_id", chat_id)

    # Проверим существование записи в ChatSettings
    chat_settings_result = await session.execute(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    chat_settings = chat_settings_result.scalar_one_or_none()

    # Если настройки не существуют, создаем их с дефолтными значениями
    if not chat_settings:
        logger.info(f"Создаем настройки чата для группы {chat_id}")
        chat_settings = ChatSettings(
            chat_id=chat_id,
            enable_photo_filter=False,
            admins_bypass_photo_filter=True,
            photo_filter_mute_minutes=60
        )
        session.add(chat_settings)
        await session.commit()
    else:
        # Обновляем информацию о группе если она уже существует
        logger.info(f"Обновляем настройки чата для группы {chat_id}")
        # Проверяем, нужно ли обновлять какие-либо поля настроек
        await session.commit()

    # Используем специальный префикс для callback_data, чтобы обрабатывать их в текущем роутере
    await call.message.edit_text(
        f"🛠 Настройки для группы: {group.title}\n\n"
        "Здесь вы можете настроить работу бота в вашей группе:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏱ Настройки Мута Новых Пользователей",
                                  callback_data="redirect:new_member_requested_handler_settings")],
            [InlineKeyboardButton(text="🤖 Настройки Капчи", callback_data="redirect:captcha_settings")],
            [InlineKeyboardButton(text="🖼 Визуальная Капча", callback_data="redirect:visual_captcha_settings")],
            [InlineKeyboardButton(text="🖼 Фильтр Фотографий", callback_data="redirect:photo_filter_settings")],
            [InlineKeyboardButton(text="◀️ Назад к списку групп", callback_data="back_to_groups")]
        ]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )

    logger.info(f"Пользователь {user_id} просматривает настройки группы {chat_id} ({group.title})")


@group_settings_handler.callback_query(lambda c: c.data.startswith("redirect:"))
async def redirect_callback(call: CallbackQuery, session: AsyncSession, bot: Bot):
    original_callback = call.data.split(":", 1)[1]
    user_id = call.from_user.id

    logger.info(f"⚙️ [Redirect] Получен callback: {original_callback} от пользователя {user_id}")

    group_id = await redis.hget(f"user:{user_id}", "group_id")
    logger.debug(f"🧩 [Redirect] group_id из Redis: {group_id}")

    if not group_id:
        await call.answer("❌ Не удалось найти привязку к группе", show_alert=True)
        return

    is_admin, group = await is_user_group_admin(bot, user_id, int(group_id), session)
    logger.info(f"🔑 [Redirect] Проверка прав админа: user_id={user_id}, group_id={group_id}, is_admin={is_admin}")

    if not is_admin:
        logger.warning(f"❌ [Redirect] Отказ в доступе: user_id={user_id}, group_id={group_id}")
        await call.answer("❌ У вас нет прав на управление этой группой", show_alert=True)
        return

    # Вызываем соответствующий обработчик
    try:
        if original_callback == "captcha_settings":
            await captcha_settings_callback(call)
        elif original_callback == "photo_filter_settings":
            await photo_filter_settings_callback(call)
        elif original_callback == "new_member_requested_handler_settings":
            await new_member_requested_handler_settings(call)
        elif original_callback == "visual_captcha_settings":
            logger.info(f"🎯 Перенаправление на visual_captcha_settings для пользователя {user_id}, "
                        f"группа {group_id}")
            # Передаем None в качестве state для совместимости с сигнатурой функции
            await visual_captcha_settings(call, None)
    except Exception as e:
        logger.error(f"Ошибка при обработке redirect-callback {original_callback}: {e}", exc_info=True)
        await call.answer("⚠️ Произошла ошибка при обработке запроса", show_alert=True)


@group_settings_handler.callback_query(lambda c: c.data.startswith("toggle_photo_filter:"))
async def toggle_photo_filter(call: CallbackQuery, session: AsyncSession, bot: Bot):
    user_id = call.from_user.id
    chat_id = int(call.data.split(":")[1])

    # Проверяем права пользователя
    is_admin, _ = await is_user_group_admin(bot, user_id, chat_id, session)

    if not is_admin:
        await call.answer("❌ У вас нет прав на управление этой группой", show_alert=True)
        return

    # Получаем текущие настройки
    result = await session.execute(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    settings = result.scalar_one_or_none()

    # Если настройки не существуют, создаем их с дефолтными значениями
    if not settings:
        logger.info(f"Создаем настройки чата для группы {chat_id}")
        settings = ChatSettings(
            chat_id=chat_id,
            enable_photo_filter=True,  # Сразу устанавливаем в True, так как мы включаем фильтр
            admins_bypass_photo_filter=True,
            photo_filter_mute_minutes=60
        )
        session.add(settings)
        await session.commit()
        new_value = True
    else:
        # Изменяем настройку
        new_value = not settings.enable_photo_filter
        await session.execute(
            update(ChatSettings)
            .where(ChatSettings.chat_id == chat_id)
            .values(enable_photo_filter=new_value)
        )
        await session.commit()

    # Возвращаемся к настройкам группы
    await show_group_settings(call, session, bot)
    await call.answer(f"Фильтр фото {'включен' if new_value else 'выключен'}")


@group_settings_handler.callback_query(lambda c: c.data.startswith("toggle_admin_bypass:"))
async def toggle_admin_bypass(call: CallbackQuery, session: AsyncSession, bot: Bot):
    user_id = call.from_user.id
    chat_id = int(call.data.split(":")[1])

    # Проверяем права пользователя
    is_admin, _ = await is_user_group_admin(bot, user_id, chat_id, session)

    if not is_admin:
        await call.answer("❌ У вас нет прав на управление этой группой", show_alert=True)
        return

    # Получаем текущие настройки
    result = await session.execute(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    settings = result.scalar_one()

    # Изменяем настройку
    new_value = not settings.admins_bypass_photo_filter
    await session.execute(
        update(ChatSettings)
        .where(ChatSettings.chat_id == chat_id)
        .values(admins_bypass_photo_filter=new_value)
    )
    await session.commit()

    # Возвращаемся к настройкам группы
    await show_group_settings(call, session, bot)
    await call.answer(f"Обход фильтра админами {'включен' if new_value else 'выключен'}")


@group_settings_handler.callback_query(lambda c: c.data == "back_to_groups")
async def back_to_groups_list(call: CallbackQuery, session: AsyncSession, bot: Bot):
    user_id = call.from_user.id
    # Сохраняем предыдущую группу в Redis для возможного восстановления
    # (Закомментировано удаление, чтобы сохранить привязку)
    # await redis.hdel(f"user:{user_id}", "group_id")
    await list_groups_of_admin_from_user_id(user_id, call, session, bot)


@group_settings_handler.my_chat_member()
async def handle_bot_added(event: ChatMemberUpdated, session: AsyncSession, bot: Bot):
    # Обрабатываем только добавление бота в группу
    if event.new_chat_member.status not in ("member", "administrator"):
        return

    chat = event.chat
    chat_id = chat.id
    logger.info(f"Бот добавлен в группу: {chat.title} (ID: {chat_id})")

    try:
        async with session.begin():
            # Проверяем, есть ли уже такая группа в БД
            group_result = await session.execute(
                select(Group).where(Group.chat_id == chat_id)
            )
            group = group_result.scalar_one_or_none()

            if not group:
                # Получаем список админов группы
                admins = await bot.get_chat_administrators(chat_id)
                creator = next((a for a in admins if a.status == "creator"), None)
                creator_id = creator.user.id if creator else None

                # Сначала создаем записи пользователей, если их еще нет
                for admin in admins:
                    admin_id = admin.user.id
                    admin_username = admin.user.username
                    admin_full_name = f"{admin.user.first_name} {admin.user.last_name or ''}".strip()

                    # Проверяем, существует ли пользователь в базе
                    user_result = await session.execute(
                        select(User).where(User.user_id == admin_id)
                    )
                    user = user_result.scalar_one_or_none()

                    if not user:
                        # Создаем пользователя
                        user = User(
                            user_id=admin_id,
                            username=admin_username,
                            full_name=admin_full_name
                        )
                        session.add(user)

                await session.flush()

                group = Group(
                    chat_id=chat_id,
                    title=chat.title,
                    creator_user_id=creator_id,
                    is_active=True
                )
                logger.info(f"Сохраняем группу: {chat.title} ({chat.id}), creator={creator_id}")
                session.add(group)
                await session.flush()

                # Добавляем всех администраторов в UserGroup
                for admin in admins:
                    admin_id = admin.user.id
                    await session.execute(
                        insert(UserGroup)
                        .values(user_id=admin_id, group_id=chat_id)
                        .on_conflict_do_nothing()
                    )

                    logger.info("✅ Группа успешно сохранена в БД")

        # Отправляем сообщение в группу
        setup_link = await create_start_link(bot, f"setup_{chat_id}", encode=True)
        await bot.send_message(
            chat_id,
            "🤖 Спасибо за добавление меня в группу!\n\n"
            "⚙️ <b>Для настройки бота</b> администраторы могут:\n"
            "1. Написать мне в ЛС команду <code>/settings</code>\n"
            f"2. Или перейти по ссылке: {setup_link}\n\n"
            "🔐 Только администраторы группы имеют доступ к настройкам.",
            parse_mode="HTML"
        )
        logger.info(f"Группа {chat.title} успешно добавлена в базу данных")

    except Exception as e:
        logger.error(f"Ошибка при добавлении группы {chat.title}: {str(e)}", exc_info=True)
        try:
            await session.rollback()
        except:
            pass


@group_settings_handler.message(Command("group_info"))
async def show_group_info(message: Message, session: AsyncSession, bot: Bot):
    """Показывает информацию о текущей группе и список администраторов"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("ℹ️ Эта команда предназначена для использования в группах")
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    try:
        # Проверяем, зарегистрирована ли группа в БД
        group_result = await session.execute(select(Group).where(Group.chat_id == chat_id))
        group = group_result.scalar_one_or_none()

        if not group:
            await message.answer("ℹ️ Эта группа еще не зарегистрирована в базе данных бота.")
            return

        # Получаем список администраторов из Telegram
        admins = await bot.get_chat_administrators(chat_id)

        # Получаем список администраторов из нашей БД
        db_admins_result = await session.execute(
            select(UserGroup.user_id).where(UserGroup.group_id == chat_id)
        )
        db_admin_ids = [row[0] for row in db_admins_result]

        # Получаем настройки капчи
        captcha_enabled, captcha_in_pm = await get_captcha_settings(session, chat_id)

        # Формируем отчет
        text = [
            f"📊 <b>Информация о группе:</b> {message.chat.title}",
            f"🆔 ID: <code>{chat_id}</code>",
            f"👑 Создатель: <code>{group.creator_user_id}</code>",
            f"🔒 Капча: {'Включена' if captcha_enabled else 'Отключена'}",
            f"📱 Капча в ЛС: {'Включена' if captcha_in_pm else 'Отключена'}",
            "",
            "👥 <b>Администраторы в Telegram:</b>"
        ]

        for admin in admins:
            name = admin.user.username or f"{admin.user.first_name} {admin.user.last_name or ''}".strip()
            text.append(f"- {name} (ID: <code>{admin.user.id}</code>) - {admin.status}")

        text.extend([
            "",
            f"🔑 <b>Администраторы в базе бота</b> ({len(db_admin_ids)}):"
        ])

        for admin_id in db_admin_ids:
            text.append(f"- ID: <code>{admin_id}</code>")

        await message.answer("\n".join(text), parse_mode="HTML")
        logger.info(f"Информация о группе {chat_id} отправлена по запросу пользователя {user_id}")

    except Exception as e:
        logger.error(f"Ошибка при получении информации о группе {chat_id}: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка при получении информации о группе.")


@group_settings_handler.message(Command("force_debug"))
async def force_debug(message: Message, session: AsyncSession, bot: Bot):
    """Показывает отладочную информацию обо всех группах и правах пользователя"""
    user_id = message.from_user.id

    # Выводим все группы в базе
    groups_result = await session.execute(select(Group))
    all_groups = groups_result.scalars().all()

    await message.answer(f"📊 Всего групп в базе: {len(all_groups)}")

    # Выводим группы, где пользователь админ по нашей БД
    admin_groups_query = (
        select(Group)
        .outerjoin(UserGroup, Group.chat_id == UserGroup.group_id)
        .where(or_(
            Group.creator_user_id == user_id,
            UserGroup.user_id == user_id
        ))
    )
    admin_groups_result = await session.execute(admin_groups_query)
    admin_groups = admin_groups_result.scalars().all()

    await message.answer(f"👑 Вы админ в {len(admin_groups)} группах по БД:")
    for g in admin_groups:
        await message.answer(f"- {g.title} (ID: {g.chat_id})")

    # Проверяем связи в UserGroup
    user_group_result = await session.execute(
        select(UserGroup).where(UserGroup.user_id == user_id)
    )
    user_groups = user_group_result.scalars().all()

    await message.answer(f"🔗 Связей UserGroup для вас: {len(user_groups)}")
    for ug in user_groups:
        await message.answer(f"- Group ID: {ug.group_id}")

    # Выводим все группы
    await message.answer("📋 Список всех групп:")
    for g in all_groups:
        # Проверяем, есть ли пользователь в UserGroup для этой группы
        is_in_user_group = any(ug.group_id == g.chat_id for ug in user_groups)
        is_creator = g.creator_user_id == user_id

        status = []
        if is_creator:
            status.append("👑 Создатель")
        if is_in_user_group:
            status.append("✅ В UserGroup")

        status_str = ", ".join(status) if status else "❌ Нет прав"

        await message.answer(
            f"Group: {g.title} | Creator: {g.creator_user_id} | Chat ID: {g.chat_id}\n"
            f"Ваш статус: {status_str}"
        )