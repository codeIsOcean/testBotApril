import random
import asyncio
from datetime import datetime, timedelta
import logging
import re

from aiogram import Router, F
from aiogram.types import ChatJoinRequest, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.chat_permissions import ChatPermissions
from aiogram.fsm.context import FSMContext

from bot.services.redis_conn import redis
from bot.utils.logger import TelegramLogHandler

# Настраиваем логгер
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(TelegramLogHandler())

captcha_handler = Router()


@captcha_handler.chat_join_request()
async def handle_join_request(request: ChatJoinRequest):
    """Обработчик запросов на вступление в группу с капчей"""
    try:
        chat_id = request.chat.id
        user_id = request.from_user.id

        # Проверяем, включена ли капча для этой группы
        captcha_enabled = await redis.hget(f"group:{chat_id}", "captcha_enabled")

        if not captcha_enabled or captcha_enabled != "1":
            logger.info(f"Капча для группы {chat_id} отключена, пропускаем проверку")
            return

        # Получаем информацию о чате
        chat = await request.bot.get_chat(chat_id)
        chat_link = chat.username if chat.username else f"t.me/+{chat.invite_link.split('/')[-1]}"

        # Удаляем предыдущие сообщения с капчей для этого пользователя
        prev_msg_id_key = f"captcha_msg:{chat_id}:{user_id}"
        prev_msg_id = await redis.get(prev_msg_id_key)
        if prev_msg_id:
            try:
                await request.bot.delete_message(user_id, int(prev_msg_id))
            except Exception as e:
                logger.error(f"Ошибка при удалении предыдущего сообщения капчи: {str(e)}")

        # Генерируем математическую задачу
        num1 = random.randint(1, 20)
        num2 = random.randint(1, 20)
        operation = random.choice(['+', '-', '*'])

        if operation == '+':
            answer = num1 + num2
        elif operation == '-':
            # Для вычитания убедимся, что ответ будет положительным
            if num1 < num2:
                num1, num2 = num2, num1
            answer = num1 - num2
        else:  # operation == '*'
            # Для умножения используем меньшие числа
            num1 = random.randint(1, 10)
            num2 = random.randint(1, 10)
            answer = num1 * num2

        # Генерируем варианты ответов
        wrong_answers = [
            answer + random.randint(1, 5),
            answer - random.randint(1, 5),
            answer + random.randint(6, 10)
        ]

        if 0 in wrong_answers:
            wrong_answers[wrong_answers.index(0)] = answer + 11

        options = wrong_answers + [answer]
        random.shuffle(options)

        # Сохраняем правильный ответ в Redis
        captcha_key = f"captcha:{chat_id}:{user_id}"
        await redis.set(captcha_key, str(answer), ex=70)  # хранить 70 секунд (тайм-аут капчи)

        # Создаем клавиатуру с вариантами ответов
        keyboard = []
        row = []
        for i, option in enumerate(options):
            if i > 0 and i % 2 == 0:
                keyboard.append(row)
                row = []
            callback_data = f"captcha_{user_id}_{chat_id}_{option}"
            row.append(InlineKeyboardButton(text=str(option), callback_data=callback_data))

        if row:
            keyboard.append(row)

        # Отправляем сообщение с капчей
        msg = await request.bot.send_message(
            user_id,
            f"👋 Привет, {request.from_user.first_name}!\n\n"
            f"Чтобы присоединиться к группе <a href='https://{chat_link}'>{request.chat.title}</a>, "
            f"пожалуйста, решите простую задачу:\n\n"
            f"<b>{num1} {operation} {num2} = ?</b>\n\n"
            f"Выберите правильный ответ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )

        # Сохраняем ID сообщения с капчей
        await redis.set(prev_msg_id_key, str(msg.message_id), ex=70)

        logger.info(f"Отправлена капча пользователю {user_id} для входа в группу {chat_id}")

        # Установим таймаут для капчи (1 минута)
        asyncio.create_task(captcha_timeout(request, captcha_key, prev_msg_id_key))

    except Exception as e:
        logger.error(f"Ошибка при обработке запроса на вступление: {str(e)}")


@captcha_handler.callback_query(F.data.startswith("captcha_"))
async def process_captcha_answer(callback: CallbackQuery):
    """Обработчик ответов на капчу"""
    try:
        parts = callback.data.split("_")
        if len(parts) != 4:
            await callback.answer("Неверный формат данных", show_alert=True)
            return

        _, user_id, chat_id, answer = parts
        user_id, chat_id, answer = int(user_id), int(chat_id), int(answer)

        # Проверяем, что callback пришел от того же пользователя
        if callback.from_user.id != user_id:
            await callback.answer("Эта капча не для вас", show_alert=True)
            return

        captcha_key = f"captcha:{chat_id}:{user_id}"
        prev_msg_id_key = f"captcha_msg:{chat_id}:{user_id}"

        correct_answer_str = await redis.get(captcha_key)
        if correct_answer_str is None:
            await callback.answer("Время решения капчи истекло. Отправьте запрос на вступление еще раз.",
                                  show_alert=True)
            return
        correct_answer = int(correct_answer_str)

        if answer == correct_answer:
            # Правильный ответ
            await callback.answer("✅ Правильно! Ваш запрос будет принят.", show_alert=True)

            # Одобряем запрос на вступление
            try:
                bot = callback.bot
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
                logger.info(f"Пользователь {user_id} успешно прошел капчу и добавлен в группу {chat_id}")

                # Получаем название чата
                chat = await bot.get_chat(chat_id)

                # Обновляем сообщение с капчей
                success_msg = await callback.message.edit_text(
                    f"✅ Вы успешно прошли проверку и присоединились к группе {chat.title}!",
                    reply_markup=None
                )

                # Удаляем сообщение через 5 секунд
                asyncio.create_task(delete_message_after_delay(bot, user_id, success_msg.message_id, 5))

                # Уведомляем в группу
                user_mention = f"@{callback.from_user.username}" if callback.from_user.username else f"Пользователь {callback.from_user.first_name}"
                group_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ {user_mention} успешно прошел капчу и присоединился к группе!"
                )

                # Удаляем уведомление в группе через 30 секунд
                asyncio.create_task(delete_message_after_delay(bot, chat_id, group_msg.message_id, 30))

                # Удаляем ключи из Redis
                await redis.delete(captcha_key)
                await redis.delete(prev_msg_id_key)
            except Exception as e:
                logger.error(f"Ошибка при одобрении запроса: {str(e)}")
                error_msg = await callback.message.answer("❌ Произошла ошибка при обработке запроса. Попробуйте позже.")
                asyncio.create_task(delete_message_after_delay(bot, user_id, error_msg.message_id, 5))
        else:
            # если ответ не правилен, можно начать заново
            await callback.answer("❌ Неправильно. Попробуйте заново отправить запрос на вступление.", show_alert=True)

            # Обновляем сообщение с капчей
            error_msg = await callback.message.edit_text(
                "❌ Неправильный ответ. Пожалуйста, отправьте запрос на вступление снова.",
                reply_markup=None
            )

            # Удаляем сообщение через 5 секунд
            asyncio.create_task(delete_message_after_delay(callback.bot, user_id, error_msg.message_id, 5))

            # Удаляем ключи из Redis
            await redis.delete(captcha_key)
            await redis.delete(prev_msg_id_key)
    except Exception as e:
        logger.error(f"Ошибка при обработке ответа на капчу: {str(e)}")
        await callback.answer("Произошла ошибка", show_alert=True)


