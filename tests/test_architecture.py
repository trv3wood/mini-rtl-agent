from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.architecture.mermaid import generate_mermaid
from src.architecture.planner import plan_architecture, validate_architecture, write_architecture_outputs
from src.architecture.skill_mapper import map_node_to_skill_category


class FakeArchitectureLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.messages: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> dict[str, Any]:
        self.messages.append(messages)
        assert "architecture planner" in messages[0]["content"]
        return self.payload

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        raise AssertionError("architecture planner should request JSON, not text")


def uart_payload() -> dict[str, Any]:
    return {
        "top_module": "uart_receiver_with_fifo",
        "submodules": [
            {
                "name": "UART_RX",
                "purpose": "Recover UART frames from RXD.",
                "inputs": ["clk", "rst", "rxd", "baud_tick"],
                "outputs": ["rx_data[7:0]", "rx_valid"],
                "constraints": ["Sample in the middle of each bit."],
                "dependencies": ["Controller"],
                "patterns": ["uart", "serial receiver", "fsm"],
            },
            {
                "name": "FIFO",
                "purpose": "Buffer received bytes.",
                "inputs": ["clk", "rst", "rx_data[7:0]", "write_en"],
                "outputs": ["data_out[7:0]", "empty", "full"],
                "constraints": ["Preserve byte order."],
                "dependencies": ["UART_RX"],
                "patterns": ["fifo", "buffer"],
            },
            {
                "name": "Controller",
                "purpose": "Coordinate receive and FIFO writes.",
                "inputs": ["clk", "rst", "rx_valid", "fifo_full"],
                "outputs": ["sample_enable", "fifo_write"],
                "constraints": ["Do not write FIFO when full."],
                "dependencies": [],
                "patterns": ["fsm", "controller"],
            },
        ],
        "connections": [
            {"from": "Controller", "to": "UART_RX", "signal": "sample_enable"},
            {"from": "UART_RX", "to": "FIFO", "signal": "rx_data/rx_valid"},
            {"from": "FIFO", "to": "Controller", "signal": "full"},
        ],
        "notes": ["LLM planned architecture for UART RX with buffering."],
    }


def fft_payload() -> dict[str, Any]:
    return {
        "top_module": "fft4_accelerator",
        "submodules": [
            {
                "name": "FFT_Controller",
                "purpose": "Sequence FFT stages.",
                "inputs": ["clk", "rst", "start"],
                "outputs": ["stage_select", "twiddle_addr", "done"],
                "constraints": ["Run two butterfly stages."],
                "dependencies": [],
                "patterns": ["fsm", "controller"],
            },
            {
                "name": "Butterfly",
                "purpose": "Compute FFT butterfly sum/difference.",
                "inputs": ["a", "b", "twiddle"],
                "outputs": ["y0", "y1"],
                "constraints": ["Define fixed-point format before RTL."],
                "dependencies": ["Complex_Multiplier"],
                "patterns": ["butterfly", "dsp"],
            },
            {
                "name": "Twiddle_ROM",
                "purpose": "Store twiddle factors.",
                "inputs": ["twiddle_addr"],
                "outputs": ["twiddle"],
                "constraints": ["Constants match N=4."],
                "dependencies": ["FFT_Controller"],
                "patterns": ["rom", "lookup"],
            },
            {
                "name": "Complex_Multiplier",
                "purpose": "Multiply complex samples by twiddles.",
                "inputs": ["sample", "twiddle"],
                "outputs": ["product"],
                "constraints": ["Define rounding policy."],
                "dependencies": ["Twiddle_ROM"],
                "patterns": ["complex multiplier", "dsp"],
            },
        ],
        "connections": [
            {"from": "FFT_Controller", "to": "Butterfly", "signal": "stage_select"},
            {"from": "FFT_Controller", "to": "Twiddle_ROM", "signal": "twiddle_addr"},
            {"from": "Twiddle_ROM", "to": "Complex_Multiplier", "signal": "twiddle_factor"},
            {"from": "Complex_Multiplier", "to": "Butterfly", "signal": "product"},
        ],
        "notes": ["4-point FFT architecture produced by fake LLM."],
    }


def dma_payload() -> dict[str, Any]:
    return {
        "top_module": "simple_dma_engine",
        "submodules": [
            {
                "name": "DMA_Controller",
                "purpose": "Sequence DMA transfer.",
                "inputs": ["clk", "rst", "start"],
                "outputs": ["read_req", "write_req", "done"],
                "constraints": ["Do not overrun FIFO."],
                "dependencies": ["FIFO_Buffer"],
                "patterns": ["fsm", "controller"],
            },
            {
                "name": "Address_Generator",
                "purpose": "Generate source and destination addresses.",
                "inputs": ["base", "length"],
                "outputs": ["src_addr", "dst_addr"],
                "constraints": ["Respect transfer length."],
                "dependencies": ["DMA_Controller"],
                "patterns": ["counter", "address generation"],
            },
            {
                "name": "FIFO_Buffer",
                "purpose": "Decouple bus reads and writes.",
                "inputs": ["write_data", "write_valid"],
                "outputs": ["read_data", "read_valid", "full", "empty"],
                "constraints": ["Preserve data order."],
                "dependencies": ["DMA_Controller"],
                "patterns": ["fifo", "ready valid"],
            },
            {
                "name": "Bus_Arbiter",
                "purpose": "Arbitrate read and write requests.",
                "inputs": ["read_req", "write_req"],
                "outputs": ["read_grant", "write_grant"],
                "constraints": ["Avoid starvation."],
                "dependencies": ["DMA_Controller"],
                "patterns": ["arbiter", "bus arbitration"],
            },
        ],
        "connections": [
            {"from": "DMA_Controller", "to": "Address_Generator", "signal": "control"},
            {"from": "DMA_Controller", "to": "Bus_Arbiter", "signal": "requests"},
            {"from": "Bus_Arbiter", "to": "FIFO_Buffer", "signal": "data_path"},
        ],
        "notes": ["Simple DMA architecture produced by fake LLM."],
    }


