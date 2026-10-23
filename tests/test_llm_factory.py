import pytest

from qa_agent.config import Settings
from qa_agent.llm import get_llm


def test_unsupported_provider_raises():
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        get_llm(provider="not-a-real-provider")


def test_groq_provider_builds_chat_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    from qa_agent.config import get_settings

    get_settings.cache_clear()
    llm = get_llm(provider="groq", model="llama-3.3-70b-versatile")
    assert llm.model_name == "llama-3.3-70b-versatile"


def test_max_output_tokens_from_provider_limits_is_passed_through():
    settings = Settings(
        groq_api_key="test-key",
        provider_limits={"groq:chat": {"max_output_tokens": 256}},
    )
    llm = get_llm(provider="groq", model="llama-3.3-70b-versatile", settings=settings)
    assert llm.max_tokens == 256


def test_no_max_output_tokens_configured_leaves_provider_default():
    settings = Settings(groq_api_key="test-key", provider_limits={})
    llm = get_llm(provider="groq", model="llama-3.3-70b-versatile", settings=settings)
    assert llm.max_tokens is None
