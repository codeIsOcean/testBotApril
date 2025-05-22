from aiogram import Router
from .new_member_requested_mute import new_member_requested_handler
from .photo_del_handler import photo_del_router

moderation_router = Router()

moderation_router.include_router(new_member_requested_handler)
moderation_router.include_router(photo_del_router)