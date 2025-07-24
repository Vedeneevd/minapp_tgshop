import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: types.Message):
    web_app = types.WebAppInfo(url="https://")
    builder = ReplyKeyboardBuilder()
    builder.button(text="📖 Каталог", web_app=web_app)
    await message.answer(
        "Откройте каталог:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )

if __name__ == "__main__":
    dp.run_polling(bot)