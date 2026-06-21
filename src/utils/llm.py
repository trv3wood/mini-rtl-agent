from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, TypeVar

from dotenv import load_dotenv
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class ChatClient(Protocol):
    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        ...

    def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[StructuredModel],
        *,
        temperature: float = 0.0,
    ) -> StructuredModel:
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

    def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[StructuredModel],
        *,
        temperature: float = 0.0,
    ) -> StructuredModel:
        parser = PydanticOutputParser(pydantic_object=schema)
        prompted_messages = with_format_instructions(messages, parser.get_format_instructions())
        text = self.complete_text(prompted_messages, temperature=temperature)
        try:
            return parser.parse(text)
        except OutputParserException as exc:
            raise RuntimeError(f"LLM structured output failed validation: {exc}") from exc


def with_format_instructions(messages: list[dict[str, str]], instructions: str) -> list[dict[str, str]]:
    if not messages:
        return [{"role": "system", "content": instructions}]
    updated = [dict(message) for message in messages]
    updated[0]["content"] = f"{updated[0]['content']}\n\n{instructions}"
    return updated


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing LLM configuration: set {name} in .env or environment")
    return value
