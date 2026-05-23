# Импортируем модуль asyncio для асинхронной работы бота
import asyncio
# Импортируем модуль logging для ведения логов работы бота
import logging
# Импортируем модуль Path для работы с путями к файлам и папкам
from pathlib import Path
# Импортируем модуль sys для изменения системных путей Python
import sys
# Импортируем модуль re для работы с регулярными выражениями (поиск текста)
import re
# Импортируем модуль time для замеров времени выполнения операций
import time

# === Настройка путей ===

# Вставляем корневую папку проекта в системный путь Python,
# чтобы импорты работали корректно (например, import config)
# Path(__file__) — путь к текущему файлу (main.py)
# .parent.parent — поднимаемся на 2 уровня вверх (bot -> prpp)
sys.path.insert(0, str(Path(__file__).parent.parent))

# === Импорты библиотек Aiogram ===

# Импортируем основные классы бота и диспетчера из Aiogram
from aiogram import Bot, Dispatcher, types
# Импортируем фильтр команд (для обработки /start, /help и т.д.)
from aiogram.filters import Command
# Импортируем тип ChatAction для отправки статуса "печатает..."
from aiogram.types import ChatAction

# === Импорты из вашего проекта ===

# Импортируем конфигурацию (токены, ID админов, пути)
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_IDS, DATA_DIR
# Импортируем клиент для общения с нейросетью Ollama
from core.llm.ollama_client import OllamaClient
# Импортируем систему памяти MemPalace (RAG + ChromaDB)
from core.memory.mempalace import MemPalace
# Импортируем класс базы данных склада (WarehouseDB)
# Убедитесь, что файл core/storage/database.py существует и содержит этот класс
from core.storage.database import WarehouseDB

# === Настройка логирования ===

# Настраиваем базовую конфигурацию логирования уровня INFO
logging.basicConfig(
    # Формат сообщения: Время - Имя логгера - Уровень - Сообщение
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    # Обработчики логов: в файл и в консоль
    handlers=[
        # Записываем логи в файл bot.log в папке data с кодировкой utf-8
        logging.FileHandler(DATA_DIR / 'bot.log', encoding='utf-8'),
        # Дублируем логи в стандартный вывод (консоль)
        logging.StreamHandler()
    ]
)
# Создаем экземпляр логгера для этого модуля
logger = logging.getLogger(__name__)

# === Инициализация глобальных объектов ===

# Создаем экземпляр Telegram бота с токеном из конфига
bot = Bot(token=TELEGRAM_BOT_TOKEN)
# Создаем диспетчер для обработки обновлений от Telegram
dp = Dispatcher()
# Создаем экземпляр клиента Ollama для генерации ответов
ollama = OllamaClient()

# === Кэширование экземпляров (Оптимизация скорости) ===

# Словарь для хранения экземпляров базы данных складов по ID пользователей
# Это нужно, чтобы не пересоздавать подключение к SQLite при каждом сообщении
_user_dbs: dict[int, WarehouseDB] = {}
# Словарь для хранения экземпляров памяти пользователей
_user_memories: dict[int, MemPalace] = {}

def get_user_db(user_id: int) -> WarehouseDB:
    """
    Функция для получения или создания базы данных склада для пользователя.
    Это паттерн Singleton для каждого пользователя.
    """
    # Проверяем, есть ли уже база для этого пользователя в кэше
    if user_id not in _user_dbs:
        # Если нет — создаем новый экземпляр и кладем в словарь
        _user_dbs[user_id] = WarehouseDB(user_id)
        # Пишем лог о создании
        logger.info(f"Created WarehouseDB for user {user_id}")
    # Возвращаем существующий или только что созданный экземпляр
    return _user_dbs[user_id]

def get_user_memory(user_id: int) -> MemPalace:
    """
    Функция для получения или создания системы памяти пользователя.
    """
    # Проверяем кэш памяти
    if user_id not in _user_memories:
        # Создаем новую память и сохраняем в кэш
        _user_memories[user_id] = MemPalace(user_id)
        logger.info(f"Created MemPalace for user {user_id}")
    # Возвращаем экземпляр памяти
    return _user_memories[user_id]

