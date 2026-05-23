# core/storage/database.py
import sqlite3
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from config import DATA_DIR

# ✅ Исправлено: используем __name__ вместо name
logger = logging.getLogger(__name__)


class WarehouseDB:
    """
    База данных склада компонентов для LED-экранов (SQLite).
    Адаптирована под специфику ПридПром: модули, блоки питания, контроллеры.
    """

    def __init__(self, user_id: int):
        """Инициализация базы данных для конкретного пользователя."""
        self.user_id = user_id
        # Каждый пользователь получает свою базу данных в папке data
        self.db_path = DATA_DIR / f"warehouse_{user_id}.db"

        # Создаем структуру таблиц при первом запуске
        self._init_tables()
        self._migrate()  # Проверка обновлений структуры

        logger.info(f"WarehouseDB initialized for user {user_id} at {self.db_path}")

    def _init_tables(self):
        """Создание основных таблиц, если их еще нет."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. Таблица категорий (Модули, Блоки питания, Каркасы...)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                schema_fields TEXT,  -- Храним JSON как текст
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Таблица поставщиков
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                phone TEXT,
                email TEXT,
                address TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Таблица товаров (Компонентов)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT UNIQUE,          -- Артикул
                category_id INTEGER,

                -- Основные данные
                price REAL,
                currency TEXT DEFAULT 'BYN',
                stock_quantity REAL DEFAULT 0,
                unit TEXT DEFAULT 'шт',

                -- Специфичные характеристики (в формате JSON TEXT)
                -- Пример: {"pixel_pitch": "P3.9", "power": "450W", "ip_rating": "IP65"}
                specifications TEXT, 

                -- Связи
                supplier_id INTEGER,

                -- Мета
                status TEXT DEFAULT 'active', -- active, low_stock, discontinued
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (category_id) REFERENCES categories(id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            )
        """)

        # Индексы для быстрого поиска
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id)")

        conn.commit()
        conn.close()

    def _migrate(self):
        """Автоматическое обновление структуры базы (добавление новых колонок)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        migrations = [
            ("products", "specifications", "ALTER TABLE products ADD COLUMN specifications TEXT"),
            ("products", "sku", "ALTER TABLE products ADD COLUMN sku TEXT"),
            ("categories", "schema_fields", "ALTER TABLE categories ADD COLUMN schema_fields TEXT")
        ]

        for table, column, sql in migrations:
            try:
                # Проверяем, существует ли колонка
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [row[1] for row in cursor.fetchall()]
                if column not in columns:
                    cursor.execute(sql)
                    logger.info(f"Migration applied: Added '{column}' to '{table}'")
            except Exception as e:
                pass  # Игнорируем ошибки миграции, если колонка уже есть

        conn.commit()
        conn.close()

    # ==========================================
    #  МЕТОДЫ ДЛЯ ТОВАРОВ (КОМПОНЕНТОВ)
    # ==========================================

    def add_product(self, name: str, category: str = None,
                    price: float = None, specifications: Dict = None,
                    supplier_id: int = None, stock_quantity: float = 0,
                    sku: str = None, unit: str = 'шт',
                    auto_detect: bool = True) -> int:
        """
        Добавить товар на склад.
        auto_detect=True позволяет боту самому вытащить цену и характеристики из названия.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. Автоматическое распознавание (если включено)
        if auto_detect and name:
            detected = self.auto_detect_fields(name, category)
            if not specifications:
                specifications = detected.get('specifications')
            if price is None:
                price = detected.get('price')
            if not category:
                category = detected.get('category')

        # 2. Получаем или создаем категорию
        category_id = None
        if category:
            category_id = self.get_or_create_category(category)

        try:
            # ✅ Исправлено: преобразуем Dict в строку JSON для SQLite
            specs_json = json.dumps(specifications) if specifications else None

            cursor.execute("""
                INSERT INTO products 
                (name, category_id, price, specifications, supplier_id, stock_quantity, sku, unit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, category_id, price, specs_json,
                  supplier_id, stock_quantity, sku, unit))

            product_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Added product: {name} (ID: {product_id})")
            return product_id
        except sqlite3.IntegrityError as e:
            logger.error(f"Error adding product (duplicate?): {e}")
            return 0
        except Exception as e:
            logger.error(f"Database error: {e}")
            return 0
        finally:
            conn.close()

    def get_products(self, search: str = None, category: str = None) -> List[Dict]:
        """Получить список товаров с фильтрами."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Позволяет обращаться к колонкам по имени
        cursor = conn.cursor()

        query = """
            SELECT p.*, c.name as category_name, s.name as supplier_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.status = 'active'
        """
        params = []

        if search:
            # Ищем по названию, артикулу или внутри характеристик (текст JSON)
            query += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.specifications LIKE ?)"
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

        if category:
            query += " AND c.name = ?"
            params.append(category)

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            product = dict(row)
            # ✅ Исправлено: парсим JSON строку обратно в словарь
            if product.get('specifications'):
                try:
                    product['specifications'] = json.loads(product['specifications'])
                except json.JSONDecodeError:
                    product['specifications'] = {}
            results.append(product)

        conn.close()
        return results

    # ==========================================
    # 🏢 МЕТОДЫ ДЛЯ ПОСТАВЩИКОВ
    # ==========================================

    def add_supplier(self, name: str, phone: str = None, email: str = None, notes: str = None) -> int:
        """Добавить поставщика."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO suppliers (name, phone, email, notes)
                VALUES (?, ?, ?, ?)
            """, (name, phone, email, notes))
            supplier_id = cursor.lastrowid
            conn.commit()
            return supplier_id
        except sqlite3.IntegrityError:
            # Если уже есть, возвращаем его ID вместо ошибки
            cursor.execute("SELECT id FROM suppliers WHERE name = ?", (name,))
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def get_suppliers(self, search: str = None) -> List[Dict]:
        """Получить список поставщиков."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if search:
            cursor.execute("SELECT * FROM suppliers WHERE name LIKE ?", (f'%{search}%',))
        else:
            cursor.execute("SELECT * FROM suppliers")

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    # ==========================================
    #  ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ (КАТЕГОРИИ И ПАРСИНГ)
    # ==========================================

    def get_or_create_category(self, name: str) -> int:
        """Найти категорию или создать новую."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM categories WHERE name = ?", (name,))
        row = cursor.fetchone()

        if row:
            conn.close()
            return row[0]

        # Создаем новую категорию
        try:
            cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
            cat_id = cursor.lastrowid
            conn.commit()
            return cat_id
        except sqlite3.IntegrityError:
            conn.close()
            return self.get_or_create_category(name)  # Рекурсивно получим ID
        finally:
            conn.close()

    def auto_detect_fields(self, text: str, category_hint: str = None) -> Dict[str, Any]:
        """
        🧠 Умный парсер текста.
        Извлекает цену, название и специфичные для LED параметры из обычного текста.
        """
        detected = {
            'name': text,
            'price': None,
            'specifications': {},
            'category': category_hint
        }

        # 1. Поиск цены (число, возможно с валютой)
        # Ищет "45 руб", "100$", "5.5", "40р"
        price_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:руб|byr|byn|р\.?|\$|usd)?', text, re.IGNORECASE)
        if price_match:
            detected['price'] = float(price_match.group(1).replace(',', '.'))

        # 2. Поиск специфичных параметров LED-экранов

        # Pixel Pitch (P3.9, P2.5, 10mm)
        pitch_match = re.search(r'[pP](\d+\.?\d*)\b', text)
        if pitch_match:
            detected['specifications']['pixel_pitch'] = f"P{pitch_match.group(1)}"

        # Мощность (450W, 300 Вт)
        power_match = re.search(r'(\d+)\s*(?:w|вт|watt)', text, re.IGNORECASE)
        if power_match:
            detected['specifications']['power'] = f"{power_match.group(1)}W"

        # IP рейтинг (IP65, IP54)
        ip_match = re.search(r'(IP\d+)', text, re.IGNORECASE)
        if ip_match:
            detected['specifications']['ip_rating'] = ip_match.group(1).upper()

        # Размер/Разрешение (500x500, 1000x500)
        size_match = re.search(r'(\d+)x(\d+)', text)
        if size_match:
            detected['specifications']['size_mm'] = f"{size_match.group(1)}x{size_match.group(2)}"

        # 3. Определение категории, если не указана
        text_lower = text.lower()
        if not category_hint:
            if any(w in text_lower for w in ['модуль', 'panel', 'экран', 'матрица']):
                detected['category'] = 'led_modules'
            elif any(w in text_lower for w in ['блок питания', 'power', 'psu', 'бп', 'драйвер']):
                detected['category'] = 'power_supplies'
            elif any(w in text_lower for w in ['контроллер', 'controller', 'novastar', 'colorlight']):
                detected['category'] = 'controllers'
            elif any(w in text_lower for w in ['кабель', 'cable', 'шлейф']):
                detected['category'] = 'cables'

        return detected