from aiogram import Router
from .captcha import captcha_router
from .group_management import group_management_router
from .moderation import moderation_router
from .start import start_router


handlers_router = Router()

handlers_router.include_router(captcha_router)
handlers_router.include_router(group_management_router)
handlers_router.include_router(moderation_router)
handlers_router.include_router(start_router)








