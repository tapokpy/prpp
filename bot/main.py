# bot/main.py
import asyncio
import logging
import re
import time
import os
from pathlib import Path
import sys

# === Настройка путей (Чтобы Python видел соседние папки) ===
# Поднимаемся на уровень выше (из bot/ в prpp/), чтобы работали импорты
sys.path.insert(0, str(Path(__file__).parent.parent))

# === Импорты библиотек ===
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ChatAction

# === Импорты из нашего проекта ===
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_IDS, DATA_DIR, UPLOADS_DIR
from core.llm.ollama_client import OllamaClient
from core.memory.mempalace import MemPalace
from core.storage.database import WarehouseDB
from core.file_parser.manager import FileParserManager

# === Настройка логирования ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(DATA_DIR / 'bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# === Инициализация глобальных объектов ===
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
ollama = OllamaClient()
file_parser = FileParserManager()

# === Кэш для ускорения работы (Singleton) ===
_user_dbs: dict[int, WarehouseDB] = {}
_user_memories: dict[int, MemPalace] = {}


def get_user_db(user_id: int) -> WarehouseDB:
    if user_id not in _user_dbs:
        _user_dbs[user_id] = WarehouseDB(user_id)
    return _user_dbs[user_id]


def get_user_memory(user_id: int) -> MemPalace:
    if user_id not in _user_memories:
        _user_memories[user_id] = MemPalace(user_id)
    return _user_memories[user_id]


# ==========================================
# 📂 ОБРАБОТЧИК ФАЙЛОВ
# ==========================================

@dp.message(F.document)
async def handle_document(msg: types.Message):
    doc = msg.document

    # 1. Проверка размера
    if doc.file_size > 10 * 1024 * 1024:
        await msg.answer("❌ Файл слишком большой (макс. 10 МБ)")
        return

    # 2. Проверка формата
    if not file_parser.is_supported(doc.file_name):
        supported = ', '.join(FileParserManager.SUPPORTED_EXTENSIONS.keys())
        await msg.answer(f"❌ Формат не поддерживается. Доступно: {supported}")
        return

    # 3. Индикатор загрузки
    status_msg = await msg.answer("📥 Файл получен, начинаю анализ...")

    # 4. Скачивание файла
    file = await bot.get_file(doc.file_id)
    file_path = UPLOADS_DIR / f"{msg.from_user.id}_{doc.file_name}"
    await bot.download_file(file.file_path, file_path)

    # 5. Анимация прогресса
    steps = ["🔍 Читаю файл...", "🧠 Анализирую структуру...", "🗂️ Извлекаю данные...", "✨ Почти готово..."]
    for step in steps:
        await status_msg.edit_text(step)
        await asyncio.sleep(0.8)

    # 6. Парсинг файла
    result = await file_parser.parse_file(file_path)

    if result['errors']:
        await status_msg.edit_text(f"⚠️ Ошибки при чтении:\n" + "\n".join(result['errors']))
        return

    # 7. Классификация и превью
    classified = file_parser.classify_items(result['items'])
    preview = file_parser.generate_preview(result['items'])

    response = (
        f"✅ <b>Файл обработан!</b>\n\n"
        f"📊 Найдено:\n"
        f"• 📦 Товаров: {len(classified['products'])}\n"
        f"• 🏢 Поставщиков: {len(classified['suppliers'])}\n\n"
        f"<b>Превью:</b>\n{preview}\n\n"
        f"✅ <i>Напишите 'Да', чтобы сохранить всё в базу.</i>"
    )

    await status_msg.edit_text(response, parse_mode="HTML")

    # 8. Очистка временного файла
    try:
        file_path.unlink()
    except:
        pass


# ==========================================
# 📜 КОМАНДЫ
# ==========================================

