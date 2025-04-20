from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Awaitable, Dict, Any


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker):
        super().__init__()
        self.sessionmaker = sessionmaker  #сохраняем фабрику сесси

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
    ) -> Any:
        async with self.sessionmaker() as session:  # открываем сессию на каждый запрос/апдейт
            data["session"] = session  # передаем сессию в хендлер через context data
            return await handler(event, data)  # вызываем хендлер
