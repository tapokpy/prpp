import sys
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_IDS
from core.llm.ollama_client import OllamaClient
from core.memory.mempalace import MemPalace

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
ollama = OllamaClient()



@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    await msg.answer("👋 Привет! Я ваш ИИ-помощник.")

@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    await msg.answer("📚 /help — справка\n/admin — админка")

@dp.message(Command("admin"))
async def cmd_admin(msg: types.Message):
    if msg.from_user.id not in ADMIN_USER_IDS:
        await msg.answer("❌ Нет прав")
        return
    await msg.answer("👨‍💼 Админ-панель")

@dp.message()
async def handle_message(msg: types.Message):
    user_id = msg.from_user.id
    memory = MemPalace(user_id)

    context = memory.wake_up(msg.text)
    response = ollama.generate(msg.text, context)

    memory.store_interaction(msg.text, response)

    await msg.answer(response)

async def main():
    logger.info("Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
