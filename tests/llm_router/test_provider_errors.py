import pytest

from qa_agent.llm_router.provider_errors import is_rate_limit_error


def test_groq_rate_limit_error_is_classified():
    from groq import APIStatusError, RateLimitError

    exc = RateLimitError("rate limited", response=_fake_response(429), body=None)
    assert is_rate_limit_error("groq", exc)
    assert isinstance(exc, APIStatusError)


def test_anthropic_rate_limit_error_is_classified():
    from anthropic import RateLimitError

    exc = RateLimitError("rate limited", response=_fake_response(429), body=None)
    assert is_rate_limit_error("anthropic", exc)


def test_openai_rate_limit_error_is_classified():
    pytest.importorskip("openai")
    from openai import RateLimitError

    exc = RateLimitError("rate limited", response=_fake_response(429), body=None)
    assert is_rate_limit_error("openai", exc)


def test_google_429_client_error_is_classified():
    from google.genai.errors import ClientError

    exc = ClientError(429, {"error": {"message": "rate limited"}})
    assert is_rate_limit_error("google", exc)


def test_google_non_429_client_error_is_not_classified():
    from google.genai.errors import ClientError

    exc = ClientError(400, {"error": {"message": "bad request"}})
    assert not is_rate_limit_error("google", exc)


def test_huggingface_rate_limit_error_is_classified():
    pytest.importorskip("huggingface_hub")
    from huggingface_hub.errors import HfHubHTTPError

    exc = HfHubHTTPError("rate limited", response=_fake_response(429))
    assert is_rate_limit_error("huggingface", exc)


def test_huggingface_non_429_error_is_not_classified():
    pytest.importorskip("huggingface_hub")
    from huggingface_hub.errors import HfHubHTTPError

    exc = HfHubHTTPError("bad request", response=_fake_response(400))
    assert not is_rate_limit_error("huggingface", exc)


def test_unrelated_exception_is_not_classified():
    assert not is_rate_limit_error("groq", ValueError("not a rate limit"))
    assert not is_rate_limit_error("google", ValueError("not a rate limit"))


def test_unknown_provider_is_not_classified():
    assert not is_rate_limit_error("made-up-provider", ValueError("whatever"))


def _fake_response(status_code: int):
    import httpx

    return httpx.Response(status_code, request=httpx.Request("POST", "https://example.com"))
