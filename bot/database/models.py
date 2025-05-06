from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, DateTime, Boolean, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime


Base = declarative_base()


# 👤 Пользователи
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, unique=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)

    groups = relationship("Group", back_populates="creator")  # 1 ко многим — создатель групп
    user_groups = relationship("UserGroup", back_populates="user", cascade="all, delete")


# 🏠 Группы
class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True)
    title = Column(String, nullable=False)
    creator_user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    creator = relationship("User", back_populates="groups")
    user_groups = relationship("UserGroup", back_populates="group", cascade="all, delete")


# 🔁 Связь многие-ко-многим между User и Group
class UserGroup(Base):
    __tablename__ = "user_group"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    group_id = Column(BigInteger, ForeignKey("groups.chat_id", ondelete="CASCADE"), nullable=False, index=True)

    user = relationship("User", back_populates="user_groups")
    group = relationship("Group", back_populates="user_groups")

    __table_args__ = (
        Index('ix_user_group_unique', 'user_id', 'group_id', unique=True),
    )


# ⚙️ Настройки капчи
class CaptchaSettings(Base):
    __tablename__ = "captcha_settings"

    group_id = Column(BigInteger, ForeignKey("groups.chat_id"), primary_key=True)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("Group")


# ✅ Ответы на капчу
class CaptchaAnswer(Base):
    __tablename__ = "captcha_answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id"), index=True)
    answer = Column(String(50))
    expires_at = Column(DateTime, index=True)

    __table_args__ = (
        Index('idx_user_chat', 'user_id', 'chat_id'),
    )


# 💬 Сообщения с капчей
class CaptchaMessageId(Base):
    __tablename__ = "captcha_message_ids"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True)
    chat_id = Column(BigInteger, ForeignKey("groups.chat_id"), index=True)
    message_id = Column(BigInteger)
    expires_at = Column(DateTime, index=True)

    __table_args__ = (
        Index('idx_user_chat_msg', 'user_id', 'chat_id'),
    )


class TimeoutMessageId(Base):
    __tablename__ = "timeout_messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    chat_id = Column(BigInteger)
    message_id = Column(BigInteger)
    created_at = Column(DateTime, default=datetime.utcnow)


class GroupUsers(Base):
    __tablename__ = 'group_users'

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    joined_at = Column(DateTime, default=datetime.now)
    last_activity = Column(DateTime, default=datetime.now)

    # Уникальный индекс для пары user_id и chat_id
    __table_args__ = (
        UniqueConstraint('user_id', 'chat_id', name='uix_user_chat'),
    )
