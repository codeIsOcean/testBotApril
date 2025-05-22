from aiogram import Router, F, Bot
from aiogram.types import ChatMemberUpdated, Message, ChatPermissions, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import ChatMemberUpdatedFilter, Command
from aiogram.enums import ChatMemberStatus, ChatType
from datetime import datetime, timedelta
import asyncio
from bot.services.redis_conn import redis
from sqlalchemy import select, update, insert
from bot.database.models import ChatSettings
from bot.database.session import get_session
from loguru import logger

new_member_requested_handler = Router()


@new_member_requested_handler.callback_query(F.data == "new_member_requested_handler_settings")
async def new_member_requested_handler_settings(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе. Сначала нажмите 'настроить' в группе.")
        await callback.answer()
        return

    group_id = int(group_id)

    # Проверяем текущее состояние мута для этой группы в Redis
    mute_enabled = await redis.get(f"group:{group_id}:mute_new_members")

    # Если в Redis нет данных, проверяем в БД
    if mute_enabled is None:
        async with get_session() as session:
            result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == group_id))
            settings = result.scalar_one_or_none()

            if settings and hasattr(settings, 'mute_new_members'):
                mute_enabled = "1" if settings.mute_new_members else "0"
                # Обновляем Redis
                await redis.set(f"group:{group_id}:mute_new_members", mute_enabled)
            else:
                mute_enabled = "0"  # По умолчанию выключено

    status = "✅ Включено" if mute_enabled == "1" else "❌ Выключено"

    # Создаем клавиатуру с галочкой перед выбранным состоянием
    enable_text = "✓ Включить" if mute_enabled == "1" else "Включить"
    disable_text = "✓ Выключить" if mute_enabled != "1" else "Выключить"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=enable_text, callback_data="mute_new_members:enable"),
            InlineKeyboardButton(text=disable_text, callback_data="mute_new_members:disable")
        ],
        [InlineKeyboardButton(text="« Назад", callback_data="show_settings")]
    ])

    # Используем edit_text вместо answer для редактирования текущего сообщения
    message_text = (
        f"⚙️ Настройки мута для новых участников при ручном добавлении:\n\n"
        f"• Новые участники автоматически получают мут\n"
        f"• Мут действует 3660 дней\n"
        f"• Текущее состояние: {status}\n\n"
        f"Эта функция защищает вашу группу от спамеров."
    )

    try:
        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка при обновлении сообщения: {str(e)}")

    await callback.answer()


# ✅ Мут через RESTRICTED статус (когда одобрение идёт через join_request)
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"}),
    ChatMemberUpdatedFilter(
        member_status_changed=(None, ChatMemberStatus.RESTRICTED)
    )
)
async def mute_handler(event: ChatMemberUpdated):
    """Мут участников, не прошедших одобрение"""
    await mute_unapproved_member(event)


# ✅ Вариант 2: Отслеживаем вручную обновление chat_member после одобрения
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"})
)
async def manually_mute_on_approval(event: ChatMemberUpdated):
    """Мут вручную одобренных участников, если Telegram прислал событие"""
    try:
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status

        print(f"[V2] Обработка chat_member: {event.from_user.id} | old={old_status} -> new={new_status}")

        if old_status in ("left", "kicked") and new_status == "member":
            user = event.new_chat_member.user
            chat = event.chat

            # Проверяем, включен ли мут для этой группы
            mute_enabled = await redis.get(f"group:{chat.id}:mute_new_members")
            if not mute_enabled or mute_enabled != "1":
                print(f"Мут для группы {chat.id} отключен, пропускаем")
                return

            await event.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=datetime.now() + timedelta(days=366 * 10)
            )

            await asyncio.sleep(1)
            print(f"🔇 Пользователь @{user.username} был замьючен после ручного одобрения (chat_member).")
        else:
            print(f"[V2] Не обработан: статус не соответствует. old={old_status}, new={new_status}")

    except Exception as e:
        print(f"MUTE ERROR (variant 2 - manual chat_member): {str(e)}")


