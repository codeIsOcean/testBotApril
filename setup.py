from setuptools import setup, find_packages

setup(
    name="mybot",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        'aiogram>=3.0.0',
        'sqlalchemy>=2.0.0',
        'alembic>=1.10.0',
        'asyncpg>=0.27.0',
    ],
)