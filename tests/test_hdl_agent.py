from __future__ import annotations

from pathlib import Path
from typing import Any

from src.hdl_agent.workflow import run_hdl_agent, strip_markdown_fences
from src.utils.llm import LLMConfig


class FakeLLM:
    def __init__(self) -> None:
        self.text_prompts: list[list[dict[str, str]]] = []

    def complete_structured(self, messages: list[dict[str, str]], schema, *, temperature: float = 0.0):
        assert "UART" in messages[-1]["content"] or "uart" in messages[-1]["content"]
        payload = {
            "intent": "uart transmitter",
            "positive_terms": ["uart", "tx", "transmitter", "baud", "ready valid"],
            "negative_terms": [],
            "likely_categories": ["serial"],
            "likely_interfaces": ["uart", "ready_valid"],
            "required_features": ["start bit", "stop bit", "busy"],
        }
        return schema.model_validate(payload)

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        self.text_prompts.append(messages)
        prompt = messages[-1]["content"]
        assert "Selected skill: uart_tx" in prompt
        assert "skill.json" in prompt
        assert "compact_card.json" in prompt
        assert "RTL source" in prompt
        return """```verilog
module demo_uart_tx(input wire clk, input wire rst, output wire txd);
  assign txd = rst ? 1'b1 : clk;
endmodule
```"""


class RepairFakeLLM(FakeLLM):
    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        self.text_prompts.append(messages)
        if len(self.text_prompts) == 1:
            return "module broken(input wire clk;\nendmodule\n"
        prompt = messages[-1]["content"]
        assert "iverilog failure log" in prompt
        assert "Broken HDL" in prompt
        return "module repaired(input wire clk, output wire txd);\n  assign txd = clk;\nendmodule\n"


class AlwaysBrokenLLM(FakeLLM):
    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        self.text_prompts.append(messages)
        return "module still_broken(input wire clk;\nendmodule\n"


def test_hdl_agent_uses_retriever_and_writes_hdl(tmp_path: Path) -> None:
    llm = FakeLLM()
    output = tmp_path / "agent_uart.v"
    result = run_hdl_agent(
        "Create a small UART transmitter with ready/valid input and busy output",
        llm=llm,
        output_path=output,
    )

    assert result.query_plan.intent == "uart transmitter"
    assert result.selected_skill.name == "uart_tx"
    assert result.retrieved["results"][0]["name"] == "uart_tx"
    assert result.repair_attempts == 0
    assert output.read_text(encoding="utf-8").startswith("module demo_uart_tx")
    assert "```" not in output.read_text(encoding="utf-8")


def test_hdl_agent_reports_important_actions(tmp_path: Path) -> None:
    messages: list[str] = []
    output = tmp_path / "agent_uart.v"

    run_hdl_agent(
        "Create a small UART transmitter with ready/valid input and busy output",
        llm=FakeLLM(),
        output_path=output,
        log=messages.append,
    )

    joined = "\n".join(messages)
    assert "starting HDL generation workflow" in joined
    assert "building query_plan" in joined
    assert "invoking skill retriever tool" in joined
    assert "selected skill: uart_tx" in joined
    assert "running iverilog syntax check" in joined
    assert "syntax check passed" in joined
    assert "wrote generated RTL" in joined


def test_hdl_agent_repairs_syntax_failure_before_writing(tmp_path: Path) -> None:
    llm = RepairFakeLLM()
    output = tmp_path / "agent_uart.v"
    result = run_hdl_agent(
        "Create a small UART transmitter with ready/valid input and busy output",
        llm=llm,
        output_path=output,
        max_retries=3,
    )

    assert result.repair_attempts == 1
    assert output.read_text(encoding="utf-8").startswith("module repaired")
    assert len(llm.text_prompts) == 2


def test_hdl_agent_fails_after_max_syntax_repairs(tmp_path: Path) -> None:
    llm = AlwaysBrokenLLM()
    output = tmp_path / "agent_uart.v"

    try:
        run_hdl_agent(
            "Create a small UART transmitter with ready/valid input and busy output",
            llm=llm,
            output_path=output,
            max_retries=2,
        )
    except RuntimeError as exc:
        assert "failed iverilog syntax check after 2 repair attempt" in str(exc)
    else:
        raise AssertionError("expected syntax repair failure")

    assert not output.exists()
    assert len(llm.text_prompts) == 3


def test_strip_markdown_fences_accepts_plain_code() -> None:
    assert strip_markdown_fences("module x; endmodule").endswith("\n")
    assert strip_markdown_fences("```systemverilog\nmodule x; endmodule\n```") == "module x; endmodule\n"


def test_llm_config_reads_provider_neutral_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    config = LLMConfig.from_env()

    assert config.api_key == "test-key"
    assert config.base_url == "https://example.invalid/v1"
    assert config.model == "test-model"


def test_llm_config_fails_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)

    try:
        LLMConfig.from_env()
    except RuntimeError as exc:
        assert "set LLM_API_KEY" in str(exc)
    else:
        raise AssertionError("expected missing API key error")


def test_llm_config_loads_dotenv_file(tmp_path: Path, monkeypatch) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "LLM_API_KEY=dotenv-key",
                "LLM_BASE_URL=https://example.invalid/v1",
                "LLM_MODEL=dotenv-model",
                "LLM_TIMEOUT_SECONDS=7",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)

    config = LLMConfig.from_env()

    assert config.api_key == "dotenv-key"
    assert config.base_url == "https://example.invalid/v1"
    assert config.model == "dotenv-model"
    assert config.timeout_seconds == 7
