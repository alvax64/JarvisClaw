"""LLM client for text post-processing and translation."""

from __future__ import annotations

import os
from typing import Any

import httpx

from ultratype.config import LLMConfig, ProfileConfig, TranslationConfig, build_profile_context

# Provider endpoint defaults
_PROVIDER_ENDPOINTS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://localhost:11434/v1",
}


class LLMClient:
    """Async LLM client supporting multiple providers."""

    def __init__(self, config: LLMConfig, profile: ProfileConfig | None = None) -> None:
        self._config = config
        self._profile = profile or ProfileConfig()
        self._api_key = config.api_key or os.environ.get("ULTRATYPE_API_KEY", "")
        self._endpoint = config.endpoint or _PROVIDER_ENDPOINTS.get(config.provider, "")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> LLMClient:
        self._client = httpx.AsyncClient(timeout=self._config.timeout)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def post_process(self, text: str) -> str:
        """Apply correction prompt to transcribed text."""
        prompt = self._config.correction_prompt.format(
            profile_context=build_profile_context(self._profile),
        )
        return await self._complete(prompt, text)

    async def translate(
        self, text: str, translation_config: TranslationConfig
    ) -> str:
        """Apply translation prompt to text."""
        prompt = self._config.translation_prompt.format(
            source_language=translation_config.source_language,
            target_language=translation_config.target_language,
            profile_context=build_profile_context(self._profile),
        )
        return await self._complete(prompt, text)

    async def _complete(self, system_prompt: str, user_text: str) -> str:
        """Route to the correct provider API."""
        provider = self._config.provider.lower()
        if provider == "gemini":
            return await self._gemini(system_prompt, user_text)
        elif provider in ("openai", "ollama", "custom"):
            return await self._openai_compat(system_prompt, user_text)
        elif provider == "anthropic":
            return await self._anthropic(system_prompt, user_text)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

    async def _gemini(self, system_prompt: str, user_text: str) -> str:
        """Google Gemini API (generateContent)."""
        assert self._client is not None
        url = (
            f"{self._endpoint}/models/{self._config.model}:generateContent"
            f"?key={self._api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_text}]}],
            "generationConfig": {"temperature": 0.3},
        }

        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    async def _openai_compat(self, system_prompt: str, user_text: str) -> str:
        """OpenAI-compatible API (also works for Ollama)."""
        assert self._client is not None
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.3,
        }

        resp = await self._client.post(
            f"{self._endpoint}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    async def _anthropic(self, system_prompt: str, user_text: str) -> str:
        """Anthropic Messages API."""
        assert self._client is not None
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }

        payload = {
            "model": self._config.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_text}],
        }

        resp = await self._client.post(
            f"{self._endpoint}/messages",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"].strip()
