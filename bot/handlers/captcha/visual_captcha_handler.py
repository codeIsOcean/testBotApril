# handlers/captcha/visual_captcha_handler.py
import asyncio
import logging
import traceback
from typing import Dict, Optional, Any, Union

from aiogram import Bot, Router, F
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import BaseFilter # имортируем для дип линк, чтобы фильтр реагировал только для него
from aiogram.types import (
    Message,
    CallbackQuery,
    ChatJoinRequest
)
from aiogram.utils.deep_linking import create_start_link

from bot.services.redis_conn import redis
from bot.services.visual_captcha_logic import (
    generate_visual_captcha,
    delete_message_after_delay,
    save_join_request,
    create_deeplink_for_captcha,
    get_captcha_keyboard,
    get_group_settings_keyboard,
    get_group_join_keyboard,
    save_captcha_data,
    get_captcha_data,
    set_rate_limit,
    check_rate_limit,
    get_rate_limit_time_left,
    check_admin_rights,
    set_visual_captcha_status,
    get_visual_captcha_status,
    approve_chat_join_request,
    get_group_display_name
)

# Создаем логгер
logger = logging.getLogger(__name__)

visual_captcha_handler_router = Router()


# Определение состояний FSM
class CaptchaStates(StatesGroup):
    waiting_for_captcha = State()


@visual_captcha_handler_router.chat_join_request()
async def handle_join_request(join_request: ChatJoinRequest):
    """
    Обрабатывает запрос на вступление в группу
    Отправляет пользователю сообщение с предложением пройти капчу
    """
    user = join_request.from_user
    chat = join_request.chat
    user_id = user.id
    chat_id = chat.id

    # Проверяем, активна ли визуальная капча для группы
    captcha_enabled = await get_visual_captcha_status(chat_id)
    if not captcha_enabled:
        logger.info(f"⛔ Визуальная капча не активирована в группе {chat_id}, выходим из handle_join_request")
        return

    # Определяем ID группы (используем username, если есть, иначе ID)
    group_id = chat.username or f"private_{chat.id}"

    # Сохраняем информацию о запросе на вступление
    await save_join_request(user_id, chat_id, group_id)

    # Создаем deep link для пользователя
    deep_link = await create_deeplink_for_captcha(join_request.bot, group_id)

    # Создаем клавиатуру с кнопкой для прохождения капчи
    keyboard = await get_captcha_keyboard(deep_link)

    try:
        # Удаляем предыдущие сообщения пользователю, если они были
        user_messages = await redis.get(f"user_messages:{user_id}")
        if user_messages:
            message_ids = user_messages.split(",")
            for msg_id in message_ids:
                try:
                    await join_request.bot.delete_message(chat_id=user_id, message_id=int(msg_id))
                except Exception as e:
                    # Логируем только если это не ошибка отсутствия сообщения
                    if "message to delete not found" not in str(e).lower():
                        logger.error(f"Ошибка при удалении сообщения {msg_id}: {str(e)}")

        # Формируем текст сообщения со ссылкой на группу, если возможно
        group_link = f"https://t.me/{chat.username}" if chat.username else None

        # Экранируем спецсимволы в названии группы для HTML
        group_title = chat.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        message_text = (
            f"Для вступления в группу <a href='{group_link}'>{group_title}</a> необходимо пройти проверку. "
            f"Нажмите на кнопку ниже:"
            if group_link else
            f"Для вступления в группу \"{group_title}\" необходимо пройти проверку. Нажмите на кнопку ниже:"
        )

        # Отправляем сообщение пользователю
        msg = await join_request.bot.send_message(
            user_id,
            message_text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"✅ Отправлено сообщение пользователю {user_id} о необходимости прохождения капчи")

        # Сохраняем ID сообщения для возможного удаления в будущем
        await redis.setex(f"user_messages:{user_id}", 3600, str(msg.message_id))

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке запроса на вступление: {e}")
        logger.debug(f"Подробная информация об ошибке: {traceback.format_exc()}")


