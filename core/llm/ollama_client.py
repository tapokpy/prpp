# core/llm/ollama_client.py

import requests
import logging
from config import OLLAMA_HOST, QWEN_MODEL

# ✅ Исправлено: используем __name__ вместо name, чтобы избежать ошибки запуска
logger = logging.getLogger(__name__)

class OllamaClient:
    """
    Клиент для работы с локальным сервером Ollama.
    Отвечает за формирование промптов, отправку запросов к нейросети
    и получение ответов для бота.
    """

    def __init__(self, host: str = None, model: str = None):
        """
        Инициализация клиента нейросети.

        Args:
            host: Адрес сервера Ollama (по умолчанию localhost:11434)
            model: Название модели (например, qwen2.5:7b)
        """
        self.host = host or OLLAMA_HOST
        self.model = model or QWEN_MODEL
        self.timeout = 120  # Таймаут ответа в секундах (2 минуты)

        # 🧠 СИСТЕМНЫЙ ПРОМПТ (Role/Context)
        # Это самая важная часть для бизнеса. Мы задаем "роль" боту.
        # Без этого бот может начать вести себя как поэт или переводчик.
        # Здесь мы зашиваем знания о ПридПром и специфике LED-экранов.
        self.system_role = (
            "Ты — интеллектуальный технический помощник агентства ПридПром. "
            "Твоя специализация: производство и монтаж светодиодных экранов, "
            "управление складом компонентов (модули, контроллеры, блоки питания), "
            "работа с поставщиками и анализ ТЗ. "
            "Отвечай четко, по делу, используй профессиональную терминологию. "
            "Если информации нет — не выдумывай, а скажи, что нужно уточнить."
        )

    def generate(self, prompt: str, context: str = "", temperature: float = 0.2) -> str:
        """
        Генерация ответа нейросетью.

        Args:
            prompt: Вопрос пользователя (то, что он написал в чат)
            context: Контекст из памяти (факты, прошлые диалоги, цены из RAG)
            temperature: Креативность (0.0 - строгость, 1.0 - фантазия).
                         Для бизнеса и склада лучше ставить 0.1-0.3.

        Returns:
            Текстовый ответ от нейросети.
        """

        # 1. Собираем полный текст промпта
        # Структура: [Системная роль] + [Контекст из памяти] + [Вопрос пользователя]
        if context:
            full_prompt = (
                f"{self.system_role}\n\n"
                f"--- КОНТЕКСТ ИЗ ПАМЯТИ ---\n{context}\n"
                f"-----------------------------\n\n"
                f"Вопрос пользователя: {prompt}\n"
                f"Твой ответ:"
            )
        else:
            full_prompt = (
                f"{self.system_role}\n\n"
                f"Вопрос пользователя: {prompt}\n"
                f"Твой ответ:"
            )

        # 2. Формируем тело запроса для API Ollama
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,  # Ждем полный ответ сразу, а не по буквам
            "options": {
                "temperature": temperature  # Настраиваем "строгость"
            }
        }

        try:
            # 3. Отправляем запрос на сервер Ollama
            response = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=self.timeout
            )

            # 4. Проверяем успешность ответа HTTP
            response.raise_for_status()

            # 5. Возвращаем текст ответа
            # Ollama возвращает JSON, нам нужно поле "response"
            return response.json().get("response", "❌ Ошибка: пустой ответ от нейросети")

        except requests.exceptions.ConnectionError:
            # Эта ошибка возникает, если Ollama не запущена
            logger.error("❌ Не удалось подключиться к Ollama. Сервер запущен?")
            return "⚠️ Ошибка: Не могу связаться с сервером Ollama. Проверьте, запущена ли программа Ollama на компьютере."

        except requests.exceptions.Timeout:
            # Если модель думает слишком долго
            logger.error("❌ Таймаут запроса к Ollama.")
            return "⚠️ Ошибка: Нейросеть думает слишком долго. Попробуйте позже."

        except Exception as e:
            # Любые другие непредвиденные ошибки
            logger.error(f"❌ Ошибка генерации: {e}")
            return f"⚠️ Ошибка генерации ответа: {str(e)}"