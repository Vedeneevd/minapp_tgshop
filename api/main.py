from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from bot.database import get_brands, get_products_by_brand

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
)

@app.get("/api/brands")
async def api_brands():
    brands = await get_brands()
    return [{"id": b.id, "name": b.name} for b in brands]

@app.get("/api/products")
async def api_products(brand_id: int):
    products = await get_products_by_brand(brand_id)
    return [
        {
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "photo_url": p.photo_url
        } for p in products
    ]