@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    user_id = msg.from_user.id
    get_user_db(user_id)
    get_user_memory(user_id)

    await msg.answer(
        "👋 <b>Привет! Я ИИ-помощник агентства ПридПром.</b>\n\n"
        "📌 <b>Мои задачи:</b>\n"
        "• 📦 Учет LED-компонентов (модули, БП, контроллеры)\n"
        "• 🏢 База поставщиков и цен\n"
        "• 🧠 Память о проектах и монтажах\n"
        "• 📎 Анализ файлов (прайсы, ТЗ)\n\n"
        "💡 <b>Примеры:</b>\n"
        '• "Модуль P3.9 450W IP65 цена 40р"\n'
        '• "Поставщик БелКрепеж +375291234567"\n'
        '• "Какие блоки питания есть на складе?"\n'
        '• "ВСПОМНИ проект на Ленина"\n\n'
        "📎 <b>Загрузите файл:</b> Отправьте мне прайс-лист (.xlsx, .csv) или ТЗ (.docx, .pdf)"
    )


@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    await msg.answer(
        "📚 <b>Справка:</b>\n\n"
        "📦 <b>Склад:</b>\n"
        "/my_products — список товаров\n"
        "/my_suppliers — список поставщиков\n\n"
        "🧠 <b>Система:</b>\n"
        "/memory — 📊 мониторинг объема памяти\n"
        "/admin — панель администратора\n\n"
        "📎 <b>Файлы:</b>\n"
        "Просто отправьте файл в чат, и я его проанализирую!"
    )


@dp.message(Command("memory"))
async def cmd_memory(msg: types.Message):
    user_id = msg.from_user.id
    memory = get_user_memory(user_id)
    stats = memory.get_stats()

    response_text = (
        f"🧠 <b>Мониторинг памяти (MemPalace)</b>\n\n"
        f"💾 <b>Объем хранилища:</b> {stats['storage_size_mb']} МБ\n"
        f"   • ChromaDB (смысл): ~{stats['storage_size_mb'] * 0.6:.1f} МБ\n"
        f"   • SQLite (факты): ~{stats['storage_size_mb'] * 0.4:.1f} МБ\n\n"
        f"📊 <b>Данные:</b>\n"
        f"   • 🔹 Фактов: {stats['total_facts']}\n"
        f"   • 💬 Диалогов: {stats['total_interactions']}\n"
        f"   • 🔍 Векторов: {stats['vector_count']}\n\n"
        f"📂 <b>Залы:</b>\n"
    )

    for hall, count in stats['facts_by_hall'].items():
        if hall == "hall_facts":
            emoji = "📝"
        elif hall == "hall_events":
            emoji = "⚡"
        elif hall == "hall_preferences":
            emoji = "❤️"
        else:
            emoji = "📦"
        response_text += f"   {emoji} {hall}: {count}\n"

    await msg.answer(response_text, parse_mode="HTML")


@dp.message(Command("admin"))
async def cmd_admin(msg: types.Message):
    if msg.from_user.id not in ADMIN_USER_IDS:
        await msg.answer("🚫 Доступ запрещён. Вы не в списке администраторов.")
        return

    stats = get_user_memory(msg.from_user.id).get_stats()
    await msg.answer(
        f"👨‍ <b>Админ-панель</b>\n\n"
        f"💬 Взаимодействий: {stats['total_interactions']}\n"
        f"📊 Фактов: {stats['total_facts']}\n"
        f"💾 Размер: {stats['storage_size_mb']} МБ"
    )


@dp.message(Command("my_products"))
async def cmd_my_products(msg: types.Message):
    db = get_user_db(msg.from_user.id)
    products = db.get_products()

    if not products:
        await msg.answer("📦 Склад пуст. Добавьте компоненты или загрузите прайс-лист!")
        return

    text = f"📦 <b>Склад (всего: {len(products)})</b>\n\n"
    for item in products[:10]:
        specs = item.get('specifications') or {}
        spec_str = ", ".join(f"{k}:{v}" for k, v in list(specs.items())[:2])
        text += f"• {item['name']}"
        if spec_str: text += f" ({spec_str})"
        if item.get('price'): text += f" — {item['price']} BYN"
        text += "\n"

    await msg.answer(text, parse_mode="HTML")


