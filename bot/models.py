from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql.schema import ForeignKeyConstraint

Base = declarative_base()

class Brand(Base):
    __tablename__ = 'brands'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    categories = relationship("Category", back_populates="brand", cascade="all, delete-orphan")

class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    brand_id = Column(Integer, ForeignKey('brands.id', ondelete="CASCADE"), nullable=False)
    brand = relationship("Brand", back_populates="categories")
    products = relationship("Product", back_populates="category", cascade="all, delete-orphan")

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)
    photo_url = Column(String(500))
    description = Column(String(500))
    category_id = Column(Integer, ForeignKey('categories.id', ondelete="CASCADE"), nullable=False)
    category = relationship("Category", back_populates="products")