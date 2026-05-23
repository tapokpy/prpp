import sqlite3
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from config import DATA_DIR

logger = logging.getLogger(__name__)


class WarehouseDB:
    """
    База данных склада метизов (SQLite).
    Поддерживает гибкую структуру данных через JSON и авто-миграции.
    """

    def __init__(self, user_id: int):
        """
        Инициализация базы данных для конкретного пользователя.
        Создаёт отдельные файлы БД для каждого пользователя.
        """
        self.user_id = user_id
        # Путь к файлу базы данных в папке data
        self.db_path = DATA_DIR / f"warehouse_{user_id}.db"

        # Инициализируем таблицы и запускаем миграции
        self._init_tables()
        self._migrate()

        logger.info(f"WarehouseDB initialized for user {user_id} at {self.db_path}")

    def _init_tables(self):
        """
        Создание основных таблиц, если они ещё не существуют.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. Таблица поставщиков (Suppliers)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                phone TEXT,
                email TEXT,
                address TEXT,
                contact_person TEXT,
                notes TEXT,
                additional_info JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Таблица категорий товаров (Categories)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                default_unit TEXT DEFAULT 'шт',
                schema_fields JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Таблица товаров (Products) - с JSON для характеристик
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category_id INTEGER,

                -- Основные поля
                sku TEXT UNIQUE,
                price REAL,
                currency TEXT DEFAULT 'BYN',
                stock_quantity REAL DEFAULT 0,
                unit TEXT DEFAULT 'шт',

                -- Гибкие характеристики в формате JSON
                characteristics JSON,

                -- Связи
                supplier_id INTEGER,
                project_id INTEGER,

                -- Метаданные
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (category_id) REFERENCES categories(id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            )
        """)

        # 4. Таблица проектов (Projects)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT,
                description TEXT,
                status TEXT DEFAULT 'active',
                budget REAL,
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 5. Таблица цен от поставщиков (Product Prices)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                supplier_id INTEGER NOT NULL,
                price REAL NOT NULL,
                currency TEXT DEFAULT 'BYN',
                min_order_qty REAL DEFAULT 1,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
                UNIQUE(product_id, supplier_id)
            )
        """)

        # Индексы для ускорения поиска
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name)")

        conn.commit()
        conn.close()

    def _migrate(self):
        """
        Автоматические миграции: добавление новых полей в существующие таблицы.
        Это позволяет обновлять бота без потери данных.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Список миграций: (таблица, колонка, SQL запрос добавления)
        migrations = [
            ("products", "characteristics", "ALTER TABLE products ADD COLUMN characteristics JSON"),
            ("products", "sku", "ALTER TABLE products ADD COLUMN sku TEXT"),
            ("products", "status", "ALTER TABLE products ADD COLUMN status TEXT DEFAULT 'active'"),
            ("suppliers", "additional_info", "ALTER TABLE suppliers ADD COLUMN additional_info JSON"),
            ("suppliers", "contact_person", "ALTER TABLE suppliers ADD COLUMN contact_person TEXT"),
            ("projects", "metadata", "ALTER TABLE projects ADD COLUMN metadata JSON"),
            ("projects", "budget", "ALTER TABLE projects ADD COLUMN budget REAL"),
            ("categories", "schema_fields", "ALTER TABLE categories ADD COLUMN schema_fields JSON")
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
                logger.warning(f"Migration skipped or error ({table}.{column}): {e}")

        conn.commit()
        conn.close()

    # ==========================================
    #  МЕТОДЫ ДЛЯ ПОСТАВЩИКОВ
    # ==========================================

    def add_supplier(self, name: str, phone: str = None, email: str = None,
                     address: str = None, contact_person: str = None,
                     notes: str = None, additional_info: Dict = None) -> int:
        """Добавить нового поставщика."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO suppliers (name, phone, email, address, contact_person, notes, additional_info)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, phone, email, address, contact_person, notes, json.dumps(additional_info or {})))

            supplier_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Added supplier: {name} (ID: {supplier_id})")
            return supplier_id
        except sqlite3.IntegrityError:
            # Если поставщик уже есть, можно обновить данные (опционально)
            logger.info(f"Supplier '{name}' already exists.")
            return self.get_supplier_id_by_name(name)
        finally:
            conn.close()

    def get_supplier_id_by_name(self, name: str) -> int:
        """Получить ID поставщика по имени."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM suppliers WHERE name = ?", (name,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def get_suppliers(self, search: str = None) -> List[Dict]:
        """Получить список поставщиков (с поиском)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if search:
            cursor.execute("""
                SELECT * FROM suppliers 
                WHERE name LIKE ? OR phone LIKE ? OR notes LIKE ?
                ORDER BY name
            """, (f'%{search}%', f'%{search}%', f'%{search}%'))
        else:
            cursor.execute("SELECT * FROM suppliers ORDER BY name")

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    # ==========================================
    # 📦 МЕТОДЫ ДЛЯ ТОВАРОВ
    # ==========================================

    def add_product(self, name: str, category: str = None,
                    price: float = None, characteristics: Dict = None,
                    supplier_id: int = None, stock_quantity: float = 0,
                    sku: str = None, unit: str = 'шт',
                    auto_detect: bool = True) -> int:
        """
        Добавить товар.
        auto_detect=True позволяет извлекать параметры из названия, если они не переданы явно.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Если включено авто-определение, пробуем разобрать название
        if auto_detect and name:
            detected = self.auto_detect_fields(name, category or 'product')

            # Если характеристики не были переданы явно, берем из авто-детекта
            if not characteristics:
                characteristics = detected.get('characteristics')

            # Если цена не была передана, берем из авто-детекта
            if price is None:
                price = detected.get('price')

            # Определяем категорию, если не указана
            if not category:
                category = detected.get('category')

        # Получаем или создаем категорию
        category_id = None
        if category:
            category_id = self.get_or_create_category(category)

        # Генерируем SKU (артикул), если нет
        if not sku and characteristics:
            sku_parts = ['ITEM']
            if characteristics.get('diameter'):
                sku_parts.append(str(characteristics['diameter']).replace('М', 'M'))
            if characteristics.get('length'):
                sku_parts.append(str(characteristics['length']).replace('мм', ''))
            sku = '-'.join(sku_parts)

        try:
            cursor.execute("""
                INSERT INTO products 
                (name, category_id, price, characteristics, supplier_id, stock_quantity, sku, unit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, category_id, price, json.dumps(characteristics or {}),
                  supplier_id, stock_quantity, sku, unit))

            product_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Added product: {name} (ID: {product_id})")
            return product_id
        except sqlite3.IntegrityError as e:
            logger.error(f"Error adding product {name}: {e}")
            raise
        finally:
            conn.close()

    def get_products(self, search: str = None, category: str = None,
                     supplier_id: int = None) -> List[Dict]:
        """Получить список товаров с фильтрами."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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
            query += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.characteristics LIKE ?)"
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

        if category:
            query += " AND c.name = ?"
            params.append(category)

        if supplier_id:
            query += " AND p.supplier_id = ?"
            params.append(supplier_id)

        query += " ORDER BY p.name"

        cursor.execute(query, params)
        results = []

        for row in cursor.fetchall():
            product = dict(row)
            # Преобразуем JSON строку обратно в словарь
            if product.get('characteristics'):
                product['characteristics'] = json.loads(product['characteristics'])
            results.append(product)

        conn.close()
        return results

    # ==========================================
    # 🛠 ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ==========================================

    def get_or_create_category(self, name: str) -> int:
        """Получить ID категории или создать её с предустановленными полями."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Ищем категорию
        cursor.execute("SELECT id FROM categories WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0]

        # Если нет — создаем
        # Предустановленные схемы для метизов
        default_schemas = {
            'болты': {'diameter': 'string', 'length': 'string', 'din': 'string'},
            'гайки': {'diameter': 'string', 'din': 'string'},
            'винты': {'diameter': 'string', 'length': 'string'},
            'шайбы': {'diameter': 'string'}
        }

        schema = default_schemas.get(name.lower())

        cursor.execute("""
            INSERT INTO categories (name, schema_fields)
            VALUES (?, ?)
        """, (name, json.dumps(schema or {})))

        cat_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return cat_id

    def auto_detect_fields(self, text: str, category_hint: str = None) -> Dict[str, Any]:
        """
        Автоматически извлекает данные из текста сообщения.
        Пример: "Болт М8х50 цена 5р" -> {name: "Болт М8х50", price: 5, characteristics: {...}}
        """
        detected = {
            'name': text,
            'price': None,
            'characteristics': {},
            'category': category_hint
        }

        # 1. Поиск цены (число, возможно с валютой)
        price_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:руб|byr|byn|р\.?|\$)?', text, re.IGNORECASE)
        if price_match:
            detected['price'] = float(price_match.group(1).replace(',', '.'))

        # 2. Поиск характеристик метизов
        chars = {}

        # Диаметр (М8, М10...)
        diam_match = re.search(r'[мМ](\d+(?:[.,]\d+)?)', text)
        if diam_match:
            chars['diameter'] = f"М{diam_match.group(1)}"

        # Длина (50мм, 50...)
        len_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:мм|mm)', text, re.IGNORECASE)
        if len_match:
            chars['length'] = f"{len_match.group(1)}мм"

        # DIN стандарт
        din_match = re.search(r'[Dd][Ii][Nn]\s*(\d+)', text)
        if din_match:
            chars['din'] = f"DIN{din_match.group(1)}"

        # Покрытие (оцинк, нерж)
        if re.search(r'оцинк|цинк|zinc', text, re.IGNORECASE):
            chars['coating'] = 'zinc'
        elif re.search(r'нерж|stainless', text, re.IGNORECASE):
            chars['material'] = 'stainless'

        detected['characteristics'] = chars

        # 3. Определение категории, если не передана
        if not category_hint:
            if 'болт' in text.lower():
                detected['category'] = 'болты'
            elif 'гайка' in text.lower():
                detected['category'] = 'гайки'
            elif 'винт' in text.lower():
                detected['category'] = 'винты'
            elif 'шайба' in text.lower():
                detected['category'] = 'шайбы'

        return detected

    # ==========================================
    #  МЕТОДЫ ДЛЯ ПРОЕКТОВ
    # ==========================================

    def add_project(self, name: str, location: str = None, description: str = None) -> int:
        """Добавить проект."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO projects (name, location, description)
            VALUES (?, ?, ?)
        """, (name, location, description))

        proj_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return proj_id

    def get_projects(self) -> List[Dict]:
        """Получить список проектов."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results