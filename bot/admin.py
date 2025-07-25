import os
import logging
from functools import wraps
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from models import Brand, Category, Product
from database import engine, AsyncSessionLocal

router = Router()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMINS = [6326719341]  # Ваш Telegram ID


# Состояния FSM
class AddStates(StatesGroup):
    brand_name = State()
    category_brand = State()
    category_name = State()
    product_brand = State()
    product_category = State()
    product_name = State()
    product_price = State()
    product_photo = State()
    product_description = State()


class EditStates(StatesGroup):
    category_id = State()
    product_id = State()
    field = State()
    new_value = State()


class DeleteStates(StatesGroup):
    category_id = State()
    product_id = State()
    brand_id = State()


# Улучшенный декоратор для проверки прав администратора
def admin_required(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        update = None
        for arg in args:
            if isinstance(arg, (Message, CallbackQuery)):
                update = arg
                break

        if not update:
            logger.error("Не удалось определить объект update")
            return

        user_id = update.from_user.id
        if user_id not in ADMINS:
            logger.warning(f"Попытка несанкционированного доступа: {user_id}")
            if isinstance(update, CallbackQuery):
                await update.answer("🚫 Доступ запрещён", show_alert=True)
            else:
                await update.answer("🚫 Доступ запрещён")
            return

        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Ошибка в обработчике: {e}", exc_info=True)
            if isinstance(update, CallbackQuery):
                await update.answer("❌ Произошла ошибка", show_alert=True)
            else:
                await update.answer("❌ Произошла ошибка")

    return wrapper


# Вспомогательные функции для работы с БД
async def get_brands(session: AsyncSession):
    result = await session.execute(select(Brand).order_by(Brand.name))
    return result.scalars().all()


async def get_categories_with_brands(session: AsyncSession):
    """Получаем категории с именами брендов"""
    result = await session.execute(
        select(Category, Brand)
        .join(Brand, Category.brand_id == Brand.id)
        .order_by(Brand.name, Category.name)
    )
    return result.all()


async def get_products_with_details(session: AsyncSession):
    result = await session.execute(
        select(Product, Category, Brand)
        .select_from(Product)
        .join(Category, Product.category_id == Category.id)
        .join(Brand, Category.brand_id == Brand.id)
        .order_by(Brand.name, Category.name, Product.name)
    )
    return result.all()


async def get_categories_by_brand(session: AsyncSession, brand_id: int):
    result = await session.execute(
        select(Category)
        .where(Category.brand_id == brand_id)
    )
    return result.scalars().all()


# ========================
# ГЛАВНОЕ МЕНЮ
# ========================

@router.message(Command("admin"))
@admin_required
async def admin_panel(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📦 Товары", callback_data="products_menu"),
        InlineKeyboardButton(text="🏷️ Бренды", callback_data="brands_menu"),
        InlineKeyboardButton(text="📂 Категории", callback_data="categories_menu")
    )
    builder.row(
        InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product_start"),
        InlineKeyboardButton(text="➕ Добавить бренд", callback_data="add_brand_start"),
        InlineKeyboardButton(text="➕ Добавить категорию", callback_data="add_category_start")
    )

    await message.answer(
        "👨‍💻 Админ-панель:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "admin_back")
@admin_required
async def back_to_admin(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    await admin_panel(callback.message)
    await callback.answer()


# ========================
# УПРАВЛЕНИЕ БРЕНДАМИ
# ========================

@router.callback_query(F.data == "brands_menu")
@admin_required
async def brands_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Список брендов", callback_data="view_brands"),
        InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_brand_select")
    )
    builder.row(
        InlineKeyboardButton(text="🗑️ Удалить", callback_data="delete_brand_select"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
    )
    await callback.message.edit_text("🏷️ Управление брендами:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "view_brands")
@admin_required
async def view_brands(callback: CallbackQuery):
    try:
        async with AsyncSessionLocal() as session:
            brands = await get_brands(session)

            if not brands:
                await callback.message.answer("ℹ️ Брендов пока нет")
                return await callback.answer()

            text = "🏷️ <b>Список брендов:</b>\n\n" + "\n".join(
                f"{i + 1}. {brand.name} (ID: {brand.id})"
                for i, brand in enumerate(brands)
            )
            await callback.message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка при получении брендов: {e}")
        await callback.message.answer("❌ Ошибка при получении списка брендов")
    finally:
        await callback.answer()


@router.callback_query(F.data == "add_brand_start")
@admin_required
async def add_brand_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название нового бренда:")
    await state.set_state(AddStates.brand_name)
    await callback.answer()


@router.message(AddStates.brand_name)
@admin_required
async def add_brand_finish(message: Message, state: FSMContext):
    async with AsyncSession(engine) as session:
        session.add(Brand(name=message.text))
        await session.commit()

    await message.answer(f"✅ Бренд {message.text} успешно добавлен!")
    await state.clear()
    await admin_panel(message)


@router.callback_query(F.data == "edit_brand_select")
@admin_required
async def select_brand_to_edit(callback: CallbackQuery):
    async with AsyncSession(engine) as session:
        brands = await get_brands(session)

        if not brands:
            await callback.message.answer("ℹ️ Брендов пока нет")
            return await callback.answer()

        builder = InlineKeyboardBuilder()
        for brand in brands:
            builder.button(
                text=f"{brand.name} (ID: {brand.id})",
                callback_data=f"edit_brand_{brand.id}"
            )
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="brands_menu"))

        await callback.message.edit_text(
            "Выберите бренд для редактирования:",
            reply_markup=builder.as_markup()
        )
        await callback.answer()


@router.callback_query(F.data.startswith("edit_brand_"))
@admin_required
async def edit_brand_name(callback: CallbackQuery, state: FSMContext):
    try:
        brand_id = int(callback.data.split("_")[2])
        await state.update_data(brand_id=brand_id)
        await callback.message.answer("Введите новое название бренда:")
        await state.set_state(EditStates.new_value)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await callback.answer("❌ Ошибка обработки команды")


@router.message(EditStates.new_value)
@admin_required
async def save_brand_name(message: Message, state: FSMContext):
    data = await state.get_data()

    async with AsyncSession(engine) as session:
        brand = await session.get(Brand, data.get('brand_id'))
        if not brand:
            await message.answer("❌ Бренд не найден")
            await state.clear()
            return

        old_name = brand.name
        brand.name = message.text
        await session.commit()
        await message.answer(f"✅ Бренд '{old_name}' переименован в '{message.text}'")

    await state.clear()
    await admin_panel(message)


# ========================
# УПРАВЛЕНИЕ КАТЕГОРИЯМИ (исправленная версия)
# ========================

class CategoryStates(StatesGroup):
    select_brand = State()  # Для выбора бренда при добавлении
    enter_name = State()  # Для ввода названия категории
    select_for_edit = State()  # Для выбора категории для редактирования
    edit_name = State()  # Для ввода нового названия
    select_for_delete = State()  # Для выбора категории для удаления
    confirm_delete = State()  # Для подтверждения удаления


@router.callback_query(F.data == "categories_menu")
@admin_required
async def categories_menu(callback: CallbackQuery):
    """Главное меню управления категориями"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Список категорий", callback_data="view_categories"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="add_category_start")
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать", callback_data="start_edit_category"),
        InlineKeyboardButton(text="🗑️ Удалить", callback_data="start_delete_category")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    await callback.message.edit_text(
        "📂 Управление категориями:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "view_categories")
@admin_required
async def view_categories(callback: CallbackQuery):
    """Просмотр списка всех категорий с брендами"""
    try:
        async with AsyncSessionLocal() as session:
            categories_with_brands = await get_categories_with_brands(session)

            if not categories_with_brands:
                await callback.message.answer("ℹ️ Категорий пока нет")
                return await callback.answer()

            text = "📂 <b>Список категорий:</b>\n\n" + "\n".join(
                f"{i + 1}. {brand.name} / {category.name} (ID: {category.id})"
                for i, (category, brand) in enumerate(categories_with_brands)
            )
            await callback.message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка при просмотре категорий: {e}")
        await callback.message.answer("❌ Ошибка при загрузке категорий")
    finally:
        await callback.answer()
    # ========================


# ДОБАВЛЕНИЕ КАТЕГОРИИ
# ========================

@router.callback_query(F.data == "add_category_start")
@admin_required
async def add_category_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса добавления категории - выбор бренда"""
    try:
        async with AsyncSessionLocal() as session:
            brands = await get_brands(session)

            if not brands:
                await callback.message.answer("ℹ️ Сначала добавьте бренды")
                await state.clear()
                return await callback.answer()

            builder = InlineKeyboardBuilder()
            for brand in brands:
                builder.button(
                    text=brand.name,
                    callback_data=f"select_brand_{brand.id}"
                )
            builder.adjust(2)
            builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="categories_menu"))

            await callback.message.edit_text(
                "Выберите бренд для новой категории:",
                reply_markup=builder.as_markup()
            )
            await state.set_state(CategoryStates.select_brand)
    except Exception as e:
        logger.error(f"Ошибка запуска добавления категории: {e}")
        await callback.message.answer("❌ Ошибка при запуске добавления категории")
        await state.clear()
    finally:
        await callback.answer()


