from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from models import Base, Brand, Category, Product

DATABASE_URL = "postgresql+asyncpg://tguser:ваш_пароль@localhost/tgshop"

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_brands():
    async with async_session() as session:
        result = await session.execute(select(Brand))
        return result.scalars().all()

async def get_products_by_brand(brand_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Product).where(Product.brand_id == brand_id))
        return result.scalars().all()