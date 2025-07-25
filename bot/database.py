from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from models import Base

DATABASE_URL = "postgresql+asyncpg://tguser:123@localhost/tgshop"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    """Инициализация базы данных с созданием всех таблиц"""
    async with engine.begin() as conn:
        print("Создание таблиц в базе данных...")
        await conn.run_sync(Base.metadata.create_all)
        print("Все таблицы успешно созданы")

async def get_db():
    """Генератор сессий для зависимостей"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()