@router.callback_query(CategoryStates.select_brand, F.data.startswith("select_brand_"))
@admin_required
async def select_brand_for_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора бренда для новой категории"""
    try:
        brand_id = int(callback.data.split("_")[2])
        await state.update_data(brand_id=brand_id)
        await callback.message.answer("Введите название новой категории:")
        await state.set_state(CategoryStates.enter_name)
    except Exception as e:
        logger.error(f"Ошибка выбора бренда: {e}")
        await callback.message.answer("❌ Ошибка выбора бренда")
        await state.clear()
    finally:
        await callback.answer()


@router.message(CategoryStates.enter_name)
@admin_required
async def save_new_category(message: Message, state: FSMContext):
    """Сохранение новой категории в базу данных"""
    try:
        data = await state.get_data()
        brand_id = data.get('brand_id')
        category_name = message.text.strip()

        if not brand_id:
            await message.answer("❌ Бренд не выбран")
            await state.clear()
            return

        if not category_name:
            await message.answer("❌ Название категории не может быть пустым")
            return

        async with AsyncSessionLocal() as session:
            # Проверяем существование бренда
            brand = await session.get(Brand, brand_id)
            if not brand:
                await message.answer("❌ Выбранный бренд не найден")
                await state.clear()
                return

            # Проверяем уникальность названия категории для этого бренда
            existing = await session.execute(
                select(Category)
                .where(and_(
                    Category.brand_id == brand_id,
                    func.lower(Category.name) == func.lower(category_name)
                ))
            )
            if existing.scalars().first():
                await message.answer("❌ У этого бренда уже есть категория с таким названием")
                return

            # Создаем новую категорию
            new_category = Category(
                name=category_name,
                brand_id=brand_id
            )
            session.add(new_category)
            await session.commit()

            await message.answer(
                f"✅ Новая категория успешно добавлена:\n"
                f"Бренд: {brand.name}\n"
                f"Категория: {category_name}"
            )
    except Exception as e:
        logger.error(f"Ошибка сохранения категории: {e}")
        await message.answer("❌ Ошибка при создании категории")
    finally:
        await state.clear()
        await admin_panel(message)


# ========================
# РЕДАКТИРОВАНИЕ КАТЕГОРИИ
# ========================

@router.callback_query(F.data == "start_edit_category")
@admin_required
async def start_edit_category(callback: CallbackQuery, state: FSMContext):
    """Начало процесса редактирования - выбор категории"""
    try:
        async with AsyncSessionLocal() as session:
            categories_with_brands = await get_categories_with_brands(session)

            if not categories_with_brands:
                await callback.answer("ℹ️ Категорий пока нет")
                return

            builder = InlineKeyboardBuilder()
            for category, brand in categories_with_brands:
                builder.button(
                    text=f"{brand.name} / {category.name} (ID: {category.id})",
                    callback_data=f"select_edit_{category.id}"
                )
            builder.adjust(1)
            builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="categories_menu"))

            await callback.message.edit_text(
                "Выберите категорию для редактирования:",
                reply_markup=builder.as_markup()
            )
            await state.set_state(CategoryStates.select_for_edit)
    except Exception as e:
        logger.error(f"Ошибка запуска редактирования: {e}")
        await callback.answer("❌ Ошибка запуска редактирования")
    finally:
        await callback.answer()


@router.callback_query(CategoryStates.select_for_edit, F.data.startswith("select_edit_"))
@admin_required
async def select_category_for_edit(callback: CallbackQuery, state: FSMContext):
    """Выбор конкретной категории для редактирования"""
    try:
        category_id = int(callback.data.split("_")[2])
        await state.update_data(category_id=category_id)
        await state.set_state(CategoryStates.edit_name)
        await callback.message.answer("Введите новое название категории:")
    except Exception as e:
        logger.error(f"Ошибка выбора категории: {e}")
        await callback.answer("❌ Ошибка выбора категории")
    finally:
        await callback.answer()


@router.message(CategoryStates.edit_name)
@admin_required
async def save_edited_category(message: Message, state: FSMContext):
    """Сохранение изменений в категории"""
    try:
        data = await state.get_data()
        category_id = data.get('category_id')
        new_name = message.text.strip()

        if not category_id:
            await message.answer("❌ Категория не выбрана")
            await state.clear()
            return

        if not new_name:
            await message.answer("❌ Название не может быть пустым")
            return

        async with AsyncSessionLocal() as session:
            category = await session.get(Category, category_id)
            if not category:
                await message.answer("❌ Категория не найдена")
                await state.clear()
                return

            old_name = category.name
            category.name = new_name
            await session.commit()

            await message.answer(
                f"✅ Категория успешно переименована:\n"
                f"Было: {old_name}\n"
                f"Стало: {new_name}"
            )
    except Exception as e:
        logger.error(f"Ошибка сохранения категории: {e}")
        await message.answer("❌ Ошибка при сохранении изменений")
    finally:
        await state.clear()
        await admin_panel(message)


# ========================
# УДАЛЕНИЕ КАТЕГОРИИ
# ========================

@router.callback_query(F.data == "start_delete_category")
@admin_required
async def start_delete_category(callback: CallbackQuery, state: FSMContext):
    """Начало процесса удаления - выбор категории"""
    try:
        async with AsyncSessionLocal() as session:
            categories_with_brands = await get_categories_with_brands(session)

            if not categories_with_brands:
                await callback.answer("ℹ️ Категорий пока нет")
                return

            builder = InlineKeyboardBuilder()
            for category, brand in categories_with_brands:
                builder.button(
                    text=f"{brand.name} / {category.name} (ID: {category.id})",
                    callback_data=f"select_delete_{category.id}"
                )
            builder.adjust(1)
            builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="categories_menu"))

            await callback.message.edit_text(
                "Выберите категорию для удаления:",
                reply_markup=builder.as_markup()
            )
            await state.set_state(CategoryStates.select_for_delete)
    except Exception as e:
        logger.error(f"Ошибка запуска удаления: {e}")
        await callback.message.answer("❌ Ошибка при запуске удаления")
    finally:
        await callback.answer()


@router.callback_query(CategoryStates.select_for_delete, F.data.startswith("select_delete_"))
@admin_required
async def select_category_to_delete(callback: CallbackQuery, state: FSMContext):
    """Подтверждение удаления выбранной категории"""
    try:
        category_id = int(callback.data.split("_")[2])
        await state.update_data(category_id=category_id)

        async with AsyncSessionLocal() as session:
            category = await session.get(Category, category_id)
            if not category:
                await callback.answer("❌ Категория не найдена", show_alert=True)
                return

            # Загружаем связанный бренд
            await session.refresh(category, ['brand'])

            # Проверяем наличие товаров в категории
            products_count = await session.execute(
                select(func.count(Product.id))
                .where(Product.category_id == category_id)
            )
            products_count = products_count.scalar()

            if products_count > 0:
                await callback.answer(
                    f"❌ В категории есть {products_count} товаров. Сначала удалите их.",
                    show_alert=True
                )
                return

            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete"),
                InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_delete")
            )

            await callback.message.edit_text(
                f"Вы уверены, что хотите удалить категорию?\n"
                f"Бренд: {category.brand.name}\n"
                f"Категория: {category.name} (ID: {category.id})",
                reply_markup=builder.as_markup()
            )
            await state.set_state(CategoryStates.confirm_delete)
    except Exception as e:
        logger.error(f"Ошибка выбора категории: {e}")
        await callback.answer("❌ Ошибка выбора категории")
    finally:
        await callback.answer()


@router.callback_query(CategoryStates.confirm_delete, F.data == "confirm_delete")
@admin_required
async def confirm_category_delete(callback: CallbackQuery, state: FSMContext):
    """Финальное удаление категории"""
    try:
        data = await state.get_data()
        category_id = data.get('category_id')

        if not category_id:
            await callback.answer("❌ Категория не выбрана", show_alert=True)
            await state.clear()
            return

        async with AsyncSessionLocal() as session:
            category = await session.get(Category, category_id)
            if not category:
                await callback.answer("❌ Категория не найдена", show_alert=True)
                await state.clear()
                return

            category_name = category.name
            brand_name = category.brand.name
            await session.delete(category)
            await session.commit()

            await callback.message.edit_text(
                f"✅ Категория успешно удалена:\n"
                f"Бренд: {brand_name}\n"
                f"Категория: {category_name}"
            )
    except Exception as e:
        logger.error(f"Ошибка удаления категории: {e}")
        await callback.message.edit_text("❌ Ошибка при удалении категории")
    finally:
        await state.clear()
        await callback.answer()


@router.callback_query(CategoryStates.confirm_delete, F.data == "cancel_delete")
@admin_required
async def cancel_category_delete(callback: CallbackQuery, state: FSMContext):
    """Отмена удаления категории"""
    try:
        await state.clear()
        await callback.message.edit_text("❌ Удаление категории отменено")
    except Exception as e:
        logger.error(f"Ошибка отмены удаления: {e}")
    finally:
        await callback.answer()
        await categories_menu(callback)


# ========================
# УПРАВЛЕНИЕ ТОВАРАМИ
# ========================

@router.callback_query(F.data == "products_menu")
@admin_required
async def products_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Список товаров", callback_data="view_products"),
        InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_product_select")
    )
    builder.row(
        InlineKeyboardButton(text="🗑️ Удалить", callback_data="delete_product_select"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
    )
    await callback.message.edit_text("📦 Управление товарами:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "view_products")
@admin_required
async def view_products(callback: CallbackQuery):
    """Просмотр списка товаров (без фото)"""
    try:
        async with AsyncSessionLocal() as session:
            products_with_details = await get_products_with_details(session)

            if not products_with_details:
                await callback.message.answer("ℹ️ Товаров пока нет")
                return await callback.answer()

            # Группируем товары по категориям и брендам для лучшего отображения
            products_by_category = {}
            for product, category, brand in products_with_details:
                key = f"{brand.name} / {category.name}"
                if key not in products_by_category:
                    products_by_category[key] = []
                products_by_category[key].append(product)

            # Формируем сообщение
            message_text = "📦 <b>Список товаров:</b>\n\n"
            for category_path, products in products_by_category.items():
                message_text += f"<b>{category_path}</b>\n"
                for product in products:
                    message_text += (
                        f"├ {product.name}\n"
                        f"├─ Цена: {product.price} руб.\n"
                        f"├─ Описание: {product.description or 'нет описания'}\n"
                        f"└─ ID: {product.id}\n\n"
                    )

            await callback.message.answer(message_text)

    except Exception as e:
        logger.error(f"Ошибка при получении товаров: {e}", exc_info=True)
        await callback.message.answer("❌ Ошибка при получении списка товаров")
    finally:
        await callback.answer()


@router.callback_query(F.data == "add_product_start")
@admin_required
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    async with AsyncSession(engine) as session:
        brands = await get_brands(session)

        if not brands:
            await callback.message.answer("ℹ️ Сначала добавьте бренды")
            return await callback.answer()

        builder = InlineKeyboardBuilder()
        for brand in brands:
            builder.button(text=brand.name, callback_data=f"add_prod_brand_{brand.id}")
        builder.adjust(2)

        await callback.message.edit_text(
            "Выберите бренд:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(AddStates.product_brand)
        await callback.answer()


@router.callback_query(AddStates.product_brand, F.data.startswith("add_prod_brand_"))
@admin_required
async def select_product_category(callback: CallbackQuery, state: FSMContext):
    brand_id = int(callback.data.split("_")[3])
    await state.update_data(brand_id=brand_id)

    async with AsyncSession(engine) as session:
        brand = await session.get(Brand, brand_id)
        result = await session.execute(select(Category).where(Category.brand_id == brand.id))
        categories = result.scalars().all()

        if not categories:
            await callback.message.answer("ℹ️ У этого бренда нет категорий")
            return await state.clear()

        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.button(text=category.name, callback_data=f"add_prod_cat_{category.id}")
        builder.adjust(2)

        await callback.message.edit_text(
            "Выберите категорию:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(AddStates.product_category)
        await callback.answer()


@router.callback_query(AddStates.product_category, F.data.startswith("add_prod_cat_"))
@admin_required
async def set_product_name(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[3])
    await state.update_data(category_id=category_id)
    await callback.message.answer("Введите название товара:")
    await state.set_state(AddStates.product_name)
    await callback.answer()


@router.message(AddStates.product_name)
@admin_required
async def set_product_price(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите цену товара:")
    await state.set_state(AddStates.product_price)


@router.message(AddStates.product_price)
@admin_required
async def set_product_photo(message: Message, state: FSMContext):
    try:
        price = float(message.text)
        await state.update_data(price=price)
        await message.answer("Отправьте фото товара:")
        await state.set_state(AddStates.product_photo)
    except ValueError:
        await message.answer("❌ Введите корректную цену (число):")


@router.message(AddStates.product_photo, F.photo)
@admin_required
async def set_product_description(message: Message, state: FSMContext):
    os.makedirs("/var/www/rshop/static/products", exist_ok=True)
    photo = message.photo[-1]
    photo_filename = f"{photo.file_id}.jpg"
    photo_url = f"products/{photo_filename}"
    full_path = f"/var/www/rshop/static/{photo_url}"

    try:
        file = await message.bot.get_file(photo.file_id)
        await message.bot.download_file(file.file_path, full_path)
        await state.update_data(photo_url=photo_url)
        await message.answer("Введите описание товара (или '-' чтобы пропустить):")
        await state.set_state(AddStates.product_description)
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения фото: {str(e)}")


@router.message(AddStates.product_description)
@admin_required
async def add_product_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    description = message.text if message.text != "-" else None

    async with AsyncSession(engine) as session:
        product = Product(
            name=data['name'],
            price=data['price'],
            photo_url=data['photo_url'],
            description=description,
            category_id=data['category_id']
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

        caption = (
            f"✅ Товар добавлен (ID: {product.id})\n"
            f"Название: {product.name}\n"
            f"Цена: {product.price} руб.\n"
            f"Описание: {product.description or 'Без описания'}"
        )

        try:
            photo = FSInputFile(f"/var/www/rshop/static/{product.photo_url}")
            await message.answer_photo(photo, caption=caption)
        except:
            await message.answer(caption + "\n\n⚠️ Фото не загружено")

    await state.clear()
    await admin_panel(message)


@router.callback_query(F.data == "edit_product_select")
@admin_required
async def select_product_to_edit(callback: CallbackQuery):
    async with AsyncSession(engine) as session:
        products = await get_products(session)

        if not products:
            await callback.message.answer("ℹ️ Товаров пока нет")
            return await callback.answer()

        builder = InlineKeyboardBuilder()
        for product in products:
            builder.button(
                text=f"{product.name} (ID: {product.id})",
                callback_data=f"edit_prod_{product.id}"
            )
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="products_menu"))

        await callback.message.edit_text(
            "Выберите товар для редактирования:",
            reply_markup=builder.as_markup()
        )
        await callback.answer()


@router.callback_query(F.data.startswith("edit_prod_"))
@admin_required
async def select_product_field(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[2])
    await state.update_data(product_id=product_id)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Название", callback_data="edit_field_name"),
        InlineKeyboardButton(text="💵 Цена", callback_data="edit_field_price")
    )
    builder.row(
        InlineKeyboardButton(text="📝 Описание", callback_data="edit_field_desc"),
        InlineKeyboardButton(text="🖼️ Фото", callback_data="edit_field_photo")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="products_menu"))

    await callback.message.edit_text(
        "Выберите что редактировать:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "edit_field_name")
@admin_required
async def edit_product_name(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новое название:")
    await state.set_state(EditStates.field)
    await state.update_data(field="name")
    await callback.answer()


@router.callback_query(F.data == "edit_field_price")
@admin_required
async def edit_product_price(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новую цену:")
    await state.set_state(EditStates.field)
    await state.update_data(field="price")
    await callback.answer()


@router.callback_query(F.data == "edit_field_desc")
@admin_required
async def edit_product_desc(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новое описание (или '-' чтобы удалить):")
    await state.set_state(EditStates.field)
    await state.update_data(field="description")
    await callback.answer()


@router.callback_query(F.data == "edit_field_photo")
@admin_required
async def edit_product_photo(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправьте новое фото:")
    await state.set_state(EditStates.field)
    await state.update_data(field="photo_url")
    await callback.answer()


@router.message(EditStates.field)
@admin_required
async def save_product_changes(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data['field']
    value = message.text if field != "photo_url" else None

    if field == "photo_url" and message.photo:
        photo = message.photo[-1]
        photo_filename = f"{photo.file_id}.jpg"
        photo_url = f"products/{photo_filename}"
        full_path = f"/var/www/rshop/static/{photo_url}"

        try:
            # Удаляем старое фото
            async with AsyncSession(engine) as session:
                product = await session.get(Product, data['product_id'])
                old_photo = f"/var/www/rshop/static/{product.photo_url}"
                if os.path.exists(old_photo):
                    os.remove(old_photo)

            # Сохраняем новое фото
            file = await message.bot.get_file(photo.file_id)
            await message.bot.download_file(file.file_path, full_path)
            value = photo_url
        except Exception as e:
            await message.answer(f"❌ Ошибка обновления фото: {str(e)}")
            return

    if field == "description" and value == "-":
        value = None

    if field == "price":
        try:
            value = float(value)
        except ValueError:
            await message.answer("❌ Введите корректную цену")
            return

    async with AsyncSession(engine) as session:
        product = await session.get(Product, data['product_id'])
        setattr(product, field, value)
        await session.commit()
        await message.answer(f"✅ {field.capitalize()} успешно обновлено")

    await state.clear()
    await admin_panel(message)