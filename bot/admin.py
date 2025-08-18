import os
import logging
from functools import wraps
from typing import Union, List, Any, Callable, Dict
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from models import Brand, Category, Product
from database import engine, AsyncSessionLocal
from sqlalchemy.orm import joinedload

router = Router()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMINS = [6326719341, 790410251, 6388614116, 8188457128]  # Ваш Telegram ID

# Настройки пагинации
PAGINATION_BRANDS_PER_PAGE = 10
PAGINATION_CATEGORIES_PER_PAGE = 8
PAGINATION_PRODUCTS_PER_PAGE = 20


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
    brand_name = State()
    category_name = State()  # Добавлено это состояние
    category_id = State()
    product_id = State()
    field = State()
    new_value = State()


class DeleteStates(StatesGroup):
    brand_name = State()
    category_name = State()
    product_name = State()
    confirm_delete = State()
    select_brand_for_category = State()
    search_product = State()  # Для поиска товара при редактировании


# Проверка прав администратора
async def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# Декоратор для проверки прав администратора
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

        if not await is_admin(update.from_user.id):
            logger.warning(f"Попытка несанкционированного доступа: {update.from_user.id}")
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
    result = await session.execute(
        select(Category, Brand)
        .join(Brand, Category.brand_id == Brand.id)
        .order_by(Brand.name, Category.name)
    )
    return result.all()


async def get_products_with_details(session: AsyncSession):
    try:
        result = await session.execute(
            select(Product)
            .join(Category, Product.category_id == Category.id)
            .join(Brand, Category.brand_id == Brand.id)
            .order_by(Brand.name, Category.name, Product.name)
            .options(
                joinedload(Product.category).joinedload(Category.brand)
            )
        )
        return result.unique().scalars().all()
    except Exception as e:
        logger.error(f"Ошибка в get_products_with_details: {e}")
        raise


async def get_categories_by_brand(session: AsyncSession, brand_id: int):
    result = await session.execute(
        select(Category)
        .where(Category.brand_id == brand_id)
    )
    return result.scalars().all()


async def get_products(session: AsyncSession):
    result = await session.execute(select(Product))
    return result.scalars().all()


