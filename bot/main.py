import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv

# Импорты из вашего проекта
from admin import router as admin_router
from database import init_db

load_dotenv()


async def on_startup():
    """Действия при запуске бота"""
    print("Запуск инициализации базы данных...")
    await init_db()
    print("База данных готова к работе")


async def main():
    # Инициализация бота
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher()

    # Включаем роутеры
    dp.include_router(admin_router)

    # Обработчик команды /start
    @dp.message(Command("start"))
    async def start(message: types.Message):
        web_app = types.WebAppInfo(url="https://rshop1.ru/catalog")
        builder = ReplyKeyboardBuilder()
        builder.button(text="📖 Каталог", web_app=web_app)
        await message.answer(
            "Откройте каталог:",
            reply_markup=builder.as_markup(resize_keyboard=True)
        )

    # Запускаем бота
    await on_startup()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())