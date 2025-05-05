from aiogram import Router, F, Bot
from aiogram.types import ChatMemberUpdated, Message, ChatPermissions, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import ChatMemberUpdatedFilter, Command
from aiogram.enums import ChatMemberStatus, ChatType
from datetime import datetime, timedelta
import asyncio
from bot.services.redis_conn import redis

new_member_requested_handler = Router()


@new_member_requested_handler.callback_query(F.data == "new_member_requested_handler_settings")
async def process_mute_settings(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе. Сначала нажмите 'настроить' в группе.")
        await callback.answer()
        return

    # Проверяем текущее состояние мута для этой группы
    mute_enabled = await redis.get(f"group:{group_id}:mute_new_members")
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
    await callback.message.edit_text(
        f"⚙️ Настройки мута для новых участников при ручном добавлении:\n\n"
        f"• Новые участники автоматически получают мут\n"
        f"• Мут действует 3660 дней\n"
        f"• Текущее состояние: {status}\n\n"
        f"Эта функция защищает вашу группу от спамеров.",
        reply_markup=keyboard
    )


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


# Обработчики для включения/отключения мута новых пользователей
@new_member_requested_handler.callback_query(F.data == "mute_new_members:enable")
async def enable_mute_new_members(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе.")
        await callback.answer()
        return

    # Включаем функцию мута для группы
    await redis.set(f"group:{group_id}:mute_new_members", "1")

    await callback.answer("✅ Функция включена")
    await process_mute_settings(callback)  # Показываем обновленные настройки


@new_member_requested_handler.callback_query(F.data == "mute_new_members:disable")
async def disable_mute_new_members(callback: CallbackQuery):
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.message.answer("❌ Не удалось найти привязку к группе.")
        await callback.answer()
        return

    # Выключаем функцию мута для группы
    await redis.set(f"group:{group_id}:mute_new_members", "0")

    await callback.answer("❌ Функция выключена")
    await process_mute_settings(callback)  # Показываем обновленные настройки


async def mute_unapproved_member(event: ChatMemberUpdated):
    """Мут участников, не прошедших одобрение"""
    try:
        if getattr(event.new_chat_member, 'is_approved', True):
            return

        # Проверяем, включен ли мут для этой группы
        chat_id = event.chat.id
        mute_enabled = await redis.get(f"group:{chat_id}:mute_new_members")

        if not mute_enabled or mute_enabled != "1":
            print(f"Мут для группы {chat_id} отключен, пропускаем")
            return

        user = event.new_chat_member.user
        chat = event.chat

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
            until_date=datetime.now() + timedelta(days=366)
        )

        await asyncio.sleep(1)
        await event.bot.send_message(
            chat_id=chat.id,
            text=f"🚫 Спамер @{user.username} был автоматически замьючен."
        )
        print(f"Пользователь @{user.username} (ID: {user.id}) замьючен в группе {chat.id}")

    except Exception as e:
        print(f"MUTE ERROR: {str(e)}")