from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser

from .llm import ChatClient, StructuredModel, with_format_instructions


@dataclass(frozen=True)
class LLMReplayConfig:
    record_path: Path | None = None
    replay_path: Path | None = None
    demo_freeze: bool = False


class RecordingReplayLLM:
    def __init__(self, inner: ChatClient | None, config: LLMReplayConfig) -> None:
        if config.record_path and config.replay_path:
            raise ValueError("--record-llm and --replay-llm are mutually exclusive")
        if config.replay_path and inner is not None:
            self.inner = None
        else:
            self.inner = inner
        self.config = config
        self.call_index = 0
        self._replay_records = _load_records(config.replay_path) if config.replay_path else []
        if config.record_path:
            config.record_path.parent.mkdir(parents=True, exist_ok=True)

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        return self._complete_raw(messages, parsed_artifact_type="text", temperature=temperature)

    def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[StructuredModel],
        *,
        temperature: float = 0.0,
    ) -> StructuredModel:
        parser = PydanticOutputParser(pydantic_object=schema)
        prompted_messages = with_format_instructions(messages, parser.get_format_instructions())
        raw = self._complete_raw(
            prompted_messages,
            parsed_artifact_type=schema.__name__,
            temperature=temperature,
        )
        try:
            return parser.parse(raw)
        except OutputParserException as exc:
            raise RuntimeError(f"LLM structured output failed validation: {exc}") from exc

    def _complete_raw(self, messages: list[dict[str, str]], *, parsed_artifact_type: str, temperature: float) -> str:
        self.call_index += 1
        call_name = infer_call_name(messages, parsed_artifact_type)
        prompt_hash = hash_messages(messages)
        if self.config.replay_path:
            raw = self._replay(messages, call_name, prompt_hash)
        else:
            if self.inner is None:
                raise RuntimeError("record mode requires an active LLM client")
            raw = self.inner.complete_text(messages, temperature=temperature)
        if self.config.record_path:
            self._record(
                call_name=call_name,
                prompt_hash=prompt_hash,
                messages=messages,
                raw_response=raw,
                parsed_artifact_type=parsed_artifact_type,
            )
        return raw

    def _replay(self, messages: list[dict[str, str]], call_name: str, prompt_hash: str) -> str:
        if self.call_index > len(self._replay_records):
            raise RuntimeError(f"LLM replay exhausted at call {self.call_index}: {call_name}")
        record = self._replay_records[self.call_index - 1]
        if record.get("prompt_hash") != prompt_hash:
            raise RuntimeError(
                "LLM replay prompt changed at "
                f"call {self.call_index} ({call_name}); "
                f"expected {record.get('prompt_hash')} got {prompt_hash}"
            )
        return str(record.get("raw_response", ""))

    def _record(
        self,
        *,
        call_name: str,
        prompt_hash: str,
        messages: list[dict[str, str]],
        raw_response: str,
        parsed_artifact_type: str,
    ) -> None:
        assert self.config.record_path is not None
        record = {
            "call_index": self.call_index,
            "call_name": call_name,
            "prompt_hash": prompt_hash,
            "messages": messages,
            "raw_response": raw_response,
            "parsed_artifact_type": parsed_artifact_type,
            "created_at": "1970-01-01T00:00:00Z"
            if self.config.demo_freeze
            else datetime.now(timezone.utc).isoformat(),
        }
        with self.config.record_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def hash_messages(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(messages, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def infer_call_name(messages: list[dict[str, str]], parsed_artifact_type: str) -> str:
    joined = "\n".join(message.get("content", "") for message in messages[:2])
    if "select one RTL skill" in joined:
        return "skill_selection"
    if "RTL generator" in joined:
        return "rtl_generation"
    if "repair RTL code" in joined:
        return "rtl_repair"
    if "C++17 reference model files" in joined:
        return "cpp_codegen"
    if "cpp_model.v1" in joined:
        return "cpp_model"
    if "engineer_spec.v1" in joined:
        return "engineer_spec"
    if "query_plan.json" in joined:
        return "query_plan"
    if "Annotate the following RTL module with semantic fields" in joined:
        return "semantic_annotation"
    return parsed_artifact_type


def _load_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    if not path.exists():
        raise RuntimeError(f"LLM replay file does not exist: {path}")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid JSONL replay record at {path}:{line_number}: {exc}") from exc
    return records
