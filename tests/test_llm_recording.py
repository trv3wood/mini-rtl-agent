from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from src.utils.llm_recording import LLMReplayConfig, RecordingReplayLLM


class SmallSchema(BaseModel):
    value: str


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        self.calls += 1
        if messages and "return object" in messages[0]["content"]:
            return '{"value":"ok"}'
        return "plain response"


def test_record_llm_jsonl_contains_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    fake = FakeLLM()
    llm = RecordingReplayLLM(fake, LLMReplayConfig(record_path=path, demo_freeze=True))

    assert llm.complete_text([{"role": "user", "content": "hello"}]) == "plain response"
    parsed = llm.complete_structured([{"role": "system", "content": "return object"}], SmallSchema)
    assert parsed.value == "ok"

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["call_index"] for record in records] == [1, 2]
    for record in records:
        assert set(record) == {
            "call_index",
            "call_name",
            "prompt_hash",
            "messages",
            "raw_response",
            "parsed_artifact_type",
            "created_at",
        }
        assert record["created_at"] == "1970-01-01T00:00:00Z"


def test_replay_llm_uses_recorded_raw_response_without_inner_client(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    record_llm = RecordingReplayLLM(FakeLLM(), LLMReplayConfig(record_path=path, demo_freeze=True))
    record_llm.complete_text([{"role": "user", "content": "hello"}])

    replay_llm = RecordingReplayLLM(None, LLMReplayConfig(replay_path=path))

    assert replay_llm.complete_text([{"role": "user", "content": "hello"}]) == "plain response"


def test_replay_llm_fails_on_prompt_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    record_llm = RecordingReplayLLM(FakeLLM(), LLMReplayConfig(record_path=path, demo_freeze=True))
    record_llm.complete_text([{"role": "user", "content": "hello"}])

    replay_llm = RecordingReplayLLM(None, LLMReplayConfig(replay_path=path))

    try:
        replay_llm.complete_text([{"role": "user", "content": "changed"}])
    except RuntimeError as exc:
        assert "prompt changed" in str(exc)
    else:
        raise AssertionError("expected prompt hash mismatch")
