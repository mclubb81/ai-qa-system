from langchain_core.language_models import BaseChatModel

from qa_agent.config import Settings, get_effective_settings

_MODEL_FIELD_BY_PROVIDER = {
    "groq": "groq_model",
    "google": "google_model",
    "anthropic": "anthropic_model",
    "openai": "openai_model",
}


def resolve_llm_provider_and_model(
    provider: str | None, model: str | None, settings: Settings | None = None
) -> tuple[str, str]:
    """Single source of truth for provider/model fallback resolution, so
    callers that need the resolved values for logging (not just to build an
    LLM) don't have to duplicate get_llm's branching."""
    settings = settings or get_effective_settings()
    resolved_provider = (provider or settings.llm_provider).lower()
    model_field = _MODEL_FIELD_BY_PROVIDER.get(resolved_provider)
    resolved_model = model or (getattr(settings, model_field) if model_field else None)
    return resolved_provider, resolved_model or ""


def get_llm(
    provider: str | None = None, model: str | None = None, settings: Settings | None = None
) -> BaseChatModel:
    """Provider-agnostic chat model factory.

    Only imports the SDK for the selected provider, so e.g. langchain-openai
    never needs to be installed unless provider="openai" is actually used.
    """
    settings = settings or get_effective_settings()
    resolved_provider, resolved_model = resolve_llm_provider_and_model(provider, model, settings)
    # Cost control: cap response length per the configured provider_limits
    # scope, independent of rate limiting -- this is what actually bounds
    # spend once a provider is on a paid plan, not just a free tier.
    max_output_tokens = settings.provider_limits.get(f"{resolved_provider}:chat", {}).get(
        "max_output_tokens"
    )

    if resolved_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=resolved_model,
            api_key=settings.groq_api_key,
            temperature=0,
            max_tokens=max_output_tokens,
        )

    if resolved_provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=resolved_model,
            api_key=settings.google_api_key,
            temperature=0,
            max_output_tokens=max_output_tokens,
        )

    if resolved_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # ChatAnthropic requires an int max_tokens (its own default is
        # 1024) -- fall back to that same default when no cap is
        # configured, rather than passing None.
        return ChatAnthropic(
            model=resolved_model,
            api_key=settings.anthropic_api_key,
            temperature=0,
            max_tokens=max_output_tokens if max_output_tokens is not None else 1024,
        )

    if resolved_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=resolved_model,
            api_key=settings.openai_api_key,
            temperature=0,
            max_tokens=max_output_tokens,
        )

    raise ValueError(f"Unsupported LLM_PROVIDER: {resolved_provider!r}")
