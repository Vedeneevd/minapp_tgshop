from fastapi import APIRouter, UploadFile, File, Form
from models import Brand, Category, Product
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/admin/data")
async def get_admin_data():
    with Session() as session:
        brands = session.query(Brand).all()
        return {
            "brands": [{"id": b.id, "name": b.name} for b in brands]
        }


@router.post("/admin/add_product")
async def add_product(
        brand_id: int = Form(...),
        category_id: int = Form(...),
        name: str = Form(...),
        price: float = Form(...),
        photo: UploadFile = File(...),
        description: str = Form(...)
):
    # Сохраняем фото
    photo_url = f"/static/products/{photo.filename}"
    with open(f"/var/www/rshop{photo_url}", "wb") as buffer:
        buffer.write(await photo.read())

    # Добавляем в БД
    with Session() as session:
        product = Product(
            name=name,
            price=price,
            photo_url=photo_url,
            description=description,
            category_id=category_id
        )
        session.add(product)
        session.commit()

    return JSONResponse({"status": "success"})