def names(architecture: dict) -> set[str]:
    return {item["name"] for item in architecture["submodules"]}


def test_uart_receiver_with_fifo_architecture_contains_required_blocks() -> None:
    llm = FakeArchitectureLLM(uart_payload())
    architecture = plan_architecture("Design a UART receiver with FIFO buffering", llm=llm)

    assert architecture["top_module"] == "uart_receiver_with_fifo"
    assert {"UART_RX", "FIFO", "Controller"}.issubset(names(architecture))
    assert any(connection["from"] == "UART_RX" and connection["to"] == "FIFO" for connection in architecture["connections"])
    fifo = next(item for item in architecture["submodules"] if item["name"] == "FIFO")
    assert fifo["skill_category"] == "fifo"
    assert "Design a UART receiver" in llm.messages[0][1]["content"]


def test_fft4_architecture_contains_required_blocks_and_dependencies() -> None:
    architecture = plan_architecture("Design a 4-point FFT accelerator", llm=FakeArchitectureLLM(fft_payload()))

    assert architecture["top_module"] == "fft4_accelerator"
    assert {"Butterfly", "Twiddle_ROM", "Complex_Multiplier", "FFT_Controller"}.issubset(names(architecture))
    butterfly = next(item for item in architecture["submodules"] if item["name"] == "Butterfly")
    assert "Complex_Multiplier" in butterfly["dependencies"]
    assert any(connection["from"] == "Twiddle_ROM" and connection["to"] == "Complex_Multiplier" for connection in architecture["connections"])


def test_simple_dma_architecture_maps_fifo_and_arbiter() -> None:
    architecture = plan_architecture("Design a simple DMA engine", llm=FakeArchitectureLLM(dma_payload()))

    assert architecture["top_module"] == "simple_dma_engine"
    assert {"DMA_Controller", "Address_Generator", "FIFO_Buffer", "Bus_Arbiter"}.issubset(names(architecture))
    mapped = {item["name"]: item["skill_category"] for item in architecture["submodules"]}
    assert mapped["FIFO_Buffer"] == "fifo"
    assert mapped["Bus_Arbiter"] == "arbiter"


def test_non_demo_requirement_is_llm_planned_not_fixed_example_limited() -> None:
    payload = {
        "top_module": "pwm_timer",
        "submodules": [
            {
                "name": "PWM_Controller",
                "purpose": "Generate PWM output from period and duty registers.",
                "inputs": ["clk", "rst", "period", "duty"],
                "outputs": ["pwm_out"],
                "constraints": ["Duty must not exceed period."],
                "dependencies": [],
                "patterns": ["counter", "fsm"],
            }
        ],
        "connections": [],
        "notes": ["Custom architecture not covered by a fixed local example."],
    }
    architecture = plan_architecture("Design a PWM timer", llm=FakeArchitectureLLM(payload))

    assert architecture["top_module"] == "pwm_timer"
    assert names(architecture) == {"PWM_Controller"}


def test_mermaid_export_contains_graph_edges() -> None:
    architecture = plan_architecture("Design a 4-point FFT accelerator", llm=FakeArchitectureLLM(fft_payload()))
    mermaid = generate_mermaid(architecture)

    assert mermaid.startswith("graph TD")
    assert "FFT_Controller -- stage_select --> Butterfly" in mermaid
    assert "Twiddle_ROM -- twiddle_factor --> Complex_Multiplier" in mermaid


def test_write_architecture_outputs(tmp_path: Path) -> None:
    paths = write_architecture_outputs(
        "Design a UART receiver with FIFO buffering",
        tmp_path,
        llm=FakeArchitectureLLM(uart_payload()),
    )

    architecture = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert {"UART_RX", "FIFO", "Controller"}.issubset(names(architecture))
    assert "UART_RX" in paths["markdown"].read_text(encoding="utf-8")
    assert "graph TD" in paths["mermaid"].read_text(encoding="utf-8")
    spec_names = {path.name for path in paths["specs"]}
    assert {"uart_rx.md", "fifo.md", "controller.md"}.issubset(spec_names)
    assert "## Dependencies" in (tmp_path / "specs" / "fifo.md").read_text(encoding="utf-8")


def test_architecture_cli_help_does_not_require_llm_env() -> None:
    run = subprocess.run(
        ["python3", "-m", "architecture", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert "Plan a multi-module RTL architecture" in run.stdout


def test_validate_architecture_rejects_unknown_connection_target() -> None:
    payload = uart_payload()
    payload["connections"] = [{"from": "UART_RX", "to": "Missing", "signal": "bad"}]

    try:
        validate_architecture(payload)
    except RuntimeError as exc:
        assert "unknown submodule" in str(exc)
    else:
        raise AssertionError("expected validation failure")


def test_skill_mapper_basic_categories() -> None:
    assert map_node_to_skill_category("FIFO Buffer") == "fifo"
    assert map_node_to_skill_category("State Controller") == "fsm"
    assert map_node_to_skill_category("Clock Crossing Unit", "CDC synchronizer") == "synchronizer"
    assert map_node_to_skill_category("Bus Arbitration") == "arbiter"
