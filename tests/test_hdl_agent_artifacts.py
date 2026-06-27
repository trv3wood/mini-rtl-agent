from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.hdl_agent.workflow import run_hdl_agent
from src.cpp_model_gen.codegen import generate_cpp_files


class ArtifactFakeLLM:
    request = "Create IP named custom_priority8 that converts an 8-bit request vector into a valid flag and encoded winning index."

    def complete_structured(self, messages: list[dict[str, str]], schema, *, temperature: float = 0.0):
        if "selected_skill" in schema.model_fields:
            content = messages[-1]["content"]
            selected_rank = 2 if "'name': 'prim_onehot_check'" in content and "'name': 'priority_encoder'" in content else 1
            return schema.model_validate(
                {
                    "selected_skill": "priority_encoder",
                    "selected_rank": selected_rank,
                    "confidence": "high",
                    "reason": "The priority_encoder candidate directly matches request-vector to encoded-index behavior.",
                    "rejected": [],
                }
            )
        return schema.model_validate(
            {
                "intent": "custom 8-bit priority encoder with valid flag and encoded index",
                "positive_terms": [
                    "priority_encoder",
                    "binary_encoding",
                    "valid_flag",
                    "input_unencoded",
                    "output_encoded",
                ],
                "negative_terms": [],
                "likely_categories": ["control", "arbiter"],
                "likely_interfaces": ["vector_to_index"],
                "required_features": ["priority_select", "valid_flag", "encoded_index"],
            }
        )

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        system = messages[0]["content"]
        if "RTL generator" in system:
            return _rtl()
        if "engineer_spec.v1" in system:
            return json.dumps(_engineer_spec())
        if "C++17 reference model files" in system:
            return json.dumps(_cpp_files())
        if "cpp_model.v1" in system:
            return json.dumps(_cpp_model())
        raise AssertionError(f"unexpected LLM prompt: {system[:120]}")


class BrokenArtifactLLM(ArtifactFakeLLM):
    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        system = messages[0]["content"]
        if "RTL generator" in system:
            return "module broken(input wire clk;\nendmodule\n"
        return super().complete_text(messages, temperature=temperature)


def test_hdl_agent_output_dir_emits_spec_cpp_and_reports(tmp_path: Path) -> None:
    if not shutil.which("iverilog"):
        pytest.skip("iverilog is required")
    if not shutil.which("g++") and not shutil.which("clang++"):
        pytest.skip("g++ or clang++ is required")

    output_dir = tmp_path / "custom_priority8"
    messages: list[str] = []
    result = run_hdl_agent(
        ArtifactFakeLLM.request,
        llm=ArtifactFakeLLM(),
        skills_root=Path("skills"),
        output_dir=output_dir,
        limit=8,
        emit_spec=True,
        emit_cpp_ref=True,
        build_cpp_ref=True,
        run_cpp_ref_tests=True,
        log=messages.append,
    )

    assert result.selected_skill.name == "priority_encoder"
    assert result.retrieved["skill_selection"]["selected_skill"] == "priority_encoder"
    assert result.output_path == output_dir / "custom_priority8.v"

    expected = [
        "query_plan.json",
        "retrieval_trace.json",
        "custom_priority8.v",
        "final_ip_context.json",
        "engineer_spec.json",
        "cpp_model.json",
        "cpp/custom_priority8_ref.h",
        "cpp/custom_priority8_ref.cpp",
        "cpp/test_custom_priority8_ref.cpp",
        "cpp/CMakeLists.txt",
        "reports/iverilog_check.json",
        "reports/cpp_build.json",
        "reports/cpp_test.json",
    ]
    for rel_path in expected:
        assert (output_dir / rel_path).exists(), rel_path

    final_context = json.loads((output_dir / "final_ip_context.json").read_text(encoding="utf-8"))
    assert final_context["schema_version"] == "final_ip_context.v1"
    assert final_context["final_rtl"]["module_name"] == "custom_priority8"
    assert [port["name"] for port in final_context["final_rtl"]["ports"]] == ["req", "valid", "win_idx"]

    spec = json.loads((output_dir / "engineer_spec.json").read_text(encoding="utf-8"))
    assert spec["schema_version"] == "engineer_spec.v1"
    assert spec["ip_name"] == "custom_priority8"
    assert spec["source_skill"] == "priority_encoder"

    cpp_model = json.loads((output_dir / "cpp_model.json").read_text(encoding="utf-8"))
    assert cpp_model["schema_version"] == "cpp_model.v1"
    assert cpp_model["model_kind"] == "combinational_function"
    assert cpp_model["function_signature"]["arguments"][0]["type"] == "uint8_t"

    build_report = json.loads((output_dir / "reports/cpp_build.json").read_text(encoding="utf-8"))
    test_report = json.loads((output_dir / "reports/cpp_test.json").read_text(encoding="utf-8"))
    assert build_report["status"] == "passed"
    assert test_report["status"] == "passed"

    trace = "\n".join(messages)
    assert "[plan] wrote" in trace
    assert "[selector] selected" in trace
    assert "[hdl] wrote" in trace
    assert "[context] wrote" in trace
    assert "[spec] wrote" in trace
    assert "[cpp-plan] wrote" in trace
    assert "[cpp-codegen] wrote" in trace
    assert "[cpp-build] passed" in trace
    assert "[cpp-test] passed" in trace


