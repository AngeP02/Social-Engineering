from clients import OpenAICompatibleClient


class QwenClient(OpenAICompatibleClient):
    def __init__(self, model, api_key_env="DASHSCOPE_API_KEY", temperature=0.0, max_tokens=5000):
        super().__init__(
            model=model,
            api_key_env=api_key_env,
            # Per endpoint internazionali usa https://dashscope-intl.aliyuncs.com/compatible-mode/v1
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=temperature,
            max_tokens=max_tokens,
        )