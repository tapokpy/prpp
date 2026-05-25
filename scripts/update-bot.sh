#!/usr/bin/env bash
# ==============================================================================
# 📖 ИНСТРУКЦИЯ ПО ИСПОЛЬЗОВАНИЮ
# ==============================================================================
# 1. 📁 СОХРАНЕНИЕ В PYCHARM:
#    Сохраните этот файл в проекте по пути: prpp/scripts/update-bot.sh
#
# 2. 📤 ЗАГРУЗКА НА СЕРВЕР:
#    Откройте терминал в PyCharm или локально и выполните:
#    scp prpp/scripts/update-bot.sh root@45.139.78.176:/opt/prpp/scripts/
#
# 3. 🔐 ПРАВА ДОСТУПА:
#    Подключитесь к серверу и сделайте скрипт исполняемым:
#    sudo chmod +x /opt/prpp/scripts/update-bot.sh
#
# 4. 🚀 ЗАПУСК ОБНОВЛЕНИЯ:
#    sudo bash /opt/prpp/scripts/update-bot.sh
#
# 📌 ЧТО ДЕЛАЕТ СКРИПТ:
#    • Останавливает текущего бота
#    • Создаёт бэкап базы данных (/opt/prpp/data) и конфига (.env)
#    • Скачивает актуальный код с GitHub (https://github.com/tapokpy/prpp.git)
#    • Восстанавливает данные и конфиги после обновления кода
#    • Проверяет/пересоздаёт виртуальное окружение (.venv)
#    • Обновляет pip и устанавливает зависимости из requirements.txt
#    • Проверяет доступность Ollama
#    • Запускает бота через systemd (или выводит команду для ручного запуска)
# ==============================================================================

set -euo pipefail

# === НАСТРОЙКИ ===
REPO_URL="https://github.com/tapokpy/prpp.git"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="${PROJECT_DIR}/.venv"
DATA_DIR="${PROJECT_DIR}/data"
SERVICE_NAME="prpp-bot.service"
PYTHON_BIN="python3"
BACKUP_RETAIN_DAYS=7
LOG_FILE="/var/log/prpp-update.log"

# === ЦВЕТА И ФУНКЦИИ ВЫВОДА ===
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓]${NC} $1" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1" | tee -a "$LOG_FILE"; }
error() { echo -e "${RED}[✗]${NC} $1" >&2 | tee -a "$LOG_FILE"; exit 1; }
info()  { echo -e "${BLUE}[ℹ]${NC} $1" | tee -a "$LOG_FILE"; }

# === ИНИЦИАЛИЗАЦИЯ ЛОГИРОВАНИЯ ===
touch "$LOG_FILE"
chmod 644 "$LOG_FILE"
echo "" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
echo "Update started: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

log "🚀 Запуск скрипта обновления бота ПридПром..."
log "📂 Рабочая директория: $PROJECT_DIR"

# === 1. ПРОВЕРКА ПРАВ ROOT ===
if [[ $EUID -ne 0 ]]; then
    error "Запустите скрипт с правами root: sudo bash $0"
fi

# === 2. ПРОВЕРКА СВОБОДНОГО МЕСТА ===
FREE_SPACE=$(df -P "$PROJECT_DIR" | awk 'NR==2 {print $4}')
MIN_SPACE=1048576  # 1GB in KB
if [[ $FREE_SPACE -lt $MIN_SPACE ]]; then
    warn "⚠️  Мало свободного места: $((FREE_SPACE/1024)) MB (рекомендуется минимум 1GB)"
fi

# === 3. ПРОВЕРКА И УСТАНОВКА ЗАВИСИМОСТЕЙ ===
log "🔍 Проверка системных зависимостей..."
command -v git >/dev/null 2>&1 || error "Git не установлен. Выполните: apt install git"
command -v $PYTHON_BIN >/dev/null 2>&1 || error "Python3 не установлен. Выполните: apt install python3"

# Проверка python3-venv
if ! $PYTHON_BIN -m venv --help >/dev/null 2>&1; then
    warn "Пакет python3-venv не найден. Устанавливаю..."
    apt-get update -qq && apt-get install -y -qq python3.10-venv >/dev/null 2>&1 || error "Не удалось установить python3-venv"
    log "✅ python3-venv успешно установлен"
fi

SYSTEMCTL_AVAILABLE=false
if command -v systemctl >/dev/null 2>&1; then
    SYSTEMCTL_AVAILABLE=true