def test_hdl_agent_output_dir_writes_iverilog_failure_report(tmp_path: Path) -> None:
    if not shutil.which("iverilog"):
        pytest.skip("iverilog is required")

    output_dir = tmp_path / "broken_priority"
    with pytest.raises(RuntimeError):
        run_hdl_agent(
            ArtifactFakeLLM.request,
            llm=BrokenArtifactLLM(),
            skills_root=Path("skills"),
            output_dir=output_dir,
            limit=8,
            max_retries=0,
        )

    report = json.loads((output_dir / "reports/iverilog_check.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["returncode"] == 1
    assert "failed iverilog syntax check" in report["stderr"]


def test_cpp_codegen_refuses_blocking_model_plan(tmp_path: Path) -> None:
    plan = _cpp_model()
    assert isinstance(plan["behavior_contract"], dict)
    plan["model_kind"] = "unsupported"
    plan["behavior_contract"]["conflicts"] = [
        {"topic": "missing behavior", "description": "No safe model can be generated.", "blocking": True}
    ]

    with pytest.raises(ValueError, match="refusing C\\+\\+ codegen"):
        generate_cpp_files(
            llm_client=ArtifactFakeLLM(),
            cpp_model_plan=plan,
            engineer_spec=_engineer_spec(),
            output_cpp_dir=tmp_path / "cpp",
        )


def test_hdl_agent_uses_llm_selection_instead_of_top1(monkeypatch, tmp_path: Path) -> None:
    if not shutil.which("iverilog"):
        pytest.skip("iverilog is required")

    def fake_retriever(_plan, _skills_root, _limit):
        return {
            "query_plan": {},
            "results": [
                {"name": "prim_onehot_check", "path": "skills/prim_onehot_check", "score": 14},
                {"name": "priority_encoder", "path": "skills/priority_encoder", "score": 13},
            ],
        }

    monkeypatch.setattr("src.hdl_agent.workflow.call_skill_retriever_tool", fake_retriever)
    output = tmp_path / "custom_priority8.v"

    result = run_hdl_agent(
        ArtifactFakeLLM.request,
        llm=ArtifactFakeLLM(),
        skills_root=Path("skills"),
        output_path=output,
        limit=8,
    )

    assert result.retrieved["results"][0]["name"] == "prim_onehot_check"
    assert result.selected_skill.name == "priority_encoder"
    assert result.retrieved["skill_selection"]["selected_rank"] == 2


def _rtl() -> str:
    return """
module custom_priority8 (
  input wire [7:0] req,
  output reg valid,
  output reg [2:0] win_idx
);
  integer i;
  always @* begin
    valid = 1'b0;
    win_idx = 3'd0;
    for (i = 0; i < 8; i = i + 1) begin
      if (req[i]) begin
        valid = 1'b1;
        win_idx = i[2:0];
      end
    end
  end
endmodule
"""


def _engineer_spec() -> dict[str, object]:
    ports = [
        {"name": "req", "direction": "input", "width": 8, "role": "request vector", "description": "Input request bits."},
        {"name": "valid", "direction": "output", "width": 1, "role": "valid flag", "description": "High when any request bit is set."},
        {"name": "win_idx", "direction": "output", "width": 3, "role": "encoded index", "description": "Index of the highest active request bit when valid is high."},
    ]
    return {
        "schema_version": "engineer_spec.v1",
        "ip_name": "custom_priority8",
        "source_skill": "priority_encoder",
        "title": "8-bit Priority Encoder",
        "summary": {
            "one_sentence": "Encodes an 8-bit request vector into valid plus a winning index.",
            "detailed_description": "The IP reports whether any request bit is asserted and returns the highest active bit index.",
            "design_intent": "Provide a small combinational arbitration helper.",
        },
        "classification": {
            "domain": "digital logic",
            "category": "priority encoder",
            "granularity": "wrapper_ip",
            "implementation_style": "combinational_logic",
            "statefulness": "stateless",
            "clocking_model": "no_clock",
        },
        "interface": {
            "ports": ports,
            "parameters": [],
            "clock": {"name": "", "description": "No clock."},
            "reset": {"name": "", "polarity": "unknown", "synchronous": "unknown", "description": "No reset."},
            "interface_summary": "Combinational request vector in, valid and encoded index out.",
        },
        "behavior": {
            "functional_behavior": ["valid is true when req is nonzero.", "win_idx is the highest set bit when valid is true."],
            "semantic_rules": ["When multiple bits are set, the numerically highest bit wins."],
            "invalid_or_dont_care_behavior": ["win_idx is don't-care when valid is false."],
            "latency": {"type": "combinational", "cycles": None, "note": "No clocked latency."},
            "throughput": {"type": "combinational", "note": "Updates whenever inputs change."},
        },
        "usage": {
            "typical_use_cases": ["Small arbiters", "Interrupt selection"],
            "not_suitable_for": ["Fair arbitration"],
            "integration_notes": ["Use valid before consuming win_idx."],
        },
        "assumptions_and_constraints": {"assumptions": [], "constraints": [], "unknowns": []},
        "verification_notes": {
            "recommended_strategy": "Directed and random vector checks.",
            "directed_tests": ["zero", "single bit", "multiple bits"],
            "random_tests": ["random request vectors"],
            "properties_to_check": ["valid equals req!=0"],
            "uvm_suitability": "low",
            "uvm_note": "Simple combinational IP.",
        },
        "human_review": {"confidence": "high", "review_focus": ["priority direction"]},
    }


def _cpp_model() -> dict[str, object]:
    vectors = [
        {"name": "zero", "inputs": {"req": 0}, "expected": {"valid": False, "win_idx": 0}, "check_mask": {"valid": "compare", "win_idx": "ignore"}},
        {"name": "bit0", "inputs": {"req": 1}, "expected": {"valid": True, "win_idx": 0}, "check_mask": {"valid": "compare", "win_idx": "compare"}},
        {"name": "bit7", "inputs": {"req": 128}, "expected": {"valid": True, "win_idx": 7}, "check_mask": {"valid": "compare", "win_idx": "compare"}},
        {"name": "mixed", "inputs": {"req": 41}, "expected": {"valid": True, "win_idx": 5}, "check_mask": {"valid": "compare", "win_idx": "compare"}},
        {"name": "all", "inputs": {"req": 255}, "expected": {"valid": True, "win_idx": 7}, "check_mask": {"valid": "compare", "win_idx": "compare"}},
    ]
    return {
        "schema_version": "cpp_model.v1",
        "ip_name": "custom_priority8",
        "source_skill": "priority_encoder",
        "model_name": "custom_priority8_ref",
        "model_role": "golden_reference_model",
        "model_kind": "combinational_function",
        "language": "cpp17",
        "equivalence_scope": {
            "visible_outputs_only": True,
            "cycle_accurate": False,
            "four_state_logic": False,
            "timing_delays": False,
            "notes": ["Models visible combinational outputs only."],
        },
        "types": [{"name": "Result", "fields": [{"name": "valid", "type": "bool", "width": 1, "semantic": "request present"}, {"name": "win_idx", "type": "uint8_t", "width": 3, "semantic": "highest active index"}]}],
        "function_signature": {
            "name": "eval",
            "return_type": "Result",
            "arguments": [{"name": "req", "type": "uint8_t", "width": 8, "role": "request vector"}],
        },
        "behavior_contract": {
            "preconditions": [],
            "postconditions": ["valid == (req != 0)"],
            "semantic_choices": ["Highest numbered asserted bit wins."],
            "dont_care_conditions": ["win_idx ignored when valid is false."],
            "unknowns": [],
            "conflicts": [],
        },
        "test_vectors": vectors,
        "generation_outputs": {
            "header": "custom_priority8_ref.h",
            "source": "custom_priority8_ref.cpp",
            "test": "test_custom_priority8_ref.cpp",
            "build": "CMakeLists.txt",
        },
    }


def _cpp_files() -> dict[str, object]:
    return {
        "files": [
            {
                "path": "custom_priority8_ref.h",
                "content": """#pragma once
#include <cstdint>

struct CustomPriority8Result {
  bool valid;
  std::uint8_t win_idx;
};

CustomPriority8Result custom_priority8_ref(std::uint8_t req);
""",
            },
            {
                "path": "custom_priority8_ref.cpp",
                "content": """#include "custom_priority8_ref.h"

CustomPriority8Result custom_priority8_ref(std::uint8_t req) {
  CustomPriority8Result result{req != 0, 0};
  for (int i = 0; i < 8; ++i) {
    if ((req >> i) & 0x1u) {
      result.win_idx = static_cast<std::uint8_t>(i);
    }
  }
  return result;
}
""",
            },
            {
                "path": "test_custom_priority8_ref.cpp",
                "content": """#include "custom_priority8_ref.h"
#include <cassert>
#include <iostream>

static void check(std::uint8_t req, bool valid, std::uint8_t win_idx, bool check_idx) {
  auto got = custom_priority8_ref(req);
  assert(got.valid == valid);
  if (check_idx) {
    assert(got.win_idx == win_idx);
  }
}

int main() {
  check(0x00, false, 0, false);
  check(0x01, true, 0, true);
  check(0x80, true, 7, true);
  check(0x29, true, 5, true);
  check(0xff, true, 7, true);
  std::cout << "PASS custom_priority8_ref\\n";
  return 0;
}
""",
            },
            {
                "path": "CMakeLists.txt",
                "content": """cmake_minimum_required(VERSION 3.10)
project(custom_priority8_ref CXX)
set(CMAKE_CXX_STANDARD 17)
add_executable(ref_test custom_priority8_ref.cpp test_custom_priority8_ref.cpp)
""",
            },
        ]
    }
