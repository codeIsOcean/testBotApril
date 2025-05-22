from aiogram import Router
from .math_captcha_handler import captcha_handler
from .visual_captcha_handler import visual_captcha_handler_router

captcha_router = Router()
#captcha_router.include_router(captcha_handler)
captcha_router.include_router(visual_captcha_handler_router)
