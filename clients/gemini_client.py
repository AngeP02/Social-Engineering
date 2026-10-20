import os
import time
from openai import OpenAI, APIError  # Usiamo l'SDK di OpenAI compatibile con OpenRouter
from clients.base_client import BaseClient, ModelResponse


class GeminiClient(BaseClient):
    def __init__(self, model, api_key_env, temperature=0.0, max_tokens=5000):
        super().__init__(model, temperature, max_tokens)

        key = os.getenv(api_key_env)
        if not key:
            raise RuntimeError(f"Variabile d'ambiente mancante: {api_key_env}")
        self.client = OpenAI(
            base_url="https://openrouter.ai",
            api_key=key
        )

    def send_prompt(self, prompt, schema=None):
        cfg = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if schema:
            cfg["response_format"] = {
                "type": "json_object",
                "schema": schema
            }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                r = self.client.chat.completions.create(**cfg)
                content = r.choices[0].message.content or ""
                return ModelResponse(content, self.model, None, r)

            except APIError as e:
                if attempt == max_retries - 1:
                    raise e
                time.sleep(2 ** (attempt + 1))
