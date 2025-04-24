from aiogram import Router, F
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

# обрабатывает кнопки, когда админ нажимает "настроить бота",
#  Callback-хэндлер "Настроить бота"

group_setup_handler = Router()


@group_setup_handler.callback_query(F.data == "setup_bot") # использовали в grop_add_handler setup_bot
async def setup_bot_callback(callback: CallbackQuery):
    """Реакция на кнопку 'Настройть бота'"""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    print(f"🔧 Админ {user_id} нажал кнопку 'Настроить бота' в чате {chat_id}")

    # проверяем, админ ли пользователь
    member = await callback.bot.get_chat_member(chat_id, user_id)
    print(f"👤 Статус пользователя: {member.status}")

    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
        await callback.answer("Только администратор может настроить бота", show_alert=True)
        return
    me = await callback.bot.get_me()
    bot_username = me.username

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔧 Здесь", callback_data="setup_here"),
            InlineKeyboardButton(
                text="💬 В приватном чате",
                url=f"https://t.me/{bot_username}?start=setup"
            )
        ]
    ])

    await callback.message.answer(
        "Где вы хотите настроить бота? ",
        reply_markup=kb
    )
    await callback.answer()


@group_setup_handler.message(F.text.startswith("/start setup"))
async def start_setup_private(message: Message):
    print(f"🔐 Настройка через приват запущена от {message.from_user.id}")
    await message.answer(
        "🔐 Добро пожаловать в настройки бота.\nЗдесь вы можете задать параметры фильтрации, модерирования и прочее."
    )
