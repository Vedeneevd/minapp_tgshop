from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database import engine
from bot.models import Brand, Category, Product
import logging

logging.basicConfig(level=logging.INFO)
app = FastAPI()


@app.on_event("startup")
async def startup():
    logging.info("API started")


@app.get("/api/brands")
async def get_brands():
    try:
        async with AsyncSession(engine) as session:
            result = await session.execute(select(Brand))
            brands = result.scalars().all()
            return [{"id": b.id, "name": b.name} for b in brands]
    except Exception as e:
        logging.error(f"Database error: {e}")
        raise HTTPException(500, detail=str(e))


@app.get("/api/categories/{brand_id}")
async def get_categories(brand_id: int):
    try:
        async with AsyncSession(engine) as session:
            result = await session.execute(select(Category).where(Category.brand_id == brand_id))
            categories = result.scalars().all()
            return [{"id": c.id, "name": c.name} for c in categories]
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/api/products/{category_id}")
async def get_products(category_id: int):
    try:
        async with AsyncSession(engine) as session:
            result = await session.execute(select(Product).where(Product.category_id == category_id))
            products = result.scalars().all()
            return [{
                "id": p.id,
                "name": p.name,
                "price": p.price,
                "photo_url": p.photo_url,
                "description": p.description
            } for p in products]
    except Exception as e:
        raise HTTPException(500, detail=str(e))