# Функция для пагинации
async def send_paginated_message(
        callback: CallbackQuery,
        items: List[Any],
        title: str,
        item_format: Callable[[Any, int], str],
        items_per_page: int = 5,
        current_page: int = 0,
        back_callback: str = "admin_back",
        menu_callback: str = None,
        action_callback: str = None,
        parse_mode: str = "HTML"
):
    total_items = len(items)
    if total_items == 0:
        await callback.message.answer(f"{title}\n\nСписок пуст", parse_mode=parse_mode)
        return

    total_pages = (total_items + items_per_page - 1) // items_per_page
    start_idx = current_page * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)

    message_text = f"{title}\n\n"
    for i, item in enumerate(items[start_idx:end_idx], start_idx + 1):
        message_text += f"{item_format(item, i)}\n"

    message_text += f"\nСтраница {current_page + 1} из {total_pages}"

    builder = InlineKeyboardBuilder()

    if current_page > 0:
        builder.button(text="⬅️ Назад", callback_data=f"page_{current_page - 1}")
    if current_page < total_pages - 1:
        builder.button(text="Вперёд ➡️", callback_data=f"page_{current_page + 1}")

    if action_callback:
        for i, item in enumerate(items[start_idx:end_idx], start_idx):
            item_id = item[0].id if isinstance(item, tuple) else item.id
            builder.button(
                text=f"Выбрать {i + 1}",
                callback_data=f"{action_callback}:{item_id}"
            )
        builder.adjust(2, repeat=True)

    if menu_callback:
        builder.button(text="🔙 В меню", callback_data=menu_callback)
    else:
        builder.button(text="🔙 Назад", callback_data=back_callback)

    builder.adjust(2)

    try:
        await callback.message.edit_text(
            text=message_text,
            reply_markup=builder.as_markup(),
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
        await callback.message.answer(
            text=message_text,
            reply_markup=builder.as_markup(),
            parse_mode=parse_mode
        )


# Главное меню админки
async def admin_panel(update: Union[Message, CallbackQuery]):
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

    if isinstance(update, CallbackQuery):
        await update.message.edit_text(
            "👨‍💻 Админ-панель:",
            reply_markup=builder.as_markup()
        )
    else:
        await update.answer(
            "👨‍💻 Админ-панель:",
            reply_markup=builder.as_markup()
        )


# Обработчик команды /admin
@router.message(Command("admin"))
@admin_required
async def admin_command(message: Message):
    await admin_panel(message)


# Обработчик кнопки "Назад"
@router.callback_query(F.data == "admin_back")
@admin_required
async def back_to_admin(callback: CallbackQuery):
    try:
        await admin_panel(callback)
    except Exception as e:
        logger.error(f"Ошибка в обработчике назад: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
    finally:
        await callback.answer()


# ========================
# УПРАВЛЕНИЕ БРЕНДАМИ
# ========================

@router.callback_query(F.data == "brands_menu")
@admin_required
async def brands_menu(callback: CallbackQuery):
    """Главное меню управления брендами"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Список брендов", callback_data="view_brands"),
        InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_brand_select")
    )
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="add_brand_start"),
        InlineKeyboardButton(text="🗑️ Удалить", callback_data="delete_brand_select")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    try:
        await callback.message.edit_text(
            "🏷️ <b>Управление брендами:</b>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в brands_menu: {e}")
        await callback.message.answer(
            "🏷️ <b>Управление брендами:</b>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "view_brands")
@admin_required
async def view_brands(callback: CallbackQuery):
    """Просмотр списка брендов с пагинацией"""
    try:
        async with AsyncSessionLocal() as session:
            brands = await get_brands(session)

            def format_brand(brand: Brand, idx: int) -> str:
                return f"{idx}. {brand.name} (ID: {brand.id})"

            await send_paginated_message(
                callback=callback,
                items=brands,
                title="🏷️ <b>Список брендов:</b>",
                item_format=format_brand,
                items_per_page=PAGINATION_BRANDS_PER_PAGE,
                menu_callback="brands_menu",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Ошибка при получении брендов: {e}")
        await callback.message.answer("❌ Ошибка при загрузке списка брендов")
    finally:
        await callback.answer()


@router.callback_query(F.data == "add_brand_start")
@admin_required
async def add_brand_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса добавления бренда"""
    await callback.message.answer("✏️ Введите название нового бренда:")
    await state.set_state(AddStates.brand_name)
    await callback.answer()


@router.message(AddStates.brand_name)
@admin_required
async def add_brand_finish(message: Message, state: FSMContext):
    """Завершение добавления бренда"""
    brand_name = message.text.strip()
    if not brand_name:
        await message.answer("❌ Название бренда не может быть пустым. Попробуйте снова:")
        return

    try:
        async with AsyncSessionLocal() as session:
            # Проверяем, существует ли уже бренд с таким именем
            existing_brand = await session.execute(
                select(Brand).where(func.lower(Brand.name) == func.lower(brand_name)
                                    ))
            if existing_brand.scalar_one_or_none():
                await message.answer(f"❌ Бренд '{brand_name}' уже существует!")
                await state.clear()
                return await admin_panel(message)

            # Создаем новый бренд
            new_brand = Brand(name=brand_name)
            session.add(new_brand)
            await session.commit()

            await message.answer(f"✅ Бренд <b>{brand_name}</b> успешно добавлен!", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка при добавлении бренда: {e}")
        await message.answer("❌ Произошла ошибка при добавлении бренда")
    finally:
        await state.clear()
        await admin_panel(message)


@router.callback_query(F.data == "edit_brand_select")
@admin_required
async def edit_brand_select(callback: CallbackQuery, state: FSMContext):
    """Выбор бренда для редактирования"""
    await callback.message.answer("🔍 Введите название бренда для редактирования:")
    await state.set_state(EditStates.brand_name)  # Используем отдельное состояние для редактирования
    await callback.answer()


@router.message(EditStates.brand_name)
@admin_required
async def find_brand_to_edit(message: Message, state: FSMContext):
    """Поиск бренда для редактирования"""
    search_text = message.text.strip().lower()
    if not search_text:
        await message.answer("❌ Введите название бренда:")
        return

    try:
        async with AsyncSessionLocal() as session:
            # Ищем бренд по точному совпадению (регистронезависимо)
            stmt = select(Brand).where(func.lower(Brand.name) == search_text)
            result = await session.execute(stmt)
            brand = result.scalar_one_or_none()

            if not brand:
                await message.answer(f"❌ Бренд не найден. Проверьте название.")
                return

            # Сохраняем ID бренда для последующего редактирования
            await state.update_data(brand_id=brand.id)

            # Создаем клавиатуру с вариантами действий
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(
                    text="✏️ Изменить название",
                    callback_data=f"edit_brand_name:{brand.id}"
                )
            )
            builder.row(
                InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data="brands_menu"
                )
            )

            await message.answer(
                f"🏷 <b>Найден бренд:</b>\n"
                f"Название: {brand.name}\n"
                f"ID: {brand.id}\n\n"
                f"Выберите действие:",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка при поиске бренда: {e}")
        await message.answer("❌ Произошла ошибка при поиске бренда")
        await state.clear()


@router.callback_query(F.data.startswith("edit_brand_name:"))
@admin_required
async def start_edit_brand_name(callback: CallbackQuery, state: FSMContext):
    """Начало процесса изменения названия бренда"""
    try:
        brand_id = int(callback.data.split(":")[1])
        await state.update_data(brand_id=brand_id)
        await callback.message.answer("✏️ Введите новое название бренда:")
        await state.set_state(EditStates.new_value)
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await callback.answer("❌ Ошибка обработки команды")
    finally:
        await callback.answer()


@router.message(EditStates.new_value)
@admin_required
async def save_edited_brand_name(message: Message, state: FSMContext):
    """Сохранение нового названия бренда"""
    new_name = message.text.strip()
    if not new_name:
        await message.answer("❌ Название не может быть пустым. Введите новое название:")
        return

    try:
        data = await state.get_data()
        brand_id = data.get('brand_id')

        async with AsyncSessionLocal() as session:
            brand = await session.get(Brand, brand_id)
            if not brand:
                await message.answer("❌ Бренд не найден")
                await state.clear()
                return

            # Проверяем, нет ли уже бренда с таким названием
            existing_brand = await session.execute(
                select(Brand).where(
                    and_(
                        func.lower(Brand.name) == func.lower(new_name),
                        Brand.id != brand_id
                    )
                )
            )
            if existing_brand.scalar_one_or_none():
                await message.answer(f"❌ Бренд с названием '{new_name}' уже существует!")
                return

            old_name = brand.name
            brand.name = new_name
            await session.commit()

            await message.answer(
                f"✅ Бренд успешно обновлен!\n"
                f"Старое название: {old_name}\n"
                f"Новое название: {new_name}"
            )
    except Exception as e:
        logger.error(f"Ошибка при сохранении бренда: {e}")
        await message.answer("❌ Произошла ошибка при сохранении изменений")
    finally:
        await state.clear()
        await admin_panel(message)


@router.callback_query(F.data == "delete_brand_select")
@admin_required
async def delete_brand_select(callback: CallbackQuery, state: FSMContext):
    """Начало процесса удаления бренда"""
    await callback.message.answer("🔍 Введите название бренда для удаления:")
    await state.set_state(DeleteStates.brand_name)  # Явно указываем состояние удаления
    await callback.answer()


@router.message(DeleteStates.brand_name)
@admin_required
async def find_brand_to_delete(message: Message, state: FSMContext):
    """Поиск бренда для удаления"""
    search_text = message.text.strip().lower()
    if not search_text:
        await message.answer("❌ Введите название бренда:")
        return

    try:
        async with AsyncSessionLocal() as session:
            # Ищем бренд по точному совпадению (регистронезависимо)
            stmt = select(Brand).where(func.lower(Brand.name) == search_text)
            result = await session.execute(stmt)
            brand = result.scalar_one_or_none()

            if not brand:
                await message.answer(f"❌ Бренд не найден. Проверьте название.")
                return

            # Проверяем есть ли категории у этого бренда
            categories_count = await session.execute(
                select(func.count(Category.id))
                .where(Category.brand_id == brand.id)
            )
            categories_count = categories_count.scalar()

            warning = ""
            if categories_count > 0:
                warning = f"\n\n⚠️ Внимание! У этого бренда {categories_count} категорий, они тоже будут удалены!"

            await state.update_data(brand_id=brand.id)

            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data="confirm_brand_delete"
                ),
                InlineKeyboardButton(
                    text="❌ Нет, отмена",
                    callback_data="cancel_brand_delete"
                )
            )

            await message.answer(
                f"Вы уверены, что хотите удалить бренд?\n"
                f"Название: {brand.name}\n"
                f"ID: {brand.id}{warning}",
                reply_markup=builder.as_markup()
            )
            await state.set_state(DeleteStates.confirm_delete)

    except Exception as e:
        logger.error(f"Ошибка при поиске бренда: {e}")
        await message.answer("❌ Произошла ошибка при поиске бренда")
        await state.clear()