@visual_captcha_handler_router.message(CommandStart(deep_link=True))
async def process_visual_captcha_deep_link(message: Message, bot: Bot, state: FSMContext):
    """
    Обрабатывает команду /start с deep_link для визуальной капчи
    Проверяет тип deep_link и запускает соответствующий процесс
    """
    # Получаем аргументы deep_link из команды /start
    deep_link_args = message.text.split()[1] if len(message.text.split()) > 1 else None
    logger.info(f"Активирован deep link с параметрами: {deep_link_args}")

    # Оставляем весь остальной код функции без изменений
    if deep_link_args.startswith("deep_link_"):
        # Удаляем предыдущие сообщения с капчами
        # ... Оставляем весь код как был ...
        # Удаляем предыдущие сообщения с капчами
        stored_messages = await state.get_data()
        message_ids = stored_messages.get("message_ids", [])
        for msg_id in message_ids:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
            except Exception as e:
                # Логируем только если это не ошибка отсутствия сообщения
                if "message to delete not found" not in str(e).lower():
                    logger.error(f"Ошибка при удалении сообщения {msg_id}: {str(e)}")

        # Также проверяем и удаляем сохраненные в Redis сообщения
        user_messages = await redis.get(f"user_messages:{message.from_user.id}")
        if user_messages:
            try:
                msg_ids = user_messages.split(",")
                for msg_id in msg_ids:
                    try:
                        await bot.delete_message(chat_id=message.chat.id, message_id=int(msg_id))
                    except Exception as e:
                        # Логируем только если это не ошибка отсутствия сообщения
                        if "message to delete not found" not in str(e).lower():
                            logger.error(f"Ошибка при удалении сообщения {msg_id}: {str(e)}")
                # Очищаем записи в Redis
                await redis.delete(f"user_messages:{message.from_user.id}")
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщений из Redis: {e}")

        # Извлекаем название группы из deep link
        group_name = deep_link_args.replace("deep_link_", "")
        logger.info(f"Extracted group name: {group_name}")

        # Генерируем капчу используя сервисную функцию
        captcha_answer, captcha_image = await generate_visual_captcha()
        logger.info(f"Сгенерирована капча с ответом: {captcha_answer}")

        # Сохраняем информацию о капче и группе в состоянии пользователя
        await state.update_data(
            captcha_answer=captcha_answer,
            group_name=group_name,
            attempts=0,
            message_ids=[]
        )

        # Сохраняем информацию в Redis с использованием сервисной функции
        await save_captcha_data(message.from_user.id, captcha_answer, group_name, 0)

        # Отправляем капчу пользователю
        captcha_msg = await message.answer_photo(
            photo=captcha_image,
            caption="Пожалуйста, введите символы, которые вы видите на изображении, или решите математическое "
                    "выражение для вступления в группу:"
        )

        # Сохраняем ID сообщения для последующего удаления
        message_ids = [captcha_msg.message_id]
        await state.update_data(message_ids=message_ids)

        # Запускаем таймер на удаление капчи через 2 минуты
        asyncio.create_task(delete_message_after_delay(bot, message.chat.id, captcha_msg.message_id, 120))

        # Устанавливаем состояние ожидания ответа на капчу
        await state.set_state(CaptchaStates.waiting_for_captcha)
    else:
        await message.answer("Неверная ссылка. Пожалуйста, используйте корректную ссылку для вступления в группу.")
        logger.warning(f"Неверный формат deep link: {deep_link_args}")


