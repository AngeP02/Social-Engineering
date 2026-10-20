import copy
import json
import os

import anthropic
from clients.base_client import BaseClient, ModelResponse


class AnthropicClient(BaseClient):

    def __init__(self, model, api_key_env, temperature=0.0, max_tokens=5000):
        super().__init__(model, temperature, max_tokens)
        key = os.getenv(api_key_env)
        if not key:
            raise RuntimeError(
                f"Variabile d'ambiente mancante: {api_key_env}"
            )
        self.client = anthropic.Anthropic(api_key=key)

    def _clean_schema_for_anthropic(self, schema: dict) -> dict:
        cleaned = copy.deepcopy(schema)
        cleaned.pop("$schema", None)
        return cleaned

    def send_prompt(self, prompt, schema=None):
        args = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        if schema:
            cleaned_schema = self._clean_schema_for_anthropic(schema)
            args["tools"] = [
                {
                    "name": "profile_extraction",
                    "description": "Restituisce il JSON strutturato conforme allo schema di profilazione.",
                    "input_schema": cleaned_schema,
                }
            ]
            args["tool_choice"] = {
                "type": "tool",
                "name": "profile_extraction",
            }
        try:
            r = self.client.messages.create(**args)
        except TypeError as e:
            if "unexpected keyword argument 'temperature'" in str(e):
                args.pop("temperature", None)
                r = self.client.messages.create(**args)
            else:
                raise e
        usage_data = (
            r.usage.model_dump()
            if hasattr(r, "usage") and r.usage
            else None
        )
        raw_response = (
            r.model_dump() if hasattr(r, "model_dump") else str(r)
        )

        for b in r.content:
            if getattr(b, "type", None) == "tool_use":
                return ModelResponse(
                    text=json.dumps(b.input, ensure_ascii=False),
                    model=self.model,
                    usage=usage_data,
                    raw_response=raw_response,
                )
        text_output = "\n".join(
            getattr(b, "text", "")
            for b in r.content
            if getattr(b, "type", None) == "text"
        )
        return ModelResponse(
            text=text_output,
            model=self.model,
            usage=usage_data,
            raw_response=raw_response,
        )