# === Обработчики команд ===

@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    """
    Обработчик команды /start.
    Приветствует пользователя и инициализирует его базы данных.
    """
    # Получаем ID пользователя из сообщения
    user_id = msg.from_user.id
    # Инициализируем базу данных склада (чтобы она была готова к работе)
    get_user_db(user_id)
    # Инициализируем систему памяти (загружаем ChromaDB и SQLite)
    get_user_memory(user_id)

    # Отправляем приветственное сообщение с описанием возможностей
    await msg.answer(
        # HTML-разметка для жирного текста (<b>)
        "👋 <b>Привет! Я ваш ИИ-помощник для управления складом метизов.</b>\n\n"
        # Описание возможностей с эмодзи
        "📌 <b>Что я умею:</b>\n"
        "• 🧠 Запоминаю разговоры и извлекаю информацию (RAG)\n"
        "• 📦 Автоматически распознаю товары: болты, гайки, винты...\n"
        "• 🏢 Сохраняю поставщиков и контакты\n"
        "• 🔍 Отвечаю на вопросы по вашей базе знаний\n"
        "• 📊 Отправляю уведомления об изменениях цен и остатков\n\n"
        "📝 <b>Примеры использования:</b>\n"
        # Примеры ввода данных естественным языком
        '• "Болт М8х50 оцинкованный, цена 5.5 руб" — добавит товар\n'
        '• "Поставщик БелКрепеж +375291234567" — сохранит контакт\n'
        '• "Какие болты М8 есть в наличии?" — поиск по базе\n'
        '• "Напомни заказать гайки" — создаст напоминание\n\n'
        "🔧 <b>Команды:</b>\n"
        "/help — справка по командам\n"
        "/my_products — мои товары\n"
        "/my_suppliers — мои поставщики\n"
        "/stats — статистика памяти"
    )

@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    """
    Обработчик команды /help.
    Показывает список доступных команд.
    """
    await msg.answer(
        "📚 <b>Справка по командам:</b>\n\n"
        "<b>📦 Товары:</b>\n"
        "/my_products — список всех товаров\n"
        "/find_product <запрос> — поиск товара\n"
        "/add_product — добавить товар вручную (режим диалога)\n\n"
        "<b>🏢 Поставщики:</b>\n"
        "/my_suppliers — список поставщиков\n"
        "/find_supplier <имя> — найти поставщика\n"
        "/add_supplier — добавить поставщика (режим диалога)\n\n"
        "<b>🧠 Память:</b>\n"
        "/forget <тема> — удалить информацию по теме\n"
        "/export — экспортировать базу данных\n"
        "/stats — статистика хранилища\n\n"
        "<b>⚙️ Админ:</b>\n"
        "/admin — панель управления (только для админов)"
    )

@dp.message(Command("admin"))
async def cmd_admin(msg: types.Message):
    """
    Обработчик команды /admin.
    Показывает статистику памяти, но только для администраторов.
    """
    # Проверяем, есть ли ID пользователя в списке админов из конфига
    if msg.from_user.id not in ADMIN_USER_IDS:
        # Если нет — отказываем в доступе
        await msg.answer("❌ <b>Доступ запрещён.</b> Вы не в списке администраторов.")
        # Пишем предупреждение в лог о попытке несанкционированного доступа
        logger.warning(f"Unauthorized admin access attempt from user {msg.from_user.id}")
        # Прерываем выполнение функции
        return

    # Если пользователь админ — получаем статистику памяти
    stats = get_user_memory(msg.from_user.id).get_stats()

    # Отправляем сообщение со статистикой
    await msg.answer(
        f"‍💼 <b>Админ-панель</b>\n\n"
        f"📊 <b>Статистика памяти:</b>\n"
        f"• Взаимодействий: {stats['total_interactions']}\n"
        f"• Фактов в базе: {stats['total_facts']}\n"
        f"• Векторов (Chroma): {stats['vector_count']}\n"
        f"• Размер хранилища: {stats['storage_size_mb']} МБ\n\n"
        f"🗂 <b>Залы памяти:</b>\n" +
        # Формируем список залов и количества фактов в них
        "\n".join(f"• {hall}: {count}" for hall, count in stats['facts_by_hall'].items()) +
        "\n\n🔄 <i>Команды управления:</i>\n"
        "/cleanup — очистить старую память (>90 дней)\n"
        "/backup — создать резервную копию"
    )

