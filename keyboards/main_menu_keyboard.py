from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton


def get_main_menu_buttons():
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="➕ добавьте меня в ваш чат", callback_data="add_group",
            url="https://t.me/KvdModerBot?startgroup=true"
        )
    )
    kb.row(
        InlineKeyboardButton(text="👥 Группа", url="https://t.me/your_group_link"),
        InlineKeyboardButton(text="📢 Канал", url="https://t.me/your_channel_linkkkk")
    )
    kb.row(
        InlineKeyboardButton(text="🔧 Поддержка", callback_data="support"),
        InlineKeyboardButton(text="📄 Информация", callback_data="information")
    )

    return kb.as_markup()