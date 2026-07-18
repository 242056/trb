import logging
from typing import Any

import httpx

from explainlaw.llm.json_utils import parse_json_lenient

logger = logging.getLogger(__name__)


class ChatClient:
    """OpenAI-compatible chat API client."""

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._client = httpx.Client(timeout=timeout)

    @property
    def available(self) -> bool:
        return bool(self._base_url)

    def chat(self, *, system: str, user: str, temperature: float = 0.1) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        response = self._client.post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def chat_json(self, *, system: str, user: str) -> dict[str, Any]:
        raw = self.chat(system=system, user=user, temperature=0.0)
        return parse_json_lenient(raw)
