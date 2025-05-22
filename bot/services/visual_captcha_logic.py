# services/visual_captcha_logic.py
import asyncio
import random
import logging
from io import BytesIO
from typing import Dict, Optional, Any, Union, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.deep_linking import create_start_link
from PIL import Image, ImageDraw, ImageFont

from bot.services.redis_conn import redis

# Настраиваем логгер
logger = logging.getLogger(__name__)


async def generate_visual_captcha() -> tuple[str, BufferedInputFile]:
    """
    Генерирует визуальную капчу с искажённым текстом или математическим выражением
    Возвращает: (правильный ответ, изображение капчи)
    """
    # Создаем изображение
    width, height = 300, 120
    img = Image.new('RGB', (width, height), color=(255, 255, 255))
    d = ImageDraw.Draw(img)

    # Выбираем шрифт
    try:
        fonts = [
            ImageFont.truetype("arial.ttf", size)
            for size in [36, 40, 42, 38]
        ]
    except IOError:
        fonts = [ImageFont.load_default()]

    # Определяем тип капчи (число, текст или мат. выражение)
    captcha_type = random.choice(['number', 'text', 'math'])

    if captcha_type == 'number':
        # Генерируем случайное число от 1 до 50
        answer = str(random.randint(1, 50))
        text_to_draw = answer
    elif captcha_type == 'text':
        # Генерируем случайную строку из букв и цифр
        chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        answer = ''.join(random.choice(chars) for _ in range(4))
        text_to_draw = answer
    else:  # math
        # Генерируем простое математическое выражение
        a = random.randint(1, 20)
        b = random.randint(1, 10)
        operation = random.choice(['+', '-', '*'])
        if operation == '+':
            answer = str(a + b)
            text_to_draw = f"{a}+{b}"
        elif operation == '-':
            # Гарантируем положительный результат
            if a < b:
                a, b = b, a
            answer = str(a - b)
            text_to_draw = f"{a}-{b}"
        else:  # *
            a = random.randint(1, 10)
            b = random.randint(1, 9)
            answer = str(a * b)
            text_to_draw = f"{a}×{b}"

    # Рисуем фоновый шум (линии)
    for _ in range(8):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        d.line([(x1, y1), (x2, y2)], fill=(
            random.randint(160, 200),
            random.randint(160, 200),
            random.randint(160, 200)
        ), width=1)

    # Добавляем точечный шум
    for _ in range(500):
        d.point(
            (random.randint(0, width), random.randint(0, height)),
            fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        )

    # Рисуем каждый символ отдельно, с разным поворотом и цветом
    spacing = width // (len(text_to_draw) + 2)  # Распределяем символы по ширине
    x_offset = spacing

    for char in text_to_draw:
        # Случайный поворот для каждого символа
        angle = random.randint(-15, 15)
        font = random.choice(fonts)

        # Создаем отдельное изображение для символа
        char_img = Image.new('RGBA', (40, 50), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_img)

        # Случайный цвет для символа (не слишком светлый)
        color = (
            random.randint(0, 100),
            random.randint(0, 100),
            random.randint(0, 100)
        )

        # Рисуем символ
        char_draw.text((5, 5), char, font=font, fill=color)

        # Поворачиваем и накладываем на основное изображение
        rotated = char_img.rotate(angle, expand=1, fillcolor=(255, 255, 255, 0))
        y_pos = random.randint(height // 4, height // 2)
        img.paste(rotated, (x_offset, y_pos), rotated)

        # Увеличиваем смещение для следующего символа
        x_offset += spacing + random.randint(-10, 10)

    # Добавляем искажающие линии поверх текста
    for _ in range(4):
        start_y = random.randint(height // 3, 2 * height // 3)
        end_y = random.randint(height // 3, 2 * height // 3)
        d.line([(0, start_y), (width, end_y)], fill=(
            random.randint(0, 150),
            random.randint(0, 150),
            random.randint(0, 150)
        ), width=2)

    # Конвертируем изображение в байты
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)

    # Создаем файл для отправки
    file = BufferedInputFile(img_byte_arr.getvalue(), filename="captcha.png")

    return answer, file


async def create_group_invite_link(bot: Bot, group_name: str) -> str:
    """
    Создает ссылку на группу с deep link параметром
    """
    deep_link = await create_start_link(bot, f"deep_link_{group_name}")
    return deep_link


async def delete_message_after_delay(bot: Bot, chat_id: int, message_id: int, delay: float):
    """
    Удаляет сообщение через указанное время
    """
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        if "message to delete not found" in str(e).lower():
            # Игнорируем эту конкретную ошибку полностью
            pass
        else:
            # Логируем только необычные ошибки
            logger.error(f"Не удалось удалить сообщение {message_id}: {str(e)}")


async def save_join_request(user_id: int, chat_id: int, group_id: str) -> None:
    """
    Сохраняет информацию о запросе на вступление в Redis
    """
    # Сохраняем информацию в Redis с TTL (истекает через 1 час)
    await redis.setex(
        f"join_request:{user_id}:{group_id}",
        3600,  # 1 час
        str(chat_id)
    )


async def create_deeplink_for_captcha(bot: Bot, group_id: str) -> str:
    """
    Создает deep link для прохождения капчи
    """
    deep_link = await create_start_link(bot, f"deep_link_{group_id}")
    logger.info(f"Создан deep link: {deep_link} для группы {group_id}")
    return deep_link


async def get_captcha_keyboard(deep_link: str) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с кнопкой для прохождения капчи
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧩 Пройти капчу", url=deep_link)]
        ]
    )


