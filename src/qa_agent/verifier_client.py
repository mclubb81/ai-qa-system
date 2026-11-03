import httpx

from qa_agent.config import Settings


class VerifierClient:
    """Thin HTTP client for the qa-verifier Rust service (see verifier/)."""

    def __init__(self, base_url: str, timeout_seconds: float):
        self._base_url = base_url
        self._timeout = timeout_seconds

    async def verify(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/verify", json=payload)
            response.raise_for_status()
            return response.json()

    @classmethod
    def from_settings(cls, settings: Settings) -> "VerifierClient":
        return cls(settings.verifier_service_url, settings.verifier_timeout_seconds)
