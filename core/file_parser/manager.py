# core/file_parser/manager.py
import logging
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

# Для работы с разными форматами файлов
try:
    import pandas as pd  # Excel/CSV
except ImportError:
    pd = None

try:
    import PyPDF2  # PDF (текстовые)
except ImportError:
    PyPDF2 = None

try:
    from docx import Document  # Word
except ImportError:
    Document = None

from config import DATA_DIR, UPLOADS_DIR

logger = logging.getLogger(__name__)


class FileParserManager:
    """
    Менеджер обработки файлов для бота ПридПром.
    Поддерживает: .txt, .csv, .xlsx, .pdf, .docx
    Извлекает данные о товарах, поставщиках, проектах.
    """

    SUPPORTED_EXTENSIONS = {
        '.txt': 'text',
        '.csv': 'csv',
        '.xlsx': 'excel',
        '.xls': 'excel',
        '.pdf': 'pdf',
        '.docx': 'word'
    }

    def __init__(self):
        self.upload_dir = UPLOADS_DIR
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        logger.info("FileParserManager initialized")

    def is_supported(self, filename: str) -> bool:
        """Проверка поддерживаемого формата"""
        ext = Path(filename).suffix.lower()
        return ext in self.SUPPORTED_EXTENSIONS

    def get_file_type(self, filename: str) -> Optional[str]:
        """Определение типа файла по расширению"""
        ext = Path(filename).suffix.lower()
        return self.SUPPORTED_EXTENSIONS.get(ext)

    async def parse_file(self, file_path: Path, file_type: str = None) -> Dict[str, Any]:
        """
        Основной метод парсинга файла.

        Args:
            file_path: Путь к файлу
            file_type: Тип файла (txt/csv/excel/pdf/word), если известен

        Returns:
            Dict с результатами парсинга:
            {
                'success': bool,
                'items': List[Dict],  # Извлечённые товары/данные
                'meta': Dict,          # Метаданные файла
                'errors': List[str]    # Ошибки парсинга
            }
        """
        result = {
            'success': False,
            'items': [],
            'meta': {
                'filename': file_path.name,
                'size_mb': round(file_path.stat().st_size / (1024 * 1024), 2),
                'parsed_at': datetime.now().isoformat()
            },
            'errors': []
        }

        if not file_type:
            file_type = self.get_file_type(file_path.name)

        if not file_type:
            result['errors'].append(f"Неподдерживаемый формат: {file_path.suffix}")
            return result

        try:
            if file_type == 'text':
                result['items'] = self._parse_text(file_path)
            elif file_type == 'csv':
                result['items'] = self._parse_csv(file_path)
            elif file_type == 'excel':
                result['items'] = self._parse_excel(file_path)
            elif file_type == 'pdf':
                result['items'] = self._parse_pdf(file_path)
            elif file_type == 'word':
                result['items'] = self._parse_word(file_path)

            result['success'] = len(result['items']) > 0 or True  # Даже пустой файл = успех парсинга
            logger.info(f"Parsed {file_path.name}: {len(result['items'])} items")

        except Exception as e:
            result['errors'].append(f"Ошибка парсинга: {str(e)}")
            logger.error(f"Parse error for {file_path}: {e}")

        return result

    def _parse_text(self, file_path: Path) -> List[Dict]:
        """Парсинг простого текстового файла"""
        items = []
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Простая эвристика: ищем строки с ценами
            item = self._extract_item_from_line(line)
            if item:
                items.append(item)

        return items

    def _parse_csv(self, file_path: Path) -> List[Dict]:
        """Парсинг CSV файла через pandas или вручную"""
        if pd is not None:
            try:
                df = pd.read_csv(file_path, encoding='utf-8')
                return df.to_dict(orient='records')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='cp1251')  # Для русских файлов
                return df.to_dict(orient='records')
            except Exception as e:
                logger.warning(f"Pandas CSV parse failed: {e}, falling back to manual")

        # Fallback: ручной парсинг
        items = []
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        if not lines:
            return items

        headers = [h.strip() for h in lines[0].split(',')]

        for line in lines[1:]:
            if not line.strip():
                continue
            values = [v.strip() for v in line.split(',')]
            if len(values) == len(headers):
                items.append(dict(zip(headers, values)))

        return items

    def _parse_excel(self, file_path: Path) -> List[Dict]:
        """Парсинг Excel файла"""
        if pd is None:
            return [{'error': 'pandas not installed for Excel parsing'}]

        try:
            # Читаем первый лист
            df = pd.read_excel(file_path, engine='openpyxl')
            # Очищаем колонки от пробелов
            df.columns = [str(col).strip() for col in df.columns]
            # Заполняем пустые значения
            df = df.fillna('')
            return df.to_dict(orient='records')
        except Exception as e:
            logger.error(f"Excel parse error: {e}")
            return [{'error': str(e)}]

    def _parse_pdf(self, file_path: Path) -> List[Dict]:
        """Парсинг текстового PDF (не сканов)"""
        if PyPDF2 is None:
            return [{'error': 'PyPDF2 not installed'}]

        items = []
        try:
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"

                # Разбиваем на строки и пытаемся извлечь товары
                for line in text.split('\n'):
                    line = line.strip()
                    if len(line) > 20:  # Пропускаем короткие строки
                        item = self._extract_item_from_line(line)
                        if item:
                            items.append(item)
        except Exception as e:
            logger.error(f"PDF parse error: {e}")
            items.append({'error': f'PDF parse failed: {str(e)}'})

        return items

    def _parse_word(self, file_path: Path) -> List[Dict]:
        """Парсинг Word документа"""
        if Document is None:
            return [{'error': 'python-docx not installed'}]

        items = []
        try:
            doc = Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])

            for line in text.split('\n'):
                line = line.strip()
                if len(line) > 20:
                    item = self._extract_item_from_line(line)
                    if item:
                        items.append(item)
        except Exception as e:
            logger.error(f"Word parse error: {e}")
            items.append({'error': f'Word parse failed: {str(e)}'})

        return items

    def _extract_item_from_line(self, line: str) -> Optional[Dict]:
        """
        Простая эвристика для извлечения товара из строки.
        Пример: "Модуль P3.9 450W IP65 — 42 руб"
        """
        item = {'raw': line}

        # Поиск цены
        price_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:руб|byr|byn|р\.?|\$)?', line, re.IGNORECASE)
        if price_match:
            item['price'] = float(price_match.group(1).replace(',', '.'))
            item['currency'] = 'BYN' if 'by' in line.lower() or 'р' in line.lower() else 'USD'

        # Поиск характеристик LED
        pitch = re.search(r'[pP](\d+\.?\d*)', line)
        if pitch:
            item['specifications'] = item.get('specifications', {})
            item['specifications']['pixel_pitch'] = f"P{pitch.group(1)}"

        ip_match = re.search(r'(IP\d+)', line, re.IGNORECASE)
        if ip_match:
            item['specifications'] = item.get('specifications', {})
            item['specifications']['ip_rating'] = ip_match.group(1).upper()

        # Определение категории
        line_lower = line.lower()
        if any(w in line_lower for w in ['модуль', 'матрица', 'панель']):
            item['category'] = 'led_modules'
        elif any(w in line_lower for w in ['блок питания', 'бп', 'power', 'psu']):
            item['category'] = 'power_supplies'
        elif any(w in line_lower for w in ['контроллер', 'controller']):
            item['category'] = 'controllers'

        # Название — всё, что не цена и не характеристики
        if 'raw' in item:
            # Простая очистка: убираем цену и известные ключевые слова
            name = re.sub(r'\s*\d+[.,]?\d*\s*(?:руб|byr|byn|р\.?|\$)?', '', item['raw'], flags=re.IGNORECASE)
            name = re.sub(r'\s*IP\d+\s*', ' ', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*[pP]\d+\.?\d*\s*', ' ', name)
            item['name'] = name.strip()

        # Возвращаем только если нашли хотя бы название или цену
        if item.get('name') or item.get('price'):
            return item
        return None

    def classify_items(self, items: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Классификация извлечённых элементов по типам.

        Returns:
            {
                'products': [...],
                'suppliers': [...],
                'projects': [...],
                'unknown': [...]
            }
        """
        classified = {
            'products': [],
            'suppliers': [],
            'projects': [],
            'unknown': []
        }

        for item in items:
            if item.get('category') in ['led_modules', 'power_supplies', 'controllers', 'cables']:
                classified['products'].append(item)
            elif item.get('phone') or item.get('email') or 'поставщик' in item.get('raw', '').lower():
                classified['suppliers'].append(item)
            elif any(kw in item.get('raw', '').lower() for kw in ['проект', 'объект', 'заказ']):
                classified['projects'].append(item)
            else:
                classified['unknown'].append(item)

        return classified

    def generate_preview(self, items: List[Dict], limit: int = 5) -> str:
        """Генерация текстового превью для показа пользователю"""
        if not items:
            return "📭 Пустой файл или не удалось извлечь данные"

        preview = []
        for item in items[:limit]:
            name = item.get('name', item.get('raw', 'Без названия')[:50])
            price = item.get('price')
            specs = item.get('specifications', {})

            line = f"• {name}"
            if specs:
                spec_str = ", ".join(f"{k}:{v}" for k, v in list(specs.items())[:2])
                line += f" ({spec_str})"
            if price:
                line += f" — {price} {item.get('currency', 'BYN')}"
            preview.append(line)

        if len(items) > limit:
            preview.append(f"... и ещё {len(items) - limit}")

        return "\n".join(preview)