@visual_captcha_handler_router.message(CaptchaStates.waiting_for_captcha)
async def process_captcha_answer(message: Message, state: FSMContext):
    """
    Обрабатывает ответ пользователя на капчу
    Проверяет правильность ответа и выполняет соответствующие действия
    """
    user_id = message.from_user.id

    # Проверяем, не установлено ли ограничение на попытки
    if await check_rate_limit(user_id):
        time_left = await get_rate_limit_time_left(user_id)
        limit_msg = await message.answer(f"Пожалуйста, подождите {time_left} секунд перед следующей попыткой")
        # Удаляем сообщение через 5 секунд
        asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, limit_msg.message_id, 5))
        return

    # Получаем данные из состояния
    data = await state.get_data()
    captcha_answer = data.get("captcha_answer")
    group_name = data.get("group_name")
    attempts = data.get("attempts", 0)
    message_ids = data.get("message_ids", [])

    # Добавляем текущее сообщение в список для удаления
    message_ids.append(message.message_id)
    await state.update_data(message_ids=message_ids)

    # Если данных нет в состоянии, пытаемся получить из Redis
    if not captcha_answer or not group_name:
        captcha_data = await get_captcha_data(message.from_user.id)
        if captcha_data:
            captcha_answer = captcha_data["captcha_answer"]
            group_name = captcha_data["group_name"]
            attempts = captcha_data["attempts"]
        else:
            no_captcha_msg = await message.answer("Время сессии истекло. Пожалуйста, начните процесс заново.")
            message_ids.append(no_captcha_msg.message_id)
            await state.update_data(message_ids=message_ids)
            # Удаляем сообщение через 5 секунд
            asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, no_captcha_msg.message_id, 5))
            await state.clear()
            return
    # Проверяем количество попыток
    if attempts >= 3:
        too_many_attempts_msg = await message.answer(
            "Превышено количество попыток. Пожалуйста, повторите через 30 секунд.")
        message_ids.append(too_many_attempts_msg.message_id)
        await state.update_data(message_ids=message_ids)
        # Удаляем сообщение через 5 секунд
        asyncio.create_task(
            delete_message_after_delay(message.bot, message.chat.id, too_many_attempts_msg.message_id, 5))
        # Удаляем сообщение через 5 секунд
        asyncio.create_task(
            delete_message_after_delay(message.bot, message.chat.id, too_many_attempts_msg.message_id, 5))
        await redis.delete(f"captcha:{message.from_user.id}")
        # Устанавливаем временное ограничение на 60 секунд
        await set_rate_limit(message.from_user.id, 60)
        # Проверяем, сколько осталось ждать
        time_left = await get_rate_limit_time_left(message.from_user.id)
        await message.answer(f"Пожалуйста, подождите {time_left} секунд перед следующей попыткой")
        await state.clear()
    # Проверяем ответ пользователя
    try:
        user_answer = message.text.strip().upper()  # Преобразуем к верхнему регистру для текстовых капч
        if user_answer == str(captcha_answer).upper():  # Также преобразуем ответ к верхнему регистру
            # Капча решена правильно

            # Удаляем данные капчи из Redis
            await redis.delete(f"captcha:{message.from_user.id}")

            # Удаляем все предыдущие сообщения с капчами через 5 секунд
            for msg_id in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, msg_id, 5))

            # Определяем ID чата (группы)
            chat_id = None
            if group_name.startswith("private_"):
                chat_id = group_name.replace("private_", "")
            elif await redis.exists(f"join_request:{message.from_user.id}:{group_name}"):
                chat_id = await redis.get(f"join_request:{message.from_user.id}:{group_name}")

            # Если есть активный запрос на вступление, одобряем его
            if chat_id:
                # Одобряем запрос на вступление и получаем результат
                result = await approve_chat_join_request(
                    message.bot,
                    chat_id,
                    message.from_user.id
                )

                if result["success"]:
                    # Получаем отображаемое имя группы
                    group_display_name = await get_group_display_name(group_name)

                    # Создаем клавиатуру с кнопкой для перехода в группу
                    keyboard = await get_group_join_keyboard(
                        result["group_link"],
                        group_display_name
                    )

                    # Отправляем сообщение об успешном вступлении
                    await message.answer(
                        result["message"],
                        reply_markup=keyboard
                    )
                else:
                    # Если произошла ошибка при одобрении запроса
                    await message.answer(result["message"])

                    # Если есть ссылка на группу, предлагаем перейти вручную
                    if result["group_link"]:
                        keyboard = await get_group_join_keyboard(result["group_link"])
                        await message.answer(
                            "Используйте эту ссылку для присоединения:",
                            reply_markup=keyboard
                        )

                logger.info(
                    f"Одобрен запрос на вступление для пользователя {message.from_user.id} в группу {group_name}")
            else:
                # Если запрос не найден, просто отправляем ссылку на группу
                if group_name.startswith("private_"):
                    error_msg = await message.answer(
                        "Ваш запрос на вступление истек. Попробуйте снова запросить вступление в группу.")
                    message_ids.append(error_msg.message_id)
                    await state.update_data(message_ids=message_ids)
                else:
                    group_link = f"https://t.me/{group_name}"
                    keyboard = await get_group_join_keyboard(group_link)
                    await message.answer(
                        "Капча пройдена успешно! Используйте эту ссылку для вступления:",
                        reply_markup=keyboard
                    )

            # Очищаем состояние
            await state.clear()
        else:
            # Если ответ неправильный, увеличиваем счетчик попыток
            attempts += 1

            # Обновляем данные в состоянии
            await state.update_data(attempts=attempts)

            if attempts >= 3:
                # Проверяем, является ли группа приватной
                if group_name.startswith("private_"):
                    too_many_attempts_msg = await message.answer(
                        f"Превышено количество попыток. Пожалуйста, начните процесс заново.",
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                else:
                    too_many_attempts_msg = await message.answer(
                        f"Превышено количество попыток. Пожалуйста, начните процесс заново. "
                        f"Отправьте запрос в группу: "
                        f"<a href='https://t.me/{group_name}'>{group_name}</a>",
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                message_ids.append(too_many_attempts_msg.message_id)
                await state.update_data(message_ids=message_ids)

                # Удаляем все сообщения через 90 секунд
                for msg_id in message_ids:
                    asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, msg_id, 90))

                # Очищаем состояние и Redis-ключи
                await redis.delete(f"captcha:{message.from_user.id}")
                await set_rate_limit(message.from_user.id, 60)

                # Отправляем ссылку на группу повторно
                if await redis.exists(f"join_request:{message.from_user.id}:{group_name}"):
                    chat_id = await redis.get(f"join_request:{message.from_user.id}:{group_name}")
                    if group_name.startswith("private_"):
                        try:
                            invite_link = await message.bot.create_chat_invite_link(chat_id=chat_id)
                            group_link = invite_link.invite_link
                            keyboard = await get_group_join_keyboard(group_link, "группе")
                            final_msg = await message.answer(
                                "Если вы всё ещё хотите вступить в группу, используйте эту ссылку:",
                                reply_markup=keyboard
                            )
                            # Сохраняем ID этого сообщения в Redis для возможного удаления
                            await redis.setex(
                                f"user_messages:{message.from_user.id}",
                                3600,
                                str(final_msg.message_id)
                            )
                        except Exception as e:
                            logger.error(f"Ошибка при создании ссылки-приглашения: {e}")

                await state.clear()
                return

            # Генерируем новую капчу для следующей попытки
            new_captcha_answer, new_captcha_image = await generate_visual_captcha()

            # Обновляем информацию о капче в состоянии
            await state.update_data(captcha_answer=new_captcha_answer)

            # Обновляем данные в Redis с новым ответом на капчу
            await save_captcha_data(message.from_user.id, new_captcha_answer, group_name, attempts)

            # Удаляем предыдущие сообщения с капчами через 5 секунд
            for msg_id in message_ids:
                asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, msg_id, 5))

            # Очищаем список сообщений для удаления
            message_ids = []

            # Отправляем новую капчу
            wrong_answer_msg = await message.answer(f"Неверный ответ. Осталось попыток: {3 - attempts}")
            message_ids.append(wrong_answer_msg.message_id)

            captcha_msg = await message.answer_photo(
                photo=new_captcha_image,
                caption="Пожалуйста, введите символы, которые вы видите на изображении, или решите математическое "
                        "выражение:"
            )
            message_ids.append(captcha_msg.message_id)
            await state.update_data(message_ids=message_ids)

            # Запускаем таймер на удаление капчи через 2 минуты
            asyncio.create_task(delete_message_after_delay(message.bot, message.chat.id, captcha_msg.message_id, 120))

            # Получаем отображаемое имя группы для уведомления
            group_display_name = await get_group_display_name(group_name)
            group_link = f"https://t.me/{group_name}" if not group_name.startswith("private_") else None

            # Запускаем задачу для отправки напоминания через 10 секунд
            async def send_reminder():
                try:
                    logger.info(f"🕒 Запланировано напоминание для пользователя {user_id} через 10 секунд")
                    await asyncio.sleep(180)
                    logger.info(f"⏰ Время напоминания для пользователя {user_id} наступило")

                    # Проверяем, все ещё актуальна ли капча (если пользователь её не решил)
                    captcha_data = await get_captcha_data(user_id)
                    logger.info(f"📊 Данные капчи для пользователя {user_id}: {captcha_data}")

                    # Капча актуальна только если данные о капче существуют в Redis
                    if captcha_data:
                        logger.info(f"✅ Капча всё ещё актуальна для пользователя {user_id}")
                        reminder_text = f"Вы не ответили на капчу для входа в группу"
                        if group_link:
                            reminder_text += f" <a href='{group_link}'>{group_display_name}</a>"
                        reminder_text += ". Вы можете заново отправить запрос в группу, чтобы получить новую капчу."
                        logger.info(f"📝 Подготовлено сообщение: {reminder_text}")

                        try:
                            logger.info(f"🚀 Отправка напоминания пользователю {user_id} в чат {message.chat.id}")
                            reminder_msg = await message.bot.send_message(
                                message.chat.id,
                                reminder_text,
                                parse_mode="HTML",
                                disable_web_page_preview=True
                            )
                            logger.info(f"✅ Напоминание успешно отправлено, message_id={reminder_msg.message_id}")
                            # Удаляем напоминание через 3 минуты
                            asyncio.create_task(
                                delete_message_after_delay(message.bot, message.chat.id, reminder_msg.message_id, 180))
                        except Exception as e:
                            logger.error(f"❌ Ошибка при отправке напоминания: {e}")
                            logger.debug(f"Подробная информация об ошибке: {traceback.format_exc()}")
                    else:
                        logger.info(f"❎ Капча уже не актуальна для пользователя {user_id}, напоминание не отправлено")
                except Exception as e:
                    logger.error(f"❌ Критическая ошибка в функции напоминания: {e}")
                    logger.debug(f"Подробная трассировка: {traceback.format_exc()}")

            # Запускаем таймер напоминания сразу после отправки капчи
            logger.info(f"🔄 Запуск задачи отправки напоминания для пользователя {user_id}")
            # Сохраняем объект задачи в переменную, чтобы избежать сборки мусора
            reminder_task = asyncio.create_task(send_reminder())

    except Exception as e:
        error_msg = await message.answer("Пожалуйста, введите корректный ответ, соответствующий изображению.")
        message_ids.append(error_msg.message_id)
        await state.update_data(message_ids=message_ids)
        logger.error(f"Ошибка при обработке ответа на капчу: {str(e)}")
        # Добавляем расширенное логирование ошибки
        logger.debug(f"Подробная информация об ошибке: {traceback.format_exc()}")