# ✅ Повторная проверка при изменении прав
@new_member_requested_handler.chat_member(
    F.chat.type.in_({"group", "supergroup"}),
    ChatMemberUpdatedFilter(
        member_status_changed=(ChatMemberStatus.RESTRICTED, ChatMemberStatus.MEMBER)
    )
)
async def recheck_approved_member(event: ChatMemberUpdated):
    """Повторно мутим, если одобренный пользователь всё ещё не подтверждён"""
    await mute_unapproved_member(event)


@new_member_requested_handler.callback_query(F.data == "mute_new_members:enable")
async def enable_mute_new_members(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе.")
        await callback.answer()
        return

    group_id = int(group_id)

    await redis.set(f"group:{group_id}:mute_new_members", "1")

    async with get_session() as session:
        result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == group_id))
        settings = result.scalar_one_or_none()

        if settings:
            await session.execute(
                update(ChatSettings).where(ChatSettings.chat_id == group_id).values(
                    mute_new_members=True
                )
            )
        else:
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=group_id,
                    mute_new_members=True,
                    enable_photo_filter=True,
                    admins_bypass_photo_filter=True,
                    photo_filter_mute_minutes=60
                )
            )

        await session.commit()
        logger.info(f"✅ Включен мут новых участников для группы {group_id}")

    await callback.answer("✅ Функция включена")
    await new_member_requested_handler_settings(callback)


@new_member_requested_handler.callback_query(F.data == "mute_new_members:disable")
async def disable_mute_new_members(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе.")
        await callback.answer()
        return

    group_id = int(group_id)

    # Выключаем функцию мута для группы в Redis
    await redis.set(f"group:{group_id}:mute_new_members", "0")

    # Сохраняем настройки в БД
    async with get_session() as session:
        result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == group_id))
        settings = result.scalar_one_or_none()

        if settings:
            await session.execute(
                update(ChatSettings).where(ChatSettings.chat_id == group_id).values(
                    mute_new_members=False
                )
            )
        else:
            await session.execute(
                insert(ChatSettings).values(
                    chat_id=group_id,
                    mute_new_members=False,
                    enable_photo_filter=True,
                    admins_bypass_photo_filter=True,
                    photo_filter_mute_minutes=60
                )
            )

        await session.commit()
        logger.info(f"❌ Выключен мут новых участников для группы {group_id}")

    await callback.answer("❌ Функция выключена")
    await new_member_requested_handler_settings(callback)


async def mute_unapproved_member(event: ChatMemberUpdated):
    """Мут участников, не прошедших одобрение"""
    try:
        if getattr(event.new_chat_member, 'is_approved', True):
            return

        # Проверяем, включен ли мут для этой группы
        chat_id = event.chat.id
        mute_enabled = await redis.get(f"group:{chat_id}:mute_new_members")

        # Если в Redis нет данных, проверяем в БД
        if mute_enabled is None:
            async with get_session() as session:
                result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
                settings = result.scalar_one_or_none()

                if settings and hasattr(settings, 'mute_new_members'):
                    mute_enabled = "1" if settings.mute_new_members else "0"
                    await redis.set(f"group:{chat_id}:mute_new_members", mute_enabled)
                else:
                    mute_enabled = "0"  # по умолчанию отключено

        if mute_enabled != "1":
            logger.debug(f"Мут для группы {chat_id} отключен, пропускаем")
            return

        user = event.new_chat_member.user

        await event.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            ),
            until_date=datetime.now() + timedelta(days=366 * 10)  # 10 лет
        )

        await asyncio.sleep(1)

        try:
            await event.bot.send_message(
                chat_id=event.chat.id,
                text=f"🚫 Спамер @{user.username or user.id} был автоматически замьючен."
            )
            logger.info(f"Пользователь @{user.username or user.id} (ID: {user.id}) замьючен в группе {event.chat.id}")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение в чат {event.chat.id}: {str(e)}")

    except Exception as e:
        logger.error(f"💥 MUTE ERROR: {str(e)}")
        print(f"💥 MUTE ERROR: {str(e)}")


