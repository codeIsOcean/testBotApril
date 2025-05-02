from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from bot.database.models import User, Group
from bot.config import DATABASE_URL

# тут файл для движка и сессии
print("DEBUG: DATABASE_URL =", DATABASE_URL)

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)


# функция добавления или проверки пользователя в бд при нажатий команды старт
async def get_or_create_user(session: AsyncSession, user_id: int, full_name: str, username: str):
    stmt = select(User).where(User.user_id == user_id)
    result = await session.execute(stmt)
    existing_user = result.scalar_one_or_none()

    if not existing_user:
        user = User(user_id=user_id, full_name=full_name, username=username)
        session.add(user)
        await session.commit()
        return user

    return existing_user


# функция сохранения группы в бд
async def save_group(session: AsyncSession, chat_id, title, creator: User = None):
    result = await session.execute(select(Group).where(Group.chat_id == chat_id))
    group = result.scalar_one_or_none()
    if group is None:
        group = Group(chat_id=chat_id, title=title, creator=creator)
        session.add(group)
        await session.commit()
    return group
