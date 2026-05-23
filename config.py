import os
from dotenv import load_dotenv
from pathlib import Path

# Загружаем переменные из .env
load_dotenv()

# Секреты
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_IDS = [int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x]

# Ollama
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen2.5:7b")

# Пути
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))

# Создаем папки, если нет
MEMORY_DIR = DATA_DIR / "memory"
UPLOADS_DIR = DATA_DIR / "uploads"
BACKUPS_DIR = DATA_DIR / "backups"
LOGS_DIR = BASE_DIR / "logs"

for dir_path in [MEMORY_DIR, UPLOADS_DIR, BACKUPS_DIR, LOGS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)