@router.callback_query(DeleteStates.confirm_delete, F.data == "confirm_brand_delete")
@admin_required
async def execute_brand_delete(callback: CallbackQuery, state: FSMContext):
    """Окончательное удаление бренда"""
    try:
        data = await state.get_data()
        brand_id = data.get('brand_id')

        if not brand_id:
            await callback.message.answer("❌ Бренд не выбран")
            await state.clear()
            return

        async with AsyncSessionLocal() as session:
            # Получаем бренд со всеми связанными категориями
            brand = await session.get(Brand, brand_id, options=[joinedload(Brand.categories)])
            if not brand:
                await callback.message.answer("❌ Бренд не найден")
                await state.clear()
                return

            # Удаляем все связанные категории (и их товары через каскадное удаление)
            for category in brand.categories:
                await session.delete(category)

            brand_name = brand.name
            await session.delete(brand)
            await session.commit()

            await callback.message.answer(
                f"✅ Бренд успешно удалён:\n"
                f"Название: {brand_name}\n"
                f"ID: {brand_id}"
            )
    except Exception as e:
        logger.error(f"Ошибка при удалении бренда: {e}")
        await callback.message.answer("❌ Произошла ошибка при удалении бренда")
    finally:
        await state.clear()
        await admin_panel(callback.message)


