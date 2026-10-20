from clients.base_client import BaseClient, ModelResponse
from clients.openrouter_client import OpenRouterClient

# Client diretti (mantenuti per retrocompatibilità / uso senza OpenRouter)
from clients.openai_client import OpenAICompatibleClient
from clients.anthropic_client import AnthropicClient
from clients.gemini_client import GeminiClient
from clients.deepseek_client import DeepSeekClient
from clients.qwen_client import QwenClient


def get_client(cfg: dict) -> BaseClient:
    provider = cfg.get("provider", "openrouter")
    model = cfg["model"]
    api_key_env = cfg.get("api_key_env", "OPENROUTER_API_KEY")
    temperature = float(cfg.get("temperature", 0.0))
    max_tokens  = int(cfg.get("max_tokens", 10000))

    if provider == "openrouter":
        return OpenRouterClient(
            model=model,
            api_key_env=api_key_env,
            temperature=temperature,
            max_tokens=max_tokens,
            site_url=cfg.get("site_url", ""),
            app_name=cfg.get("app_name", ""),
        )
    if provider == "anthropic":
        return AnthropicClient(
            model=model,
            api_key_env=api_key_env,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if provider == "gemini":
        return GeminiClient(
            model=model,
            api_key_env=api_key_env,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if provider in ("openai", "openai_compatible"):
        return OpenAICompatibleClient(
            model=model,
            api_key_env=api_key_env,
            base_url=cfg.get("base_url"),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    raise ValueError(
        f"Provider '{provider}' non riconosciuto. "
        "Usa: openrouter | openai | openai_compatible | anthropic | gemini"
    )

__all__ = [
    "get_client",
    "BaseClient",
    "ModelResponse",
    "OpenRouterClient",
    "OpenAICompatibleClient",
    "AnthropicClient",
    "GeminiClient",
    "DeepSeekClient",
    "QwenClient",
]