fi

# === 4. ОСТАНОВКА БОТА ===
if [[ "$SYSTEMCTL_AVAILABLE" == true ]] && systemctl list-unit-files | grep -q "$SERVICE_NAME"; then
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        log "🛑 Остановка сервиса $SERVICE_NAME..."
        systemctl stop "$SERVICE_NAME" || warn "Не удалось остановить сервис (возможно, уже остановлен)"
    fi
else
    warn "Systemd сервис '$SERVICE_NAME' не найден — пропускаем остановку"
fi

# === 5. БЭКАП ДАННЫХ (КРИТИЧНО ВАЖНО) ===
if [[ -d "$DATA_DIR" ]]; then
    BACKUP_NAME="${DATA_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
    log "💾 Создание бэкапа данных: $BACKUP_NAME"
    cp -a "$DATA_DIR" "$BACKUP_NAME" || error "Не удалось создать бэкап данных!"

    # Очистка старых бэкапов
    find "$(dirname "$BACKUP_NAME")" -maxdepth 1 -name "data_backup_*" -type d -mtime +$BACKUP_RETAIN_DAYS -exec rm -rf {} + 2>/dev/null || true
    log "🗑️ Старые бэкапы очищены (старше $BACKUP_RETAIN_DAYS дней)"
else
    warn "Папка данных $DATA_DIR не найдена — пропускаем бэкап"
    mkdir -p "$DATA_DIR"
fi

# Сохранение .env (секреты не коммитятся в git)
ENV_FILE="${PROJECT_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
    ENV_BACKUP="${PROJECT_DIR}/.env.backup_$(date +%s)"
    log "🔐 Сохранение .env: $ENV_BACKUP"
    cp "$ENV_FILE" "$ENV_BACKUP"
fi

# === 6. ОБНОВЛЕНИЕ КОДА С GITHUB ===
if [[ -d "$PROJECT_DIR/.git" ]]; then
    log "📥 Обновление кода через git pull..."
    cd "$PROJECT_DIR"

    # Сохраняем текущий коммит для возможного отката
    CURRENT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

    # Пробуем git pull
    if ! git fetch origin >/dev/null 2>&1; then
        warn "⚠️  Git fetch не удался. Проверяю подключение..."
        if ! git ping -c 1 github.com >/dev/null 2>&1; then
            error "Нет доступа к GitHub. Проверьте подключение к интернету."
        fi
    fi

    git reset --hard origin/main >/dev/null 2>&1 || warn "Локальные изменения сброшены"

    if git pull origin main >/dev/null 2>&1; then
        NEW_COMMIT=$(git rev-parse HEAD)
        if [[ "$CURRENT_COMMIT" != "$NEW_COMMIT" ]]; then
            log "✅ Код обновлён: $CURRENT_COMMIT → $NEW_COMMIT"
        else
            log "✅ Код актуален (последняя версия: $CURRENT_COMMIT)"
        fi
    else
        warn "⚠️  Git pull не удался, но продолжаем..."
    fi
else
    log "📥 Клонирование репозитория с нуля..."
    rm -rf "$PROJECT_DIR" 2>/dev/null || true
    git clone "$REPO_URL" "$PROJECT_DIR" || error "Ошибка клонирования репозитория!"
    cd "$PROJECT_DIR"
    log "✅ Репозиторий склонирован"
fi

# === 7. ВОССТАНОВЛЕНИЕ ДАННЫХ И КОНФИГОВ ===
if ls ${DATA_DIR}_backup_* 1>/dev/null 2>&1; then
    LATEST_DATA_BACKUP=$(ls -td ${DATA_DIR}_backup_* | head -n 1)
    log "🔄 Восстановление данных из: $LATEST_DATA_BACKUP"
    mkdir -p "$DATA_DIR"
    cp -a "$LATEST_DATA_BACKUP"/. "$DATA_DIR"/
    log "✅ Данные восстановлены"
fi

if [[ -f "${PROJECT_DIR}/.env.backup_"* ]]; then
    LATEST_ENV_BACKUP=$(ls -t "${PROJECT_DIR}/.env.backup_"* | head -n 1)
    log "🔐 Восстановление .env из: $LATEST_ENV_BACKUP"
    cp "$LATEST_ENV_BACKUP" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    log "✅ .env восстановлен"
elif [[ ! -f "$ENV_FILE" ]]; then
    error "⚠️  Файл .env не найден! Создайте его перед запуском бота."