@dp.message(Command("my_products"))
async def cmd_my_products(msg: types.Message):
    """
    Обработчик команды /my_products.
    Показывает список товаров из базы данных склада.
    """
    # Получаем базу данных пользователя
    db = get_user_db(msg.from_user.id)
    # Запрашиваем все товары из базы
    products = db.get_products()

    # Если товаров нет — сообщаем об этом
    if not products:
        await msg.answer("📦 У вас пока нет товаров в базе.\n"
                        "Напишите что-то вроде: <i>«Болт М8х50, цена 5 руб»</i> — и я добавлю!")
        # Прерываем функцию
        return

    # Создаем словарь для группировки товаров по категориям
    by_category = {}
    # Перебираем все товары
    for p in products:
        # Получаем название категории или ставим "Без категории"
        cat = p.get('category_name') or 'Без категории'
        # Если такой категории еще нет в словаре — создаем пустой список
        if cat not in by_category:
            by_category[cat] = []
        # Добавляем товар в список соответствующей категории
        by_category[cat].append(p)

    # Начинаем формировать текст сообщения с заголовком
    text = f"📦 <b>Ваши товары</b> (всего: {len(products)})\n\n"
    # Берем первые 5 категорий (чтобы сообщение не было слишком длинным)
    for category, items in list(by_category.items())[:5]:
        # Добавляем название категории жирным шрифтом
        text += f"🔹 <b>{category}</b>:\n"
        # Берем первые 3 товара из категории
        for item in items[:3]:
            # Получаем характеристики товара (словарь)
            chars = item.get('characteristics') or {}
            # Формируем строку характеристик: "diameter:M8, length:50мм"
            char_str = ", ".join(f"{k}:{v}" for k, v in list(chars.items())[:3])
            # Добавляем название товара
            text += f"  • {item['name']}"
            # Если есть характеристики — добавляем их в скобках
            if char_str:
                text += f" ({char_str})"
            # Если есть цена — добавляем её
            if item.get('price'):
                text += f" — {item['price']} {item.get('currency', 'BYN')}"
            # Переходим на новую строку
            text += "\n"
        # Если в категории больше 3 товаров — пишем "... и ещё N"
        if len(items) > 3:
            text += f"  ... и ещё {len(items) - 3}\n"
        # Пустая строка между категориями
        text += "\n"

    # Если категорий больше 5 — пишем об этом
    if len(by_category) > 5:
        text += f"📋 И ещё {len(by_category) - 5} категорий...\n"

    # Отправляем сформированное сообщение
    await msg.answer(text, parse_mode="HTML")

