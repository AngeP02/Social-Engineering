import copy
import os
from openai import OpenAI
from clients.base_client import BaseClient, ModelResponse


class OpenAICompatibleClient(BaseClient):

    def __init__(
        self,
        model,
        api_key_env,
        base_url=None,
        temperature=0.0,
        max_tokens=5000,
    ):
        super().__init__(model, temperature, max_tokens)
        key = os.getenv(api_key_env)
        if not key:
            raise RuntimeError(
                f"Variabile d'ambiente mancante: {api_key_env}"
            )
        self.client = OpenAI(api_key=key, base_url=base_url)
        self.is_custom_provider = base_url is not None

    def _clean_schema_for_openai(self, schema: dict) -> dict:
        cleaned = copy.deepcopy(schema)
        cleaned.pop("$schema", None)
        return cleaned

    def send_prompt(self, prompt, schema=None):
        args = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if schema:
            if self.is_custom_provider:
                args["response_format"] = {"type": "json_object"}
            else:
                cleaned_schema = self._clean_schema_for_openai(schema)
                args["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "profile_extraction",
                        "strict": True,
                        "schema": cleaned_schema,
                    },
                }

        r = self.client.chat.completions.create(**args)
        usage = r.usage.model_dump() if r.usage else None

        return ModelResponse(
            text=r.choices[0].message.content or "",
            model=self.model,
            usage=usage,
            raw_response=r.model_dump(),
        )