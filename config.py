import os
from dotenv import load_dotenv
from pathlib import Path

# Загружаем переменные из .env
load_dotenv()

# === Telegram Bot ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN не найден в .env")

ADMIN_USER_IDS = [int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x]

# === Ollama Configuration ===
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen2.5:7b")

# === Paths ===
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))

# Создаем необходимые папки
for dir_name in ["memory", "uploads", "backups", "logs"]:
    (DATA_DIR / dir_name).mkdir(parents=True, exist_ok=True)

MEMORY_DIR = DATA_DIR / "memory"
UPLOADS_DIR = DATA_DIR / "uploads"
BACKUPS_DIR = DATA_DIR / "backups"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# === File Processing ===
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 10))
ALLOWED_EXTENSIONS = {".txt", ".csv", ".xlsx", ".xls", ".pdf", ".docx"}

# === Business Context ===
COMPANY_NAME = "ПридПром"
LED_CATEGORIES = ["led_modules", "power_supplies", "controllers", "cables", "cabinets", "hardware"]