fi

# === 8. ВИРТУАЛЬНОЕ ОКРУЖЕНИЕ И ЗАВИСИМОСТИ ===
if [[ ! -d "$VENV_DIR" ]] || [[ ! -f "$VENV_DIR/bin/activate" ]]; then
    log "🐍 Создание/восстановление виртуального окружения..."
    rm -rf "$VENV_DIR"
    $PYTHON_BIN -m venv "$VENV_DIR" || error "Не удалось создать virtualenv"
    log "✅ Venv создан"
else
    log "✅ Venv существует"
fi

log "📦 Обновление pip и установка зависимостей..."
source "$VENV_DIR/bin/activate"

# Исправление конфликта torch + setuptools
pip install --upgrade pip "setuptools<82" wheel --quiet --root-user-action=ignore 2>&1 | tee -a "$LOG_FILE"

if [[ -f "requirements.txt" ]]; then
    pip install -r requirements.txt --quiet --root-user-action=ignore 2>&1 | tee -a "$LOG_FILE" || error "Ошибка установки зависимостей из requirements.txt"
    log "✅ Зависимости установлены"
else
    warn "⚠️  requirements.txt не найден в корне проекта"
fi
deactivate

# === 9. ПРАВА ДОСТУПА ===
log "🔧 Настройка прав доступа..."
chown -R "$(id -un):$(id -gn)" "$PROJECT_DIR"
chmod -R 755 "$PROJECT_DIR"
[[ -f "$ENV_FILE" ]] && chmod 600 "$ENV_FILE"
[[ -d "${PROJECT_DIR}/logs" ]] && chmod 775 "${PROJECT_DIR}/logs"

# === 10. ПРОВЕРКА OLLAMA ===
log "🔍 Проверка доступности Ollama..."
if command -v curl >/dev/null 2>&1; then
    OLLAMA_HOST=$(grep OLLAMA_HOST "$ENV_FILE" 2>/dev/null | cut -d'=' -f2 || echo "http://localhost:11434")
    if curl -s --connect-timeout 5 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
        log "✅ Ollama доступна ($OLLAMA_HOST)"
    else
        warn "⚠️  Ollama недоступна ($OLLAMA_HOST). Убедитесь что сервис запущен!"
    fi
else
    warn "⚠️  curl не установлен, пропускаю проверку Ollama"
fi

# === 11. ЗАПУСК БОТА ===
if [[ "$SYSTEMCTL_AVAILABLE" == true ]]; then
    if [[ -f "/etc/systemd/system/$SERVICE_NAME" ]]; then
        log "🔄 Перезапуск systemd сервиса..."
        systemctl daemon-reload
        systemctl restart "$SERVICE_NAME" || error "Не удалось запустить сервис $SERVICE_NAME"
        systemctl enable "$SERVICE_NAME" 2>/dev/null || true

        sleep 2
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            log "✅ Бот успешно обновлён и запущен через systemd!"
        else
            error "❌ Бот не запустился. Проверьте логи: journalctl -u $SERVICE_NAME -n 50 --no-pager"
        fi
    else
        warn "⚠️  Файл сервиса systemd не найден. Запустите бота вручную:"
        log "👉 cd $PROJECT_DIR && source $VENV_DIR/bin/activate && python bot/main.py"
    fi
else
    warn "⚠️  systemctl недоступен. Запустите бота вручную:"
    log "👉 cd $PROJECT_DIR && source $VENV_DIR/bin/activate && python bot/main.py"
fi

# === 12. ФИНАЛЬНЫЙ ОТЧЁТ ===
echo ""
echo "==============================================================================="
echo "✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО УСПЕШНО"
echo "==============================================================================="
echo "📁 Проект: $PROJECT_DIR"
echo "🗄️  Данные: $DATA_DIR"
echo "🐍 Venv:   $VENV_DIR"
echo ""
echo "🔍 Быстрые команды:"
echo "  • Логи бота:     journalctl -u $SERVICE_NAME -f --no-pager"
echo "  • Статус:        systemctl status $SERVICE_NAME"
echo "  • Перезапуск:    systemctl restart $SERVICE_NAME"
echo "  • Остановка:     systemctl stop $SERVICE_NAME"
echo ""
echo "💡 Проверьте работу бота в Telegram командой /start"
echo "==============================================================================="

# Логирование завершения
echo "Update completed: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit 0