async def get_group_settings_keyboard(group_id: str, captcha_enabled: str) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для настроек капчи в группе
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Включено" if captcha_enabled == "1" else "Включить",
                    callback_data=f"set_visual_captcha:{group_id}:1"
                ),
                InlineKeyboardButton(
                    text="✅ Выключено" if captcha_enabled == "0" else "Выключить",
                    callback_data=f"set_visual_captcha:{group_id}:0"
                )
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="redirect:captcha_settings")]
        ]
    )


async def get_group_join_keyboard(group_link: str, group_display_name: str = None) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для присоединения к группе
    """
    button_text = f"Присоединиться к группе {group_display_name}" if group_display_name else "Присоединиться к группе"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button_text, url=group_link)]
        ]
    )


async def save_captcha_data(user_id: int, captcha_answer: str, group_name: str, attempts: int = 0) -> None:
    """
    Сохраняет данные капчи в Redis
    """
    await redis.setex(
        f"captcha:{user_id}",
        300,  # 5 минут
        f"{captcha_answer}:{group_name}:{attempts}"
    )


async def get_captcha_data(user_id: int) -> Dict[str, Any]:
    """
    Получает данные капчи из Redis
    """
    redis_data = await redis.get(f"captcha:{user_id}")
    if not redis_data:
        return None

    parts = redis_data.split(":")
    if len(parts) < 3:
        return None

    return {
        "captcha_answer": parts[0],
        "group_name": parts[1],
        "attempts": int(parts[2]) if len(parts) > 2 else 0
    }


async def set_rate_limit(user_id: int, seconds: int = 180) -> None:
    """
    Устанавливает ограничение на попытки для пользователя
    """
    await redis.setex(f"rate_limit:{user_id}", seconds, str(seconds))


async def check_rate_limit(user_id: int) -> bool:
    """
    Проверяет, находится ли пользователь под ограничением
    Возвращает True, если ограничение действует (пользователь не может выполнять действия)
    Возвращает False, если ограничений нет
    """
    rate_limited = await redis.exists(f"rate_limit:{user_id}")
    return bool(rate_limited)


async def get_rate_limit_time_left(user_id: int) -> int:
    """
    Возвращает оставшееся время ограничения в секундах
    Если ограничения нет, возвращает 0
    """
    ttl = await redis.ttl(f"rate_limit:{user_id}")
    return max(0, ttl)


async def check_admin_rights(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Проверяет права администратора пользователя в группе
    """
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        return False


async def set_visual_captcha_status(chat_id: int, enabled: bool) -> None:
    """
    Устанавливает статус визуальной капчи для группы
    """
    value = "1" if enabled else "0"
    await redis.set(f"visual_captcha_enabled:{chat_id}", value)


async def get_visual_captcha_status(chat_id: int) -> bool:
    """
    Получает статус визуальной капчи для группы
    """
    value = await redis.get(f"visual_captcha_enabled:{chat_id}")
    return value == "1"


async def approve_chat_join_request(bot: Bot, chat_id: int, user_id: int) -> Dict[str, Any]:
    """
    Одобряет запрос на вступление в группу
    Возвращает результат операции и ссылку на группу
    """
    result = {"success": False, "message": "", "group_link": None}

    try:
        # Пытаемся одобрить запрос на вступление
        await bot.approve_chat_join_request(
            chat_id=chat_id,
            user_id=user_id
        )
        result["success"] = True
        result["message"] = "Капча пройдена успешно! Ваш запрос на вступление в группу одобрен."

        # Получаем ссылку на группу
        try:
            chat = await bot.get_chat(chat_id)
            if chat.username:
                result["group_link"] = f"https://t.me/{chat.username}"
            else:
                # Для приватных групп создаем приглашение
                invite_link = await bot.create_chat_invite_link(chat_id=chat_id)
                result["group_link"] = invite_link.invite_link
        except Exception as e:
            logger.error(f"Ошибка при создании ссылки на группу: {e}")
            result["message"] += "\nНо не удалось создать ссылку для группы."

    except Exception as e:
        logger.error(f"Ошибка при одобрении запроса на вступление: {e}")
        result["message"] = f"Капча пройдена успешно, но не удалось автоматически добавить вас в группу: {str(e)}"

        # Пытаемся получить ссылку на группу даже при ошибке
        try:
            chat = await bot.get_chat(chat_id)
            if chat.username:
                result["group_link"] = f"https://t.me/{chat.username}"
            else:
                invite_link = await bot.create_chat_invite_link(chat_id=chat_id)
                result["group_link"] = invite_link.invite_link
        except Exception as e:
            logger.error(f"Ошибка при создании ссылки на группу после неудачного одобрения: {e}")

    return result


async def get_group_display_name(group_name: str) -> str:
    """
    Получает отображаемое имя группы из Redis или форматирует из group_name
    """
    group_display_name = await redis.get(f"group_display_name:{group_name}")

    if not group_display_name:
        # Форматируем group_name, если нет сохраненного имени
        group_display_name = group_name.replace('_', ' ').title()
    else:
        # Убеждаемся, что отображаемое имя - строка
        group_display_name = str(group_display_name)

    return group_display_name