@dp.message(Command("my_suppliers"))
async def cmd_my_suppliers(msg: types.Message):
    """
    Обработчик команды /my_suppliers.
    Показывает список поставщиков.
    """
    # Получаем базу данных пользователя
    db = get_user_db(msg.from_user.id)
    # Запрашиваем всех поставщиков
    suppliers = db.get_suppliers()

    # Если поставщиков нет — предлагаем добавить
    if not suppliers:
        await msg.answer("🏢 Нет сохранённых поставщиков.\n"
                        "Напишите: <i>«Поставщик БелКрепеж +375291234567»</i>")
        return

    # Формируем заголовок сообщения
    text = f"🏢 <b>Поставщики</b> ({len(suppliers)}):\n\n"
    # Перебираем первые 10 поставщиков
    for s in suppliers[:10]:
        # Добавляем название поставщика жирным
        text += f"• <b>{s['name']}</b>\n"
        # Если есть телефон — добавляем с эмодзи
        if s.get('phone'):
            text += f"  📞 {s['phone']}\n"
        # Если есть email — добавляем с эмодзи
        if s.get('email'):
            text += f"  ✉️ {s['email']}\n"
        # Если есть заметки — добавляем первые 100 символов
        if s.get('notes'):
            text += f"   {s['notes'][:100]}{'...' if len(s['notes']) > 100 else ''}\n"
        # Пустая строка между поставщиками
        text += "\n"

    # Если поставщиков больше 10 — пишем об этом
    if len(suppliers) > 10:
        text += f"... и ещё {len(suppliers) - 10}\n"

    # Отправляем сообщение
    await msg.answer(text, parse_mode="HTML")

# === ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ ===

