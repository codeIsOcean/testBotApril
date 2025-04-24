from aiogram import Router, F
from aiogram.types import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums.chat_member_status import ChatMemberStatus
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.queries import get_or_create_user, save_group

group_add_handler = Router()


@group_add_handler.my_chat_member()
async def check_bot_added_to_group(event: ChatMemberUpdated, session: AsyncSession):
    """Проверяем, что бот был добавлен в группу"""
    print("🛠 Хендлер my_chat_member сработал")
    print(f"📥 Новый статус: {event.new_chat_member.status}")

    # проверяем, стал ли бот админом
    if event.new_chat_member.status in[ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER]:
        user = event.from_user
        chat = event.chat
        print(f"✅ Бот добавлен в группу: {chat.title} (ID: {chat.id}) от пользователя {user.full_name} (ID: {user.id})")
        # сохраняем пользователя в группу бд
        try:
            # отвечает за добавления бота в группу и действия, связанные с этим
            db_user = await get_or_create_user(session, user.id, user.full_name, user.username)
            print("✅ пользователь сохранен в бд")

            # сохраняем информацию о группе
            await save_group(session, chat.id, chat.title, db_user)
            print("✅ группа сохранена в бд")

        except exception as e:
            print(f"❌ ошибка при сохранений в БД: {e}")

        # кнопка настройка
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Настроить бота", callback_data="setup_bot")]
        ])

        try:
            await event.bot.send_message(
                chat_id=chat.id,
                text="⚙️ Бот добавлен в группу.\nТолько администратор может настроить его.",
                reply_markup=kb
            )
            print("✅ сообщение отправлено в группу")
        except Exception as e:
            print(f"❌ ошибка при отправке сообщения в группу: {e}")
    else:
        print("⛔️ бот не получил статус администратора, сообщение не отправлено")