from aiogram import Router
from .cmd_start_handler import cmd_start_router

start_router = Router()

start_router.include_router(cmd_start_router)