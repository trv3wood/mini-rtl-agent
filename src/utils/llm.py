from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from dotenv import load_dotenv


class ChatClient(Protocol):
    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        ...

    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "LLMConfig":
        load_dotenv(".env")
        api_key = required_env("LLM_API_KEY")
        base_url = required_env("LLM_BASE_URL")
        model = required_env("LLM_MODEL")
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        )


class OpenAICompatibleLLM:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "missing Python dependency: install the project dependencies to use the real LLM client"
            ) from exc
        self.client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned empty content")
        return content.strip()

    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned empty JSON content")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("LLM JSON response must be an object")
        return payload


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing LLM configuration: set {name} in .env or environment")
    return value