@dp.message()
async def handle_message(msg: types.Message):
    """
    Универсальный обработчик всех текстовых сообщений.
    Реализует логику:
    1. Проверка триггера "ВСПОМНИ" (глубокий поиск).
    2. Авто-распознавание товаров и поставщиков.
    3. RAG-ответ на обычные вопросы.
    4. Отображение статуса "мышления" бота.
    """
    # Получаем ID пользователя
    user_id = msg.from_user.id
    # Получаем базу данных склада
    db = get_user_db(user_id)
    # Получаем систему памяти
    memory = get_user_memory(user_id)

    # Приводим текст сообщения к нижнему регистру и убираем пробелы по краям
    text = msg.text.lower().strip()
    # Переменная для хранения сообщения со статусом (чтобы потом редактировать его)
    status_msg = None

    # === 1. Отображение статуса (Что думает бот) ===

    # Отправляем действие "печатает" в чат, чтобы пользователь видел активность
    await bot.send_chat_action(chat_id=msg.chat.id, action=ChatAction.TYPING)

    # Если сообщение длиннее 10 символов (не просто команда типа /start), показываем статус
    if len(text) > 10:
        # Отправляем сообщение "Анализирую запрос..." и сохраняем его объект в status_msg
        status_msg = await msg.answer("🔍 <i>Анализирую запрос...</i>", parse_mode="HTML")

    # Замеряем время начала обработки (для статистики)
    start_time = time.time()

    # === 2. Проверка триггера "ВСПОМНИ" (Долгосрочная память) ===

    # Проверяем, начинается ли сообщение с ключевых слов для глубокого поиска
    if text.startswith(('вспомни', 'помнишь', 'найди в памяти', 'что мы обсуждали')):
        # Если есть сообщение статуса — обновляем его текст
        if status_msg:
            await status_msg.edit_text("🗄️ <i>Глубокий поиск в архивах памяти...</i>", parse_mode="HTML")

        # Очищаем текст запроса от самого слова-триггера (например, убираем "Вспомни")
        # Используем регулярное выражение для удаления триггера в начале строки
        search_query = re.sub(
            r'^(вспомни|помнишь|найди в памяти|что мы обсуждали)\s*[:\-]?\s*',
            '',
            text,
            flags=re.IGNORECASE
        ).strip()

        # Если после очистки запрос пустой — используем весь исходный текст
        if not search_query:
            search_query = text

        # Вызываем метод deep_remember для поиска по всей базе с большим контекстом
        # top_k=15 означает, что ищем 15 наиболее релевантных записей
        context = memory.deep_remember(search_query, top_k=15)

        # Формируем специальный промпт для режима воспоминаний
        rag_prompt = (
            f"Ты помогаешь пользователю вспомнить информацию из ваших прошлых диалогов.\n"
            f"Контекст из памяти (хронологически):\n{context}\n\n"
            f"Вопрос пользователя: {search_query}\n"
            f"Дай точный ответ на основе найденных записей. "
            f"Если ничего не найдено — честно скажи об этом и предложи, что можно поискать."
        )

        # Генерируем ответ через Ollama, передавая пустой контекст (так как он уже в промпте)
        response = ollama.generate(prompt=rag_prompt, context="")

        # Считаем количество найденных фактов по маркеру [hall_ в контексте
        fact_count = context.count('[hall_')
        # Добавляем мета-информацию в конец ответа мелким шрифтом
        response = f"{response}\n\n<small>🔍 Найдено записей: {fact_count}</small>"

        # Если было сообщение статуса — удаляем его
        if status_msg:
            await status_msg.delete()

        # Отправляем итоговый ответ пользователю
        await msg.answer(response, parse_mode="HTML")

        # Сохраняем этот запрос как специальное взаимодействие в память
        memory.store_interaction(
            query=f"[REMEMBER] {text}",  # Помечаем запрос как поиск по памяти
            response=response,
            wing="memory_search",  # Крыло памяти: поиск
            room="deep_recall"     # Комната: глубокое воспоминание
        )
        # Возвращаемся, чтобы не выполнять остальной код (обычный RAG)
        return

    # === 3. Авто-распознавание типов данных ===

    # 🏢 Проверка на поставщика
    # Если в тексте есть слова, указывающие на поставщика
    if any(kw in text for kw in ['поставщик', 'контакт', 'телефон', 'компания', 'менеджер']):
        # Используем метод auto_detect_fields для извлечения данных из текста
        detected = db.auto_detect_fields(msg.text, category='supplier')

        # Если имя поставщика найдено и оно длиннее 3 символов
        if detected.get('name') and len(detected['name']) > 3:
            # Добавляем поставщика в базу данных
            supplier_id = db.add_supplier(
                name=detected['name'],
                phone=detected.get('phone'),
                email=detected.get('email'),
                # Если телефон не найден, сохраняем весь текст как заметку
                notes=msg.text if not detected.get('phone') else None
            )
            # Пишем лог об успешном добавлении
            logger.info(f"Auto-added supplier: {detected['name']} for user {user_id}")

            # Формируем ответ пользователю
            await msg.answer(
                f"✅ <b>Поставщик сохранён!</b>\n"
                f"🏢 {detected['name']}\n"
                f"📞 {detected.get('phone') or 'не указан'}\n"
                f"\n<i>Теперь можно добавлять товары от этого поставщика</i>",
                parse_mode="HTML"
            )
            # Сохраняем факт в память (RAG)
            memory.add_fact(
                subject=detected['name'],
                predicate="is_supplier",
                obj="active",
                wing="suppliers",
                room="contacts"
            )
            # Если было сообщение статуса — удаляем его
            if status_msg:
                await status_msg.delete()
            # Завершаем обработку
            return

    #  Проверка на товар (метизы)
    # Если в тексте есть слова, указывающие на товар
    elif any(kw in text for kw in ['болт', 'гайка', 'винт', 'шайба', 'шуруп', 'саморез', 'метиз', 'крепёж']):
        # Извлекаем данные о товаре
        detected = db.auto_detect_fields(msg.text, category='product')

        # Если имя товара найдено и длиннее 2 символов
        if detected.get('name') and len(detected['name']) > 2:
            # Определяем категорию товара на основе ключевых слов
            category = None
            if 'болт' in text:
                category = 'болты'
            elif 'гайка' in text:
                category = 'гайки'
            elif 'винт' in text:
                category = 'винты'
            elif 'шайба' in text:
                category = 'шайбы'

            # Добавляем товар в базу данных
            product_id = db.add_product(
                name=msg.text,  # Сохраняем исходный текст для лучшего поиска
                category=category,
                price=detected.get('price'),
                characteristics=detected.get('characteristics'),
                auto_detect=True  # Включаем авто-определение характеристик
            )

            logger.info(f"Auto-added product: {detected['name']} for user {user_id}")

            # Формируем строку с характеристиками для ответа
            chars = detected.get('characteristics') or {}
            # Соединяем характеристики в строку с переносами
            char_lines = "\n".join(f"  • {k}: {v}" for k, v in chars.items()) if chars else "  • стандартные"

            # Отправляем ответ об успешном добавлении
            await msg.answer(
                f"✅ <b>Товар добавлен в базу!</b>\n\n"
                f"📦 {detected['name']}\n"
                f"🔧 Характеристики:\n{char_lines}\n"
                f" Цена: {detected.get('price', 'не указана')} BYN\n"
                f"\n<i>Спросите «какие болты М8 есть?» — и я покажу</i>",
                parse_mode="HTML"
            )

            # Сохраняем факт в память для RAG
            memory.add_fact(
                subject=detected['name'],
                predicate="has_characteristics",
                obj=str(chars),
                wing="products",
                room=category or "general"
            )
            # Удаляем сообщение статуса
            if status_msg:
                await status_msg.delete()
            return

    # === 4. Обычный RAG запрос (если не товар и не поставщик) ===

    # Если есть сообщение статуса — обновляем его
    if status_msg:
        await status_msg.edit_text("🧠 <i>Ищу в памяти...</i>", parse_mode="HTML")

    # Замеряем время начала поиска
    search_start = time.time()
    # Получаем контекст из памяти (RAG)
    context = memory.wake_up(msg.text, top_k=5)
    # Считаем время поиска
    search_time = (time.time() - search_start) * 1000

    # Если есть сообщение статуса — показываем метрики поиска
    if status_msg:
        await status_msg.edit_text(
            f"🧠 Найдено контекста: {len(context)} симв.\n"
            f"⏱ Поиск: {search_time:.0f} мс\n"
            f"️ <i>Формирую ответ...</i>",
            parse_mode="HTML"
        )

    # Генерируем ответ через Ollama
    generate_start = time.time()
    response = ollama.generate(prompt=msg.text, context=context)
    generate_time = (time.time() - generate_start) * 1000

    # Считаем общее время ответа
    total_time = (time.time() - start_time) * 1000

    # Для админов показываем технические метрики перед ответом
    if status_msg and user_id in ADMIN_USER_IDS:
        await status_msg.edit_text(
            f"✅ <b>Ответ готов!</b>\n"
            f"🔍 Поиск: {search_time:.0f} мс | 🧠 Генерация: {generate_time:.0f} мс | ⏱ Всего: {total_time:.0f} мс",
            parse_mode="HTML"
        )
        # Ждем 1 секунду, чтобы админ успел прочитать
        await asyncio.sleep(1)
        # Удаляем сообщение статуса
        await status_msg.delete()
    elif status_msg:
        # Для обычных пользователей просто удаляем статус
        await status_msg.delete()

    # Сохраняем взаимодействие в память
    memory.store_interaction(
        query=msg.text,
        response=response,
        wing="chat",
        room="general",
        tokens_used=0,  # Заглушка, пока не считаем токены
        latency_ms=int(total_time)  # Сохраняем время ответа
    )

    # Отправляем ответ пользователю
    await msg.answer(response, parse_mode="HTML")

# === Функция запуска ===

async def main():
    """
    Основная функция запуска бота.
    """
    # Пишем лог о старте бота
    logger.info("🚀 Bot starting...")
    logger.info(f"Ollama host: {ollama.host}, model: {ollama.model}")

    # Удаляем вебхук, если он был настроен ранее (на случай перезапуска)
    # drop_pending_updates=True игнорирует сообщения, пришедшие пока бот был офлайн
    await bot.delete_webhook(drop_pending_updates=True)

    # Запускаем процесс поллинга (опроса Telegram API на наличие новых сообщений)
    await dp.start_polling(bot)

# === Точка входа ===

if __name__ == "__main__":
    try:
        # Запускаем асинхронную функцию main
        asyncio.run(main())
    except KeyboardInterrupt:
        # Если нажали Ctrl+C — пишем лог об остановке
        logger.info("Bot stopped by user")
    except Exception as e:
        # Если произошла ошибка — пишем ошибку в лог с трейсбеком
        logger.error(f"Bot crashed: {e}", exc_info=True)
