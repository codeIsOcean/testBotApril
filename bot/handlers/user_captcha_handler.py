import random
import asyncio
from datetime import datetime, timedelta
import logging
import re

from aiogram import Router, F
from aiogram.types import ChatJoinRequest, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.chat_permissions import ChatPermissions
from aiogram.fsm.context import FSMContext

from sqlalchemy.future import select
from sqlalchemy import delete, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import CaptchaSettings, CaptchaMessageId, CaptchaAnswer, TimeoutMessageId
from bot.database.session import get_session
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

        # 🧹 Удаляем сообщение таймаута (если было)
        # Удаляем сообщение таймаута (если было)
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(TimeoutMessageId.message_id).where(
                        TimeoutMessageId.user_id == user_id,
                        TimeoutMessageId.chat_id == chat_id
                    )
                )
                timeout_msg_id = result.scalar_one_or_none()

                if timeout_msg_id:
                    await request.bot.delete_message(user_id, timeout_msg_id)
                    await session.execute(
                        delete(TimeoutMessageId).where(
                            TimeoutMessageId.user_id == user_id,
                            TimeoutMessageId.chat_id == chat_id
                        )
                    )
                    await session.commit()
                    print(f"✅ Удалено старое сообщение таймаута {timeout_msg_id}")
        except Exception as e:
            print(f"❌ Ошибка при удалении таймаут-сообщения: {e}")
            print(f"🧹 Пытаемся удалить таймаут сообщение для {user_id} в {chat_id}")

        # Проверяем, включена ли капча для этой группы
        async with get_session() as session:
            query = select(CaptchaSettings).where(
                CaptchaSettings.group_id == chat_id
            )
            result = await session.execute(query)
            captcha_settings = result.scalar_one_or_none()

            captcha_enabled = False
            if captcha_settings:
                captcha_enabled = captcha_settings.is_enabled
                print(
                    f"✅ Найдены настройки капчи для группы {chat_id}, статус: {'включено' if captcha_enabled else 'выключено'}")
            else:
                logger.warning(f"Настройки капчи для группы {chat_id} не найдены, создаем запись...")
                print(f"⚠️ Настройки капчи для группы {chat_id} не найдены, создаем запись...")

                # Создаем запись в базе данных с выключенной капчей по умолчанию
                insert_query = insert(CaptchaSettings).values(
                    group_id=chat_id,
                    is_enabled=False,
                    created_at=datetime.now()
                )
                await session.execute(insert_query)
                await session.commit()
                # 🔄 Синхронизация с Redis
                await redis.hset(f"group:{chat_id}", "captcha_enabled", "0")
                print(f"✅ Создана запись настроек капчи для группы {chat_id}")

        if not captcha_enabled:
            logger.info(f"Капча для группы {chat_id} отключена, пропускаем проверку")
            print(f"⛔ Капча для группы {chat_id} отключена, пропускаем проверку")
            return

            # Получаем информацию о чате
        chat = await request.bot.get_chat(chat_id)
        # Более безопасный способ получения информации о чате
        chat_title = chat.title

        # Удаляем предыдущие сообщения с капчей для этого пользователя
        async with get_session() as session:
            query = select(CaptchaMessageId.message_id).where(
                CaptchaMessageId.user_id == user_id,
                CaptchaMessageId.chat_id == chat_id
            )
            result = await session.execute(query)
            prev_msg_id = result.scalar_one_or_none()

            if prev_msg_id:
                try:
                    await request.bot.delete_message(user_id, prev_msg_id)
                    print(f"✅ Удалено предыдущее сообщение капчи для пользователя {user_id}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении предыдущего сообщения капчи: {str(e)}")
                    print(f"❌ Ошибка при удалении предыдущего сообщения капчи: {str(e)}")

                # Удаляем запись из базы
                delete_query = delete(CaptchaMessageId).where(
                    CaptchaMessageId.user_id == user_id,
                    CaptchaMessageId.chat_id == chat_id
                )
                await session.execute(delete_query)
                await session.commit()
                print(f"✅ Удалена запись о предыдущем сообщении капчи из БД")

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

        # Сохраняем правильный ответ в базу данных
        expiration_time = datetime.now() + timedelta(seconds=70)
        async with get_session() as session:
            # Удаляем предыдущие ответы пользователя
            delete_query = delete(CaptchaAnswer).where(
                CaptchaAnswer.user_id == user_id,
                CaptchaAnswer.chat_id == chat_id
            )
            await session.execute(delete_query)

            # Добавляем новый ответ
            insert_query = insert(CaptchaAnswer).values(
                user_id=user_id,
                chat_id=chat_id,
                answer=str(answer),
                expires_at=expiration_time
            )
            await session.execute(insert_query)
            await session.commit()
            print(f"✅ Сохранен ответ {answer} для пользователя {user_id} в БД")

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
        # Получаем ссылку на группу
        try:
            chat_link = f"https://t.me/{chat.username}" if chat.username else (
                await request.bot.export_chat_invite_link(chat_id))
        except Exception as e:
            chat_link = ""
            print(f"⚠️ Не удалось получить ссылку на группу: {e}")

        group_name_clickable = f"<a href='{chat_link}'>{chat.title}</a>" if chat_link else f"<b>{chat.title}</b>"

        msg = await request.bot.send_message(
            user_id,
            f"👋 Привет, {request.from_user.first_name}!\n\n"
            f"Чтобы присоединиться к группе {group_name_clickable}, пожалуйста, решите простую задачу:\n\n"
            f"<b>{num1} {operation} {num2} = ?</b>\n\n"
            f"Выберите правильный ответ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

        print(f"✅ Отправлено сообщение с капчей пользователю {user_id}")

        # Сохраняем ID сообщения с капчей
        async with get_session() as session:
            insert_query = insert(CaptchaMessageId).values(
                user_id=user_id,
                chat_id=chat_id,
                message_id=msg.message_id,
                expires_at=expiration_time
            )
            await session.execute(insert_query)
            await session.commit()
            print(f"✅ Сохранен ID сообщения с капчей {msg.message_id} в БД")

        logger.info(f"Отправлена капча пользователю {user_id} для входа в группу {chat_id}")
        print(f"✅ Отправлена капча пользователю {user_id} для входа в группу {chat_id}")

        # Установим таймаут для капчи (1 минута)
        asyncio.create_task(captcha_timeout(request, user_id, chat_id))

    except Exception as e:

        logger.error(f"Ошибка при обработке запроса на вступление: {str(e)}")

        print(f"❌ Ошибка при обработке запроса на вступление: {str(e)}")


@captcha_handler.callback_query(F.data.startswith("captcha_"))
async def process_captcha_answer(callback: CallbackQuery):
    """Обработчик ответов на капчу"""
    try:
        parts = callback.data.split("_")
        if len(parts) != 4:
            await callback.answer("Неверный формат данных", show_alert=True)
            print(f"❌ Неверный формат данных в callback: {callback.data}")
            return

        _, user_id, chat_id, answer = parts
        user_id, chat_id, answer = int(user_id), int(chat_id), int(answer)

        # Проверяем, что callback пришел от того же пользователя
        if callback.from_user.id != user_id:
            await callback.answer("Эта капча не для вас", show_alert=True)
            print(f"⛔ Попытка другого пользователя {callback.from_user.id} ответить на капчу для {user_id}")
            return

        # Получаем правильный ответ из базы данных
        async with get_session() as session:
            query = select(CaptchaAnswer.answer).where(
                CaptchaAnswer.user_id == user_id,
                CaptchaAnswer.chat_id == chat_id,
                CaptchaAnswer.expires_at > datetime.now()
            )
            result = await session.execute(query)
            correct_answer_str = result.scalar_one_or_none()

        if correct_answer_str is None:
            await callback.answer("Время решения капчи истекло. Отправьте запрос на вступление еще раз.",
                                  show_alert=True)
            print(f"⏰ Время решения капчи истекло для пользователя {user_id}")
            return

        correct_answer = int(correct_answer_str)

        if answer == correct_answer:
            # Правильный ответ
            await callback.answer("✅ Правильно! Ваш запрос будет принят.", show_alert=True)
            print(f"✅ Пользователь {user_id} правильно ответил на капчу")

            # Одобряем запрос на вступление
            try:
                bot = callback.bot
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
                logger.info(f"Пользователь {user_id} успешно прошел капчу и добавлен в группу {chat_id}")
                print(f"✅ Пользователь {user_id} успешно добавлен в группу {chat_id}")

                # Получаем название чата
                chat = await bot.get_chat(chat_id)

                # Обновляем сообщение с капчей
                success_msg = await callback.message.edit_text(
                    f"✅ Вы успешно прошли проверку и присоединились к группе {chat.title}!",
                    reply_markup=None
                )
                print(f"✅ Сообщение с капчей для пользователя {user_id} обновлено")

                # Удаляем сообщение о таймауте (если есть)
                try:
                    async with get_session() as session:
                        timeout_query = select(TimeoutMessageId.message_id).where(
                            TimeoutMessageId.user_id == user_id,
                            TimeoutMessageId.chat_id == chat_id
                        )
                        timeout_result = await session.execute(timeout_query)
                        timeout_msg_id = timeout_result.scalar_one_or_none()

                        if timeout_msg_id:
                            await bot.delete_message(user_id, timeout_msg_id)
                            await session.execute(
                                delete(TimeoutMessageId).where(
                                    TimeoutMessageId.user_id == user_id,
                                    TimeoutMessageId.chat_id == chat_id
                                )
                            )
                            await session.commit()
                            print(f"✅ Удалено сообщение о таймауте {timeout_msg_id}")
                except Exception as e:
                    print(f"❌ Ошибка при удалении сообщения о таймауте: {e}")

                # Удаляем сообщение через 5 секунд
                asyncio.create_task(delete_message_after_delay(bot, user_id, success_msg.message_id, 10))

                # Получаем имя пользователя для кликабельной ссылки
                user_mention = f"<a href='tg://user?id={user_id}'>{callback.from_user.first_name}</a>"
                chat_title = chat.title

                # Получаем invite link (если публичная группа — используем username)
                try:
                    chat_link = f"https://t.me/{chat.username}" if chat.username else (
                        await bot.export_chat_invite_link(chat_id))
                except Exception as e:
                    chat_link = ""
                    print(f"⚠️ Не удалось получить ссылку на группу: {e}")

                user_msg = await bot.send_message(
                    chat_id=user_id,
                    text=f"✅ {user_mention} вы успешно прошли капчу и присоединились к группе "
                         f"<b><a href='{chat_link}'>{chat.title}</a></b>!",
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

                print(f"✅ Отправлено уведомление пользователю {user_id} о принятии в группу")

                # Удаляем уведомление в ЛС через 30 секунд
                asyncio.create_task(delete_message_after_delay(bot, user_id, user_msg.message_id, 30))

                # Удаляем данные из базы
                async with get_session() as session:
                    # Удаляем запись о сообщении с капчей
                    delete_msg_query = delete(CaptchaMessageId).where(
                        CaptchaMessageId.user_id == user_id,
                        CaptchaMessageId.chat_id == chat_id
                    )
                    await session.execute(delete_msg_query)

                    # Удаляем запись о правильном ответе
                    delete_answer_query = delete(CaptchaAnswer).where(
                        CaptchaAnswer.user_id == user_id,
                        CaptchaAnswer.chat_id == chat_id
                    )
                    await session.execute(delete_answer_query)
                    await session.commit()
                    print(f"✅ Данные о капче для пользователя {user_id} удалены из БД")

            except Exception as e:
                logger.error(f"Ошибка при одобрении запроса: {str(e)}")
                print(f"❌ Ошибка при одобрении запроса: {str(e)}")
                error_msg = await callback.message.answer("❌ Произошла ошибка при обработке запроса. Попробуйте позже.")
                asyncio.create_task(delete_message_after_delay(bot, user_id, error_msg.message_id, 5))
        else:
            # если ответ не правилен, можно начать заново
            await callback.answer("❌ Неправильно. Попробуйте заново отправить запрос на вступление.", show_alert=True)
            print(f"❌ Пользователь {user_id} неправильно ответил на капчу")

            # Обновляем сообщение с капчей
            try:
                # Получаем название чата
                chat = await callback.bot.get_chat(chat_id)
                chat_title = chat.title

                # Получаем ссылку на группу
                try:
                    chat_link = f"https://t.me/{chat.username}" if chat.username else (
                        await callback.bot.export_chat_invite_link(chat_id))
                except Exception as e:
                    chat_link = ""
                    print(f"⚠️ Не удалось получить ссылку на группу: {e}")

                group_name_clickable = f"<a href='{chat_link}'>{chat_title}</a>" if chat_link else f"<b>{chat_title}</b>"

                error_msg = await callback.message.edit_text(
                    f"❌ Неправильный ответ. Пожалуйста, отправьте запрос на вступление в группу {group_name_clickable} снова.",
                    reply_markup=None,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

                print(f"✅ Сообщение капчи обновлено для пользователя {user_id} (неправильный ответ)")
            except Exception as e:
                logger.error(f"Ошибка при обновлении сообщения с ошибкой капчи: {str(e)}")
                print(f"❌ Ошибка при обновлении сообщения с ошибкой капчи: {str(e)}")

            # Удаляем сообщение через 60 секунд
            asyncio.create_task(delete_message_after_delay(callback.bot, user_id, error_msg.message_id, 60))

            # Удаляем данные из базы
            async with get_session() as session:
                # Удаляем запись о сообщении с капчей
                delete_msg_query = delete(CaptchaMessageId).where(
                    CaptchaMessageId.user_id == user_id,
                    CaptchaMessageId.chat_id == chat_id
                )
                await session.execute(delete_msg_query)

                # Удаляем запись о правильном ответе
                delete_answer_query = delete(CaptchaAnswer).where(
                    CaptchaAnswer.user_id == user_id,
                    CaptchaAnswer.chat_id == chat_id
                )
                await session.execute(delete_answer_query)
                await session.commit()
                print(f"✅ Данные о капче для пользователя {user_id} удалены из БД (неправильный ответ)")

    except Exception as e:
        logger.error(f"Ошибка при обработке ответа на капчу: {str(e)}")
        print(f"❌ Ошибка при обработке ответа на капчу: {str(e)}")
        await callback.answer("Произошла ошибка", show_alert=True)


async def captcha_timeout(request: ChatJoinRequest, user_id: int, chat_id: int):
    """Обработка таймаута капчи"""
    await asyncio.sleep(60)  # 1 минута на решение

    # Проверяем, есть ли еще данные в БД
    async with get_session() as session:
        query = select(CaptchaAnswer).where(
            CaptchaAnswer.user_id == user_id,
            CaptchaAnswer.chat_id == chat_id,
            CaptchaAnswer.expires_at > datetime.now()
        )
        result = await session.execute(query)
        captcha_data = result.scalars().first()

    if captcha_data:
        try:
            # Получаем ID предыдущего сообщения
            async with get_session() as session:
                msg_query = select(CaptchaMessageId.message_id).where(
                    CaptchaMessageId.user_id == user_id,
                    CaptchaMessageId.chat_id == chat_id
                )
                result = await session.execute(msg_query)
                prev_msg_id = result.scalar_one_or_none()

                # Проверяем, что капча еще не решена
                captcha_check = await session.execute(
                    select(CaptchaAnswer).where(
                        CaptchaAnswer.user_id == user_id,
                        CaptchaAnswer.chat_id == chat_id
                    )
                )
                if not captcha_check.scalars().first():
                    # Капча уже решена, выходим из функции
                    print(f"✅ Капча для пользователя {user_id} уже решена, отменяем таймаут")
                    return

            # Удаляем предыдущее сообщение с капчей
            if prev_msg_id:
                try:
                    await request.bot.delete_message(user_id, prev_msg_id)
                    print(f"✅ Удалено сообщение с капчей {prev_msg_id} (таймаут)")
                except Exception as e:
                    logger.error(f"Ошибка при удалении предыдущего сообщения капчи: {str(e)}")
                    print(f"❌ Ошибка при удалении предыдущего сообщения капчи: {str(e)}")

            # Отправляем сообщение о истечении времени
            # Получаем ссылку на группу
            try:
                chat = await request.bot.get_chat(chat_id)
                chat_link = f"https://t.me/{chat.username}" if chat.username else (
                    await request.bot.export_chat_invite_link(chat_id))
                group_clickable = f"<a href='{chat_link}'>{chat.title}</a>"
            except Exception as e:
                group_clickable = "<b>группу</b>"
                print(f"⚠️ Ошибка при создании ссылки на группу: {e}")

            timeout_msg = await request.bot.send_message(
                user_id,
                f"⏰ Время на решение капчи истекло.\n\n"
                f"Вы можете повторно отправить запрос на вступление в {group_clickable}.",
                parse_mode="HTML",
                disable_web_page_preview=True
            )

            print(f"✅ Отправлено сообщение о таймауте пользователю {user_id}")

            # Сохраняем ID таймаут-сообщения
            async with get_session() as session:
                # Удалим старое (если есть)
                await session.execute(
                    delete(TimeoutMessageId).where(
                        TimeoutMessageId.user_id == user_id,
                        TimeoutMessageId.chat_id == chat_id
                    )
                )
                await session.execute(
                    insert(TimeoutMessageId).values(
                        user_id=user_id,
                        chat_id=chat_id,
                        message_id=timeout_msg.message_id
                    )
                )
                await session.commit()

            logger.info(
                f"Пользователь {user_id} не решил каптчу вовремя (таймаут) для группы {chat_id}")
            print(f"⏰ Пользователь {user_id} не решил каптчу вовремя для группы {chat_id}")

            # Удаляем данные из базы
            async with get_session() as session:
                # Удаляем запись о сообщении с капчей
                delete_msg_query = delete(CaptchaMessageId).where(
                    CaptchaMessageId.user_id == user_id,
                    CaptchaMessageId.chat_id == chat_id
                )
                await session.execute(delete_msg_query)

                # Удаляем запись о правильном ответе
                delete_answer_query = delete(CaptchaAnswer).where(
                    CaptchaAnswer.user_id == user_id,
                    CaptchaAnswer.chat_id == chat_id
                )
                await session.execute(delete_answer_query)
                await session.commit()
                print(f"✅ Данные о капче для пользователя {user_id} удалены из БД (таймаут)")
        except Exception as e:
            logger.error(f"Ошибка при обработке таймаута капчи: {str(e)}")
            print(f"❌ Ошибка при обработке таймаута капчи: {str(e)}")


async def delete_message_after_delay(bot, chat_id, message_id, delay_seconds):
    """Удаляет сообщение после указанной задержки"""
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id, message_id)
        print(f"✅ Сообщение {message_id} удалено из чата {chat_id} после задержки {delay_seconds} сек")
    except Exception as e:
        try:
            logger.error(f"Ошибка при удалении сообщения {message_id} в чате {chat_id}: {str(e)}")
        except AttributeError:
            print(f"❌ Ошибка логгера при логировании ошибки удаления сообщения")
        print(f"❌ Ошибка при удалении сообщения {message_id} в чате {chat_id}: {str(e)}")