@router.callback_query(DeleteStates.confirm_delete, F.data == "cancel_brand_delete")
@admin_required
async def cancel_brand_delete(callback: CallbackQuery, state: FSMContext):
    """Отмена удаления бренда"""
    await state.clear()
    await callback.message.answer("❌ Удаление бренда отменено")
    await admin_panel(callback.message)


class EditStates(StatesGroup):
    brand_name = State()
    category_name = State()  # Добавлено это состояние
    category_id = State()
    product_id = State()
    field = State()
    new_value = State()


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
async def view_products(callback: CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        current_page = data.get('products_page', 0)

        async with AsyncSessionLocal() as session:
            products = await get_products_with_details(session)

            # Логируем полученные данные для отладки
            logger.info(f"Получено {len(products)} записей")
            if products:
                logger.info(f"Первая запись: {products[0].name}")

            # Группируем по категориям
            grouped_data = {}
            for product in products:
                category = product.category
                brand = category.brand
                key = f"{brand.name} / {category.name}"
                if key not in grouped_data:
                    grouped_data[key] = []
                grouped_data[key].append(product)

            # Формируем плоский список для пагинации
            flat_list = []
            for category_path, products in grouped_data.items():
                flat_list.append(("header", category_path))
                for product in products:
                    flat_list.append(("product", product))

            def format_item(item, idx):
                if item[0] == "header":
                    return f"\n<b>{item[1]}</b>"
                else:
                    product = item[1]
                    return (
                        f"├ {product.name}\n"
                        f"├─ Цена: {product.price} руб.\n"
                        f"├─ Описание: {product.description or 'нет описания'}\n"
                        f"└─ ID: {product.id}"
                    )

            await send_paginated_message(
                callback=callback,
                items=flat_list,
                title="📦 <b>Список товаров:</b>",
                item_format=format_item,
                items_per_page=PAGINATION_PRODUCTS_PER_PAGE,
                current_page=current_page,
                menu_callback="products_menu"
            )

    except Exception as e:
        logger.error(f"Полная ошибка в view_products: {e}", exc_info=True)
        await callback.message.answer("❌ Ошибка при формировании списка товаров")
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
async def start_product_search(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🔍 Введите название товара для редактирования:")
    await state.set_state(DeleteStates.search_product)
    await callback.answer()


@router.message(DeleteStates.search_product)
@admin_required
async def find_and_edit_product(message: Message, state: FSMContext):
    search_text = message.text.strip().lower()

    async with AsyncSessionLocal() as session:
        # Ищем товар по названию (регистронезависимо)
        stmt = (
            select(Product)
            .join(Category).join(Brand)
            .where(func.lower(Product.name) == search_text)
            .options(joinedload(Product.category).joinedload(Category.brand))
        )
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            await message.answer("❌ Товар не найден. Проверьте название или используйте /admin для возврата.")
            await state.clear()
            return

        # Сохраняем ID товара для редактирования
        await state.update_data(product_id=product.id)

        # Формируем информацию о товаре
        info_text = (
            f"🏷 Товар: {product.name}\n"
            f"🏭 Бренд: {product.category.brand.name}\n"
            f"📂 Категория: {product.category.name}\n"
            f"💵 Цена: {product.price} руб.\n"
            f"📝 Описание: {product.description or 'нет'}\n"
            f"🆔 ID: {product.id}"
        )

        # Кнопки для выбора поля
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

        # Отправляем фото товара (если есть)
        if product.photo_url:
            try:
                photo = FSInputFile(f"/var/www/rshop/static/{product.photo_url}")
                await message.answer_photo(photo, caption=info_text, reply_markup=builder.as_markup())
            except:
                await message.answer(info_text, reply_markup=builder.as_markup())
        else:
            await message.answer(info_text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("select_product_"))
@admin_required
async def handle_product_selection(callback: CallbackQuery):
    try:
        product_id = int(callback.data.split("_")[2])

        async with AsyncSessionLocal() as session:
            product = await session.get(
                Product,
                product_id,
                options=[joinedload(Product.category).joinedload(Category.brand)]
            )

            if product:
                await callback.message.delete()  # Удаляем сообщение со списком
                await show_product_edit_options(callback.message, product)
            else:
                await callback.answer("❌ Товар не найден", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка выбора товара: {str(e)}", exc_info=True)
        await callback.answer("⚠️ Ошибка при выборе товара", show_alert=True)


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


@router.callback_query(F.data == "delete_product_select")
@admin_required
async def delete_product_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название товара для удаления:")
    await state.set_state(DeleteStates.product_name)
    await callback.answer()


@router.message(DeleteStates.product_name)
@admin_required
async def delete_product_confirm(message: Message, state: FSMContext):
    product_name = message.text.strip()

    async with AsyncSession(engine) as session:
        # Ищем товар по имени (регистронезависимо)
        stmt = select(Product).where(func.lower(Product.name) == func.lower(product_name))
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            await message.answer(f"❌ Товар '{product_name}' не найден")
            await state.clear()
            return

        # Получаем категорию и бренд для отображения
        category = await session.get(Category, product.category_id)
        brand = await session.get(Brand, category.brand_id)

        await state.update_data(product_id=product.id)

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_product_delete"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="admin_back")
        )

        await message.answer(
            f"Вы уверены, что хотите удалить товар?\n"
            f"Бренд: {brand.name}\n"
            f"Категория: {category.name}\n"
            f"Товар: {product.name}\n"
            f"Цена: {product.price} руб.\n"
            f"ID: {product.id}",
            reply_markup=builder.as_markup()
        )
        await state.set_state(DeleteStates.confirm_delete)


@router.callback_query(DeleteStates.confirm_delete, F.data == "confirm_product_delete")
@admin_required
async def delete_product_execute(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    product_id = data.get('product_id')

    if not product_id:
        await callback.message.answer("❌ Товар не выбран")
        await state.clear()
        return

    async with AsyncSession(engine) as session:
        product = await session.get(Product, product_id)
        if not product:
            await callback.message.answer("❌ Товар не найден")
            await state.clear()
            return

        # Удаляем фото товара
        if product.photo_url:
            photo_path = f"/var/www/rshop/static/{product.photo_url}"
            if os.path.exists(photo_path):
                try:
                    os.remove(photo_path)
                except Exception as e:
                    logger.error(f"Ошибка удаления фото: {e}")

        product_name = product.name
        await session.delete(product)
        await session.commit()

        await callback.message.answer(
            f"✅ Товар успешно удалён:\n"
            f"Название: {product_name}\n"
            f"ID: {product_id}"
        )

    await state.clear()
    await admin_panel(callback.message)


# Обработчик пагинации
@router.callback_query(F.data.startswith("page_"))
@admin_required
async def handle_pagination(callback: CallbackQuery, state: FSMContext):
    try:
        page = int(callback.data.split("_")[1])
        await state.update_data(products_page=page)  # Явно сохраняем страницу товаров

        # Определяем контекст по тексту сообщения
        message_text = callback.message.text or ""

        if "товар" in message_text.lower():
            await view_products(callback, state)
        elif "бренд" in message_text.lower():
            await view_brands(callback, state)
        elif "категори" in message_text.lower():
            await view_categories(callback, state)
        else:
            await callback.answer("Неизвестный контекст пагинации")

    except Exception as e:
        logger.error(f"Ошибка обработки пагинации: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при переключении страницы")


# ========================
# УПРАВЛЕНИЕ КАТЕГОРИЯМИ (ИСПРАВЛЕННАЯ ВЕРСИЯ)
# ========================

class CategoryStates(StatesGroup):
    select_brand = State()
    enter_name = State()
    edit_select = State()
    edit_enter_name = State()
    delete_select = State()
    delete_confirm = State()


@router.callback_query(F.data == "categories_menu")
@admin_required
async def categories_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Список категорий", callback_data="view_categories"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="add_category_start")
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_category_start"),
        InlineKeyboardButton(text="🗑️ Удалить", callback_data="delete_category_start")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    try:
        await callback.message.edit_text(
            "📂 Управление категориями:",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Ошибка в меню категорий: {e}")
        await callback.answer("❌ Ошибка при отображении меню")


@router.callback_query(F.data == "view_categories")
@admin_required
async def view_categories(callback: CallbackQuery):
    try:
        async with AsyncSessionLocal() as session:
            categories = await session.execute(
                select(Category)
                .options(joinedload(Category.brand))
                .order_by(Category.name)
            )
            categories = categories.unique().scalars().all()

            if not categories:
                await callback.message.answer("ℹ️ Список категорий пуст")
                return

            def format_category(category: Category, idx: int) -> str:
                return f"{idx}. {category.brand.name} / {category.name} (ID: {category.id})"

            await send_paginated_message(
                callback=callback,
                items=categories,
                title="📂 Список категорий:",
                item_format=format_category,
                items_per_page=PAGINATION_CATEGORIES_PER_PAGE,
                menu_callback="categories_menu"
            )
    except Exception as e:
        logger.error(f"Ошибка при загрузке категорий: {e}")
        await callback.answer("❌ Ошибка при загрузке списка")


@router.callback_query(F.data == "add_category_start")
@admin_required
async def add_category_start(callback: CallbackQuery, state: FSMContext):
    try:
        async with AsyncSessionLocal() as session:
            brands = await session.execute(select(Brand).order_by(Brand.name))
            brands = brands.scalars().all()

            if not brands:
                await callback.message.answer("ℹ️ Сначала добавьте бренды")
                return

            builder = InlineKeyboardBuilder()
            for brand in brands:
                builder.button(text=brand.name, callback_data=f"add_cat_brand_{brand.id}")

            builder.adjust(2)
            builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="categories_menu"))

            await callback.message.edit_text(
                "Выберите бренд для новой категории:",
                reply_markup=builder.as_markup()
            )
            await state.set_state(CategoryStates.select_brand)
    except Exception as e:
        logger.error(f"Ошибка при запуске добавления: {e}")
        await callback.answer("❌ Ошибка при запуске")


@router.callback_query(CategoryStates.select_brand, F.data.startswith("add_cat_brand_"))
@admin_required
async def select_brand_for_category(callback: CallbackQuery, state: FSMContext):
    try:
        brand_id = int(callback.data.split("_")[3])
        await state.update_data(brand_id=brand_id)
        await callback.message.answer("Введите название новой категории:")
        await state.set_state(CategoryStates.enter_name)
    except Exception as e:
        logger.error(f"Ошибка выбора бренда: {e}")
        await callback.answer("❌ Ошибка выбора")


@router.message(CategoryStates.enter_name)
@admin_required
async def save_new_category(message: Message, state: FSMContext):
    try:
        category_name = message.text.strip()
        if not category_name:
            await message.answer("❌ Название не может быть пустым. Введите снова:")
            return

        data = await state.get_data()
        brand_id = data.get('brand_id')

        async with AsyncSessionLocal() as session:
            # Проверка на существующую категорию
            existing = await session.scalar(
                select(Category).where(
                    and_(
                        Category.brand_id == brand_id,
                        func.lower(Category.name) == func.lower(category_name)
                    )
                )
            )

            if existing:
                await message.answer("❌ Категория с таким названием уже существует")
                return

            new_category = Category(name=category_name, brand_id=brand_id)
            session.add(new_category)
            await session.commit()

            await message.answer(f"✅ Категория '{category_name}' успешно добавлена")
            await admin_panel(message)

    except Exception as e:
        logger.error(f"Ошибка сохранения категории: {e}")
        await message.answer("❌ Ошибка при сохранении категории")
    finally:
        await state.clear()


@router.callback_query(F.data == "edit_category_start")
@admin_required
async def edit_category_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🔍 Введите название категории для редактирования:")
    await state.set_state(CategoryStates.edit_select)
    await callback.answer()


@router.message(CategoryStates.edit_select)
@admin_required
async def find_category_to_edit(message: Message, state: FSMContext):
    try:
        search_text = message.text.strip().lower()
        if not search_text:
            await message.answer("❌ Введите название категории:")
            return

        async with AsyncSessionLocal() as session:
            categories = await session.execute(
                select(Category)
                .join(Brand)
                .where(func.lower(Category.name) == search_text)
                .options(joinedload(Category.brand))
            )
            categories = categories.unique().scalars().all()

            if not categories:
                await message.answer("❌ Категория не найдена")
                return

            if len(categories) == 1:
                category = categories[0]
                await state.update_data(category_id=category.id)
                await message.answer(
                    f"Найдена категория: {category.brand.name} / {category.name}\n"
                    "Введите новое название:"
                )
                await state.set_state(CategoryStates.edit_enter_name)
            else:
                builder = InlineKeyboardBuilder()
                for category in categories:
                    builder.button(
                        text=f"{category.brand.name} - {category.name}",
                        callback_data=f"edit_cat_{category.id}"
                    )
                builder.adjust(1)
                await message.answer(
                    "Найдено несколько категорий. Выберите нужную:",
                    reply_markup=builder.as_markup()
                )
    except Exception as e:
        logger.error(f"Ошибка поиска категории: {e}")
        await message.answer("❌ Ошибка при поиске категории")


@router.callback_query(F.data.startswith("edit_cat_"))
@admin_required
async def select_category_to_edit(callback: CallbackQuery, state: FSMContext):
    try:
        category_id = int(callback.data.split("_")[1])
        await state.update_data(category_id=category_id)
        await callback.message.answer("Введите новое название категории:")
        await state.set_state(CategoryStates.edit_enter_name)
    except Exception as e:
        logger.error(f"Ошибка выбора категории: {e}")
        await callback.answer("❌ Ошибка при выборе категории")


@router.message(CategoryStates.edit_enter_name)
@admin_required
async def save_edited_category(message: Message, state: FSMContext):
    try:
        new_name = message.text.strip()
        if not new_name:
            await message.answer("❌ Название не может быть пустым. Введите снова:")
            return

        data = await state.get_data()
        category_id = data.get('category_id')

        async with AsyncSessionLocal() as session:
            category = await session.get(Category, category_id, options=[joinedload(Category.brand)])
            if not category:
                await message.answer("❌ Категория не найдена")
                await state.clear()
                return

            # Проверка на дубликат
            existing = await session.scalar(
                select(Category).where(
                    and_(
                        Category.brand_id == category.brand_id,
                        func.lower(Category.name) == func.lower(new_name),
                        Category.id != category_id
                    )
                )
            )
            if existing:
                await message.answer("❌ Категория с таким названием уже существует")
                return

            old_name = category.name
            category.name = new_name
            await session.commit()

            await message.answer(
                f"✅ Категория успешно обновлена\n"
                f"Было: {old_name}\n"
                f"Стало: {new_name}"
            )
            await admin_panel(message)
    except Exception as e:
        logger.error(f"Ошибка сохранения изменений: {e}")
        await message.answer("❌ Ошибка при сохранении изменений")
    finally:
        await state.clear()


@router.callback_query(F.data == "delete_category_start")
@admin_required
async def delete_category_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🔍 Введите название категории для удаления:")
    await state.set_state(CategoryStates.delete_select)
    await callback.answer()


@router.message(CategoryStates.delete_select)
@admin_required
async def find_category_to_delete(message: Message, state: FSMContext):
    try:
        search_text = message.text.strip().lower()
        if not search_text:
            await message.answer("❌ Введите название категории:")
            return

        async with AsyncSessionLocal() as session:
            categories = await session.execute(
                select(Category)
                .join(Brand)
                .where(func.lower(Category.name) == search_text)
                .options(joinedload(Category.brand))
            )
            categories = categories.unique().scalars().all()

            if not categories:
                await message.answer("❌ Категория не найдена")
                await state.clear()
                return

            if len(categories) == 1:
                category = categories[0]
                await show_delete_confirmation(message, state, category)
            else:
                builder = InlineKeyboardBuilder()
                for category in categories:
                    builder.button(
                        text=f"{category.brand.name}",
                        callback_data=f"del_cat_{category.id}"
                    )
                builder.adjust(2)
                await message.answer(
                    "Найдено несколько категорий. Выберите нужную:",
                    reply_markup=builder.as_markup()
                )
                await state.update_data(categories={c.id: c for c in categories})
    except Exception as e:
        logger.error(f"Ошибка поиска категории: {e}")
        await message.answer("❌ Ошибка при поиске категории")


async def show_delete_confirmation(message: Message, state: FSMContext, category: Category):
    try:
        async with AsyncSessionLocal() as session:
            products_count = await session.scalar(
                select(func.count(Product.id)).where(Product.category_id == category.id)
            )

            warning = ""
            if products_count > 0:
                warning = f"\n\n⚠️ Внимание! В этой категории {products_count} товаров, они тоже будут удалены!"

            await state.update_data(category_id=category.id)

            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_category_delete"),
                InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_category_delete")
            )

            await message.answer(
                f"Вы уверены, что хотите удалить категорию?\n"
                f"Бренд: {category.brand.name}\n"
                f"Категория: {category.name}\n"
                f"ID: {category.id}{warning}",
                reply_markup=builder.as_markup()
            )
            await state.set_state(CategoryStates.delete_confirm)
    except Exception as e:
        logger.error(f"Ошибка подтверждения удаления: {e}")
        await message.answer("❌ Ошибка при подготовке удаления")


@router.callback_query(F.data.startswith("del_cat_"))
@admin_required
async def select_category_to_delete(callback: CallbackQuery, state: FSMContext):
    try:
        category_id = int(callback.data.split("_")[2])
        data = await state.get_data()
        categories = data.get('categories', {})
        category = categories.get(category_id)

        if not category:
            await callback.answer("❌ Категория не найдена")
            return

        await callback.message.delete()
        await show_delete_confirmation(callback.message, state, category)
    except Exception as e:
        logger.error(f"Ошибка выбора категории: {e}")
        await callback.answer("❌ Ошибка при выборе категории")


@router.callback_query(CategoryStates.delete_confirm, F.data == "confirm_category_delete")
@admin_required
async def execute_category_delete(callback: CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        category_id = data.get('category_id')

        if not category_id:
            await callback.message.answer("❌ Категория не выбрана")
            await state.clear()
            return

        async with AsyncSessionLocal() as session:
            category = await session.get(Category, category_id, options=[joinedload(Category.brand)])
            if not category:
                await callback.message.answer("❌ Категория не найдена")
                await state.clear()
                return

            category_name = category.name
            brand_name = category.brand.name

            await session.delete(category)
            await session.commit()

            await callback.message.answer(
                f"✅ Категория успешно удалена:\n"
                f"Бренд: {brand_name}\n"
                f"Категория: {category_name}\n"
                f"ID: {category_id}"
            )
    except Exception as e:
        logger.error(f"Ошибка при удалении категории: {e}")
        await callback.message.answer("❌ Ошибка при удалении категории")
    finally:
        await state.clear()
        await admin_panel(callback.message)


@router.callback_query(CategoryStates.delete_confirm, F.data == "cancel_category_delete")
@admin_required
async def cancel_category_delete(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Удаление категории отменено")
    await admin_panel(callback.message)