@dp.message(Command("my_suppliers"))
async def cmd_my_suppliers(msg: types.Message):
    db = get_user_db(msg.from_user.id)
    suppliers = db.get_suppliers()

    if not suppliers:
        await msg.answer("🏢 Нет поставщиков. Пример: 'Поставщик БелКрепеж +375291234567'.")
        return

    text = f"🏢 <b>Поставщики ({len(suppliers)})</b>\n\n"
    for s in suppliers[:10]:
        text += f"• <b>{s['name']}</b>\n"
        if s.get('phone'): text += f"  📞 {s['phone']}\n"
        text += "\n"

    await msg.answer(text, parse_mode="HTML")


# ==========================================
# 💬 ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ
# ==========================================

@dp.message()
async def handle_message(msg: types.Message):
    user_id = msg.from_user.id
    db = get_user_db(user_id)
    memory = get_user_memory(user_id)
    text = msg.text.lower().strip()

    # Индикатор "печатает..."
    await bot.send_chat_action(chat_id=msg.chat.id, action=ChatAction.TYPING)
    status_msg = await msg.answer("🧠 <i>Думаю...</i>", parse_mode="HTML")

    # 1. Режим "ВСПОМНИ" (Глубокий поиск в памяти)
    if text.startswith(('вспомни', 'помнишь', 'найди в памяти')):
        query = re.sub(r'^(вспомни|помнишь|найди в памяти)\s*[:\-]?\s*', '', text, flags=re.IGNORECASE).strip()
        if not query: query = text

        await status_msg.edit_text("🗄️ <i>Ищу в архивах...</i>", parse_mode="HTML")
        context = memory.deep_remember(query, top_k=15)
        response = ollama.generate(prompt=query, context=context)

        await msg.answer(f"{response}\n\n<small>🔍 Найдено записей: {context.count('[hall_')}</small>",
                         parse_mode="HTML")
        if status_msg: await status_msg.delete()
        return

    # 2. Авто-распознавание LED-компонентов
    led_keywords = ['модуль', 'блок питания', 'бп', 'контроллер', 'novastar', 'кабель', 'power', 'psu', 'p3.9', 'p4',
                    'p5']
    if any(kw in text for kw in led_keywords):
        detected = db.auto_detect_fields(msg.text)
        if detected.get('name') and len(detected['name']) > 2:
            db.add_product(
                name=detected['name'],
                category=detected.get('category', 'led_components'),
                price=detected.get('price'),
                specifications=detected.get('specifications'),
                auto_detect=True
            )
            await msg.answer(f"✅ <b>Компонент добавлен:</b> {detected['name']}", parse_mode="HTML")
            if status_msg: await status_msg.delete()
            return

    # 3. Авто-распознавание Поставщиков
    if any(kw in text for kw in ['поставщик', 'контакт', 'телефон', 'менеджер']):
        detected = db.auto_detect_fields(msg.text, category='supplier')
        if detected.get('name') and len(detected['name']) > 3:
            db.add_supplier(name=detected['name'], phone=detected.get('phone'))
            await msg.answer(f"✅ <b>Поставщик:</b> {detected['name']}", parse_mode="HTML")
            if status_msg: await status_msg.delete()
            return

    # 4. Обычный RAG запрос (Общение с ботом)
    context = memory.wake_up(msg.text, top_k=5)
    response = ollama.generate(prompt=msg.text, context=context)

    if status_msg: await status_msg.delete()
    await msg.answer(response, parse_mode="HTML")


# ==========================================
# 🚀 ЗАПУСК
# ==========================================

async def main():
    logger.info("🚀 Bot starting...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")