async def captcha_timeout(request: ChatJoinRequest, captcha_key: str, prev_msg_id_key: str):
    """Обработка таймаута капчи"""
    await asyncio.sleep(60)  # 1 минута на решение

    # Проверяем, есть ли еще ключ в Redis
    if await redis.exists(captcha_key):
        try:
            # Получаем ID предыдущего сообщения
            prev_msg_id = await redis.get(prev_msg_id_key)

            # Удаляем предыдущее сообщение с капчей
            if prev_msg_id:
                try:
                    await request.bot.delete_message(request.from_user.id, int(prev_msg_id))
                except Exception as e:
                    logger.error(f"Ошибка при удалении предыдущего сообщения капчи: {str(e)}")

            # Отправляем сообщение о истечении времени
            timeout_msg = await request.bot.send_message(
                request.from_user.id,
                "⏰ Время на решение капчи истекло. Вы можете повторно отправить запрос на вступление в группу."
            )

            # Удаляем сообщение через 5 секунд
            asyncio.create_task(
                delete_message_after_delay(request.bot, request.from_user.id, timeout_msg.message_id, 5))

            logger.info(
                f"Пользователь {request.from_user.id} не решил каптчу вовремя (таймаут) для группы {request.chat.id}")

            # Удаляем ключи из Redis
            await redis.delete(captcha_key)
            await redis.delete(prev_msg_id_key)
        except Exception as e:
            logger.error(f"Ошибка при обработке таймаута капчи: {str(e)}")


async def delete_message_after_delay(bot, chat_id, message_id, delay_seconds):
    """Удаляет сообщение после указанной задержки"""
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения {message_id} в чате {chat_id}: {str(e)}")