@visual_captcha_handler_router.message(Command("check"))
async def cmd_check(message: Message):
    """
    Обработчик команды /check для проверки связи
    Отправляет тестовое сообщение пользователю
    """
    user_id = message.from_user.id
    try:
        await message.bot.send_message(user_id, "Проверка связи ✅")
        await message.answer("Сообщение успешно отправлено")
    except Exception as e:
        await message.answer(f"❌ Не могу отправить сообщение: {e}")


@visual_captcha_handler_router.message(Command("checkuser"))
async def cmd_check_user(message: Message):
    """
    Обработчик команды /checkuser для администраторов
    Проверяет возможность отправки сообщений указанному пользователю
    """
    # Проверка аргументов команды
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите ID или @username пользователя: /checkuser <id или @username>")
        return

    target = args[1]
    try:
        # Если указан ID (число)
        if target.isdigit():
            user_id = int(target)
        # Если указан username
        elif target.startswith("@"):
            username = target[1:]  # Убираем @ из начала
            # В этом случае нам нужно получить ID пользователя через API
            try:
                # Пытаемся найти чат по юзернейму
                chat = await message.bot.get_chat(username)
                user_id = chat.id
            except Exception as e:
                await message.answer(f"❌ Не удалось найти пользователя с юзернеймом {username}: {e}")
                return
        else:
            await message.answer("Неверный формат. Укажите ID (число) или @username")
            return

        # Пытаемся отправить сообщение пользователю
        await message.bot.send_message(user_id, "Проверка связи от администратора ✅")
        await message.answer(f"✅ Сообщение успешно отправлено пользователю (ID: {user_id})")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение пользователю: {e}")


