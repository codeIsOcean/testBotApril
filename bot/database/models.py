from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, unique=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)

    groups = relationship("Group", back_populates="creator")  # связь 1-ко-многим


# таблица хранения групп куда добавлен бот
class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True)
    title = Column(String, nullable=False)
    creator_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)

    creator = relationship("User", back_populates="groups")


