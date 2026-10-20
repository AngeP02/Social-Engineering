from clients.openai_client import OpenAICompatibleClient

class DeepSeekClient(OpenAICompatibleClient):
    def __init__(self, model, api_key_env="DEEPSEEK_API_KEY", temperature=0.0, max_tokens=5000):
        super().__init__(
            model=model,
            api_key_env=api_key_env,
            base_url="https://api.deepseek.com",
            temperature=temperature,
            max_tokens=max_tokens,
        )