@visual_captcha_handler_router.callback_query(F.data == "visual_captcha_settings")
async def visual_captcha_settings(callback_query: CallbackQuery, state: FSMContext):
    """
    Обработчик настроек визуальной капчи для групп
    Отображает текущее состояние и кнопки для изменения
    """
    user_id = callback_query.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")  # получаем id группы из Redis

    if not group_id:
        await callback_query.answer("❌ Не удалось определить группу. Попробуйте снова.", show_alert=True)
        return

    try:
        # Проверяем, является ли пользователь администратором
        is_admin = await check_admin_rights(callback_query.bot, int(group_id), user_id)

        if not is_admin:
            await callback_query.answer("У вас нет прав для изменения настроек группы", show_alert=True)
            return

        # Получаем текущее состояние настройки капчи
        captcha_enabled = await redis.get(f"visual_captcha_enabled:{group_id}") or "0"

        # Создаём клавиатуру для настроек
        keyboard = await get_group_settings_keyboard(group_id, captcha_enabled)

        await callback_query.message.edit_text(
            "Настройка визуальной капчи для новых участников.\n\n"
            "При включении этой функции, новые участники должны будут пройти проверку с визуальной капчей.",
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Ошибка при настройке визуальной капчи: {e}")
        await callback_query.answer("Произошла ошибка при загрузке настроек", show_alert=True)


@visual_captcha_handler_router.callback_query(F.data.startswith("set_visual_captcha:"))
async def set_visual_captcha(callback_query: CallbackQuery, state: FSMContext):
    """
    Обработчик для установки состояния визуальной капчи (включена/выключена)
    """
    data = callback_query.data.split(":")
    if len(data) < 3:
        await callback_query.answer("Некорректные данные", show_alert=True)
        return

    chat_id = data[1]
    enabled = data[2]

    # Проверяем права администратора
    try:
        user_id = callback_query.from_user.id
        is_admin = await check_admin_rights(callback_query.bot, int(chat_id), user_id)

        if not is_admin:
            await callback_query.answer("У вас нет прав для изменения настроек группы", show_alert=True)
            return

        # Устанавливаем статус капчи через сервисную функцию
        await set_visual_captcha_status(int(chat_id), enabled == "1")

        status_message = "Визуальная капча включена" if enabled == "1" else "Визуальная капча отключена"
        await callback_query.answer(status_message, show_alert=True)

        # Создаем клавиатуру для настроек
        keyboard = await get_group_settings_keyboard(chat_id, enabled)

        await callback_query.message.edit_text(
            "Настройка визуальной капчи для новых участников.\n\n"
            "При включении этой функции, новые участники должны будут пройти проверку с визуальной капчей.",
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Ошибка при установке настроек визуальной капчи: {e}")
        await callback_query.answer("Произошла ошибка при сохранении настроек", show_alert=True)


@visual_captcha_handler_router.callback_query(F.data == "captcha_settings")
async def back_to_main_captcha_settings(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик возврата к главным настройкам
    """
    user_id = callback.from_user.id
    group_id = await redis.hget(f"user:{user_id}", "group_id")

    if not group_id:
        await callback.answer("❌ Не удалось определить группу", show_alert=True)
        return

    await callback.answer()
    await callback.message.delete()

    # Импортируем метод для отображения основных настроек
    from bot.handlers.settings_inprivate_handler import show_settings_callback

    await show_settings_callback(callback)
