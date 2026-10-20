import copy
import json
import os
import time

from openai import OpenAI, APIError

from clients.base_client import BaseClient, ModelResponse
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
_STRUCTURED_OUTPUT_MODELS: set[str] = set()


class OpenRouterClient(BaseClient):

    def __init__(
        self,
        model: str,
        api_key_env: str = "OPENROUTER_API_KEY",
        temperature: float = 0.0,
        max_tokens: int = 10000,
        site_url: str = "",
        app_name: str = "",
        max_retries: int = 3,
    ):
        super().__init__(model, temperature, max_tokens)
        self.max_retries = max_retries

        key = os.getenv(api_key_env)
        if not key:
            raise RuntimeError(
                f"Variabile d'ambiente mancante: {api_key_env}. "
                "Imposta OPENROUTER_API_KEY con la tua chiave da openrouter.ai."
            )

        extra_headers = {}
        if site_url:
            extra_headers["HTTP-Referer"] = site_url
        if app_name:
            extra_headers["X-Title"] = app_name

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=key,
            default_headers=extra_headers if extra_headers else None,
        )

    def _build_args(self, prompt: str, schema: dict | None) -> dict:
        args: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if schema:
            args["response_format"] = {"type": "json_object"}

        return args

    def send_chat(self, messages: list[dict], schema: dict | None = None) -> ModelResponse:
        args: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens":  self.max_tokens,
        }
        if schema:
            args["response_format"] = {"type": "json_object"}

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self.client.chat.completions.create(**args)
                content = r.choices[0].message.content or ""
                usage   = r.usage.model_dump() if r.usage else None
                return ModelResponse(
                    text=content,
                    model=self.model,
                    usage=usage,
                    raw_response=r.model_dump() if hasattr(r, "model_dump") else str(r),
                )
            except APIError as e:
                last_exc = e
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
        raise last_exc

    def send_prompt(self, prompt: str, schema: dict | None = None) -> ModelResponse:
        args = self._build_args(prompt, schema)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self.client.chat.completions.create(**args)
                content = r.choices[0].message.content or ""
                usage = r.usage.model_dump() if r.usage else None
                return ModelResponse(
                    text=content,
                    model=self.model,
                    usage=usage,
                    raw_response=r.model_dump() if hasattr(r, "model_dump") else str(r),
                )
            except APIError as e:
                last_exc = e
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))

        raise last_exc