def is_rate_limit_error(provider: str, exc: BaseException) -> bool:
    """Classify a caught exception as a provider-native rate-limit error.
    Each SDK is imported lazily -- never required unless that provider is
    actually in play, same discipline as qa_agent.llm.get_llm.

    groq/openai/anthropic each have a dedicated RateLimitError (always
    HTTP 429 by construction). Google is different: langchain-google-genai
    depends on the unified `google-genai` SDK, not the older
    google-generativeai/google-api-core stack -- `google.genai.errors.
    ClientError` covers the whole 4xx range, so it additionally needs an
    explicit `.code == 429` check to avoid misclassifying e.g. a 400.
    """
    try:
        if provider == "groq":
            from groq import RateLimitError as GroqRateLimitError

            return isinstance(exc, GroqRateLimitError)
        if provider == "openai":
            from openai import RateLimitError as OpenAIRateLimitError

            return isinstance(exc, OpenAIRateLimitError)
        if provider == "anthropic":
            from anthropic import RateLimitError as AnthropicRateLimitError

            return isinstance(exc, AnthropicRateLimitError)
        if provider == "google":
            from google.genai.errors import ClientError

            return isinstance(exc, ClientError) and getattr(exc, "code", None) == 429
        if provider == "huggingface":
            from huggingface_hub.errors import HfHubHTTPError

            # Same situation as Google: HfHubHTTPError spans the whole 4xx
            # range (ChatHuggingFace/HuggingFaceEndpoint call through
            # huggingface_hub's InferenceClient, which raises this on any
            # non-2xx), so an explicit status-code check is required.
            return (
                isinstance(exc, HfHubHTTPError)
                and getattr(exc, "response", None) is not None
                and exc.response.status_code == 429
            )
    except ImportError:
        return False
    return False
