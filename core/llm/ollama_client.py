import requests
import logging
from config import OLLAMA_HOST, QWEN_MODEL

logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(self, host: str = None, model: str = None):
        self.host = host or OLLAMA_HOST
        self.model = model or QWEN_MODEL
        self.timeout = 120

    def generate(self, prompt: str, context: str = "", temperature: float = 0.2) -> str:
        full_prompt = f"{context}\n\nВопрос: {prompt}\nОтвет:" if context else prompt

        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": temperature}
                },
                timeout=self.timeout
            )
            return response.json().get("response", "❌ Ошибка")
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return f"⚠️ Ошибка: {str(e)}"
