from aiogram import Bot
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, ChatMemberUpdated
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert, or_
import logging

from bot.database.models import Group, ChatSettings, UserGroup, User
from bot.handlers.settings_inprivate_handler import settings_inprivate_handler, redis
from bot.handlers.settings_inprivate_handler import photo_filter_settings_callback
from bot.handlers.settings_inprivate_handler import show_settings_callback
from bot.handlers.settings_inprivate_handler import captcha_settings_callback
from bot.handlers.new_member_requested_mute import process_mute_settings as new_member_requested_handler_settings

logger = logging.getLogger(__name__)

group_settings_handler = Router()


async def is_user_group_admin(bot: Bot, user_id: int, chat_id: int, session: AsyncSession) -> tuple[bool, Group | None]:
    """Проверяет, является ли пользователь администратором группы"""
    logger.debug(f"Проверка админских прав для пользователя {user_id} в группе {chat_id}")

    # Проверяем, является ли пользователь создателем группы
    creator_result = await session.execute(
        select(Group).where(Group.chat_id == chat_id, Group.creator_user_id == user_id)
    )
    group = creator_result.scalar_one_or_none()

    if group:
        logger.debug(f"Пользователь {user_id} является создателем группы {chat_id}")
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


@group_settings_handler.message(Command("settings"))
@group_settings_handler.message(
    Command(commands=["start"], magic=lambda cmd: cmd.args and cmd.args.startswith("setup_")))
async def list_groups_of_admin(message: Message, session: AsyncSession, bot: Bot):
    # Проверяем, что сообщение пришло в личных сообщениях
    if message.chat.type != "private":
        await message.answer("Эта команда доступна только в личных сообщениях с ботом.")
        return

    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил список групп для настройки")

    # Обработка глубокой ссылки для настройки конкретной группы
    if message.text.startswith("/start setup_"):
        try:
            chat_id = int(message.text.split("_")[1])
            logger.info(f"Получена глубокая ссылка для настройки группы {chat_id}")

            # Проверяем права пользователя
            is_admin, group = await is_user_group_admin(bot, user_id, chat_id, session)

            if not is_admin:
                await message.answer("❌ У вас нет прав администратора в этой группе.")
                return

            # Создаем фейковый CallbackQuery для показа настроек
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
        # Проверим, есть ли пользователь в базе, если нет - создадим
        user_result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            # Создаем пользователя
            user = User(
                user_id=user_id,
                username=message.from_user.username,
                full_name=f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
            )
            session.add(user)
            await session.commit()

        # Получаем все группы, где пользователь является администратором
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

        # Дополнительная проверка - запросим группы напрямую через Telegram API
        user_chats = []
        try:
            # Проверяем, в каких группах пользователь является админом
            bot_info = await bot.get_me()
            bot_id = bot_info.id

            # Логируем для отладки
            logger.debug(f"Ищем группы для пользователя {user_id} через Telegram API")

            # Дополнительные действия можно добавить при необходимости
        except Exception as e:
            logger.error(f"Не удалось проверить группы через Telegram API: {e}")

    except Exception as e:
        await message.answer("⚠️ Произошла ошибка при получении списка групп. Попробуйте позже.")
        logger.error(f"Ошибка при получении групп пользователя {user_id}: {e}", exc_info=True)
        return



        # 🧠 Автоматически проверим группы из базы, где бот есть, но user не добавлен
        all_groups_result = await session.execute(select(Group))
        all_groups = all_groups_result.scalars().all()

        # Список групп для удаления из базы
        groups_to_remove = []

        for group in all_groups:
            try:
                member = await bot.get_chat_member(group.chat_id, user_id)
                if member.status in ("administrator", "creator"):
                    # Проверим, нет ли уже связи
                    exists = await session.execute(
                        select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == group.chat_id)
                    )
                    if not exists.scalar_one_or_none():
                        session.add(UserGroup(user_id=user_id, group_id=group.chat_id))
                        await session.commit()
                        logger.info(f"📌 Автоматически добавлена связь: user={user_id}, group={group.chat_id}")
            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось получить статус члена группы {group.chat_id} для пользователя {user_id}: {e}")

                # Проверяем, существует ли группа через другой метод
                try:
                    chat_info = await bot.get_chat(group.chat_id)
                    # Группа существует, но пользователь не имеет доступа или другая ошибка
                    logger.info(f"Группа {group.chat_id} существует, но возникла ошибка доступа")
                except Exception:
                    # Группа не существует - пометим для удаления
                    logger.warning(f"🗑️ Группа {group.chat_id} не существует, будет удалена из базы")
                    groups_to_remove.append(group.chat_id)

        # Удаляем несуществующие группы из базы
        if groups_to_remove:
            try:
                # Сначала удаляем связи в UserGroup
                for chat_id in groups_to_remove:
                    await session.execute(
                        update(Group)
                        .where(Group.chat_id == chat_id)
                        .values(is_active=False)
                    )
                await session.commit()
                logger.info(f"🧹 Помечено как неактивные {len(groups_to_remove)} несуществующих групп")
            except Exception as e:
                logger.error(f"❌ Ошибка при удалении несуществующих групп: {e}")
                await session.rollback()

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

    try:
        chat = await bot.get_chat(int(chat_id))
        if chat.username:
            link = f"https://t.me/{chat.username}"
            title = f"{chat.title}"
        else:
            title = f"{chat.title} (ID: {chat_id})"
    except Exception:
        title = f"ID: {chat_id}"

    # Используем специальный префикс для callback_data, чтобы обрабатывать их в текущем роутере
    await call.message.edit_text(
        f"🛠 Настройки для группы: {title}\n\n"
        "Здесь вы можете:\n"
        "- 🚫 Забанить пользователя\n"
        "- 🤖 Настроить капчу для новых участников\n"
        "- 🔚 Выйти из режима настройки (/cancel)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Настройки Мута Новых Пользователей",
                                  callback_data="redirect:new_member_requested_handler_settings")],
            [InlineKeyboardButton(text="Настройки Капчи", callback_data="redirect:captcha_settings")],
            [InlineKeyboardButton(text="Фильтр Фотографий", callback_data="redirect:photo_filter_settings")]
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

    is_admin, _ = await is_user_group_admin(bot, user_id, int(group_id), session)
    if not is_admin:
        await call.answer("❌ У вас нет прав на управление этой группой", show_alert=True)
        return

    try:
        if original_callback == "captcha_settings":
            await captcha_settings_callback(call)
        ...
    except Exception as e:
        logger.exception(f"💥 Ошибка в redirect_callback: {e}")
        await call.answer("⚠️ Произошла ошибка при обработке запроса", show_alert=True)
        return

    # Вызываем соответствующий обработчик
    try:
        if original_callback == "captcha_settings":
            await captcha_settings_callback(call)
        elif original_callback == "photo_filter_settings":
            await photo_filter_settings_callback(call)
        elif original_callback == "new_member_requested_handler_settings":
            await new_member_requested_handler_settings(call)
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
    settings = result.scalar_one()

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

        # Формируем отчет
        text = [
            f"📊 <b>Информация о группе:</b> {message.chat.title}",
            f"🆔 ID: <code>{chat_id}</code>",
            f"👑 Создатель: <code>{group.creator_user_id}</code>",
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
async def force_debug(message: Message, session: AsyncSession):
    groups = await session.execute(select(Group))
    for g in groups.scalars().all():
        await message.answer(f"Group: {g.title} | Creator: {g.creator_user_id} | Chat ID: {g.chat_id}")
