from langchain_core.language_models import BaseChatModel

from qa_agent.config import get_settings


def get_llm(provider: str | None = None, model: str | None = None) -> BaseChatModel:
    """Provider-agnostic chat model factory.

    Only imports the SDK for the selected provider, so e.g. langchain-openai
    never needs to be installed unless provider="openai" is actually used.
    """
    settings = get_settings()
    provider = (provider or settings.llm_provider).lower()

    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=model or settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=0,
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model or settings.google_model,
            api_key=settings.google_api_key,
            temperature=0,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model or settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            temperature=0,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
        )

    raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}")
