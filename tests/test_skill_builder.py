from __future__ import annotations

import json
from pathlib import Path

from src.skill_builder.builder import build_skill_library
from src.skill_builder.cli import main as skill_builder_main
from src.skill_builder.llm_client import (
    AnnotationResult,
    FallbackAnnotator,
    OpenAICompatibleAnnotator,
    SemanticAnnotation,
)
from src.skill_builder.minimal import (
    build_compact_card,
    build_minimal_skill_json,
    validate_compact_card,
    validate_minimal_skill,
)
from src.skill_builder.frontend import parse_project
from src.skill_builder.hierarchy import (
    build_module_hierarchy,
    compute_dependency_closure,
    mermaid_dependency_graph,
    module_dependency_graph,
)
from src.skill_builder.parser import parse_modules
from src.skill_builder.semantic import (
    annotate_module,
    build_semantic_input,
    make_compact_card_from_skill,
    merge_deterministic_and_semantic,
)
from src.skill_builder.taxonomy import normalize_annotation
from src.skill_builder.validate_minimal_skills import validate_library
from src.skill_retriever.models import QueryPlan
from src.skill_retriever.retriever import retrieve_skills
from src.utils.llm_recording import LLMReplayConfig, RecordingReplayLLM


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class SemanticFakeLLM:
    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        return json.dumps({
            "core_function": "test semantic annotation",
            "algorithm": "combinational pass through",
            "structure": ["combinational_logic"],
            "interface_protocol": "plain_ports",
            "granularity": "primitive",
            "keywords": ["demo", "semantic"],
        })

    def complete_structured(self, messages: list[dict[str, str]], schema, *, temperature: float = 0.0):
        return schema.model_validate_json(self.complete_text(messages, temperature=temperature))


def test_parse_simple_ansi_module(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "ansi.v",
        """
module simple_ansi (
    input wire clk,
    input wire rst,
    input wire [7:0] data_i,
    output reg valid_o
);
endmodule
""",
    )
    modules = parse_modules(rtl)
    assert [module.name for module in modules] == ["simple_ansi"]
    assert [port.name for port in modules[0].ports] == ["clk", "rst", "data_i", "valid_o"]
    assert modules[0].ports[2].width == "[7:0]"
    assert modules[0].ports[3].direction == "output"


def test_parse_non_ansi_module(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "non_ansi.v",
        """
module non_ansi(clk, rst_n, data_o);
input clk;
input rst_n;
output [3:0] data_o;
endmodule
""",
    )
    module = parse_modules(rtl)[0]
    ports = {port.name: port for port in module.ports}
    assert ports["clk"].direction == "input"
    assert ports["rst_n"].direction == "input"
    assert ports["data_o"].direction == "output"
    assert ports["data_o"].width == "[3:0]"


def test_parse_parameterized_module(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "param.v",
        """
module param_mod #(
    parameter WIDTH = 16,
    parameter DEPTH = 4
) (
    input wire [WIDTH-1:0] data_i,
    output wire [DEPTH-1:0] data_o
);
endmodule
""",
    )
    module = parse_modules(rtl)[0]
    assert [(param.name, param.default) for param in module.parameters] == [
        ("WIDTH", "16"),
        ("DEPTH", "4"),
    ]
    assert module.ports[0].width == "[WIDTH-1:0]"


def test_pyslang_extracts_module_with_comment_between_name_and_ports(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "commented_header.v",
        """
module commented_header
// Params
#(
    parameter WIDTH = 8
)
// Ports
(
    input wire clk,
    input wire [WIDTH-1:0] data_i,
    output wire valid_o
);
endmodule
""",
    )

    modules = parse_project([rtl])

    assert [module.name for module in modules] == ["commented_header"]
    assert modules[0].parse_backend == "pyslang"
    assert [param.name for param in modules[0].parameters] == ["WIDTH"]
    assert [port.name for port in modules[0].ports] == ["clk", "data_i", "valid_o"]
    assert modules[0].ports[1].width == "[WIDTH - 1:0]"


def test_parse_module_with_comments(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "comments.v",
        """
// Top comment for extraction.
/*
 * Block comment survives as readable text.
 */
module commented(input wire clk);
endmodule
""",
    )
    module = parse_modules(rtl)[0]
    assert any("Top comment" in comment for comment in module.comments)
    assert any("Block comment" in comment for comment in module.comments)


def test_parse_module_with_no_parameters(tmp_path: Path) -> None:
    rtl = write(tmp_path / "noparam.v", "module noparam(input wire clk); endmodule\n")
    module = parse_modules(rtl)[0]
    assert module.name == "noparam"
    assert module.parameters == []


def test_parse_multiple_modules_in_one_file(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "multi.v",
        """
module first(input wire clk); endmodule
module second(input wire clk, output wire done); endmodule
""",
    )
    assert [module.name for module in parse_modules(rtl)] == ["first", "second"]


def test_frontend_extracts_module_ir_instances_and_hierarchy(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "top.sv",
        """
module child(input logic clk);
endmodule

module top(input logic clk);
    child u_child (.clk(clk));
    external_ip u_ip (.clk(clk));
endmodule

module island(input logic clk);
endmodule
""",
    )
    modules = parse_project([rtl])
    by_name = {module.name: module for module in modules}
    assert set(by_name) == {"child", "top", "island"}
    assert by_name["top"].parse_backend in {"pyslang", "regex"}
    assert by_name["top"].instances[0].module_name == "child"
    assert by_name["top"].instances[0].port_connections == {"clk": "clk"}

    hierarchy = build_module_hierarchy(modules)
    assert hierarchy.edges["top"] == {"child"}
    assert hierarchy.roots == ["island", "top"]
    assert hierarchy.unresolved_dependencies == {"top": {"external_ip"}}


def test_pyslang_instance_extractor_ignores_procedural_constructs(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "ast_instances.sv",
        """
module child(input logic clk); endmodule
module top(input logic clk);
    for (genvar i = 0; i < 4; i++) begin : g
        child u_child(.clk(clk));
    end
    function automatic logic bin2gray(input logic value);
        return value ^ (value >> 1);
    endfunction
    initial begin
        $display("test");
        $error("error");
    end
endmodule
""",
    )
    modules = parse_project([rtl])
    top = {module.name: module for module in modules}["top"]
    assert top.instance_backend == "pyslang_ast"
    assert [(inst.module_name, inst.instance_name) for inst in top.instances] == [("child", "u_child")]
    hierarchy = build_module_hierarchy(modules)
    assert hierarchy.unresolved_dependencies == {}


def test_pyslang_instance_extractor_handles_parameterized_instance(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "param_inst.sv",
        """
module axis_fifo #(parameter DEPTH = 4) (input logic clk); endmodule
module top(input logic clk);
    axis_fifo #(
        .DEPTH(16)
    ) u_fifo (
        .clk(clk)
    );
endmodule
""",
    )
    top = {module.name: module for module in parse_project([rtl])}["top"]
    assert len(top.instances) == 1
    inst = top.instances[0]
    assert inst.module_name == "axis_fifo"
    assert inst.instance_name == "u_fifo"
    assert inst.parameter_overrides == {"DEPTH": "16"}
    assert inst.port_connections == {"clk": "clk"}
    assert inst.source is not None
    assert inst.source.line_start is not None


def test_frontend_extracts_structural_facts_for_evidence_pack(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "facts.sv",
        """
module facts(input logic clk, input logic rst, output logic full);
    logic [7:0] mem [0:3];
    logic [2:0] count;

    assign full = count == 4;

    always_ff @(posedge clk) begin
        if (rst) begin
            count <= 0;
        end
    end

    assert property (count <= 4);
endmodule
""",
    )
    module = parse_project([rtl])[0]
    assert [fact.name for fact in module.memory_candidates] == ["mem"]
    assert module.always_blocks
    assert module.always_blocks[0].expression == "posedge clk"
    assert [fact.name for fact in module.continuous_assignments] == ["full"]
    assert module.assertions[0].kind == "assert_statement"
    assert module.assertions[0].expression == "count <= 4"


def test_hierarchy_keeps_self_recursive_module_as_root(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "self_ref.v",
        """
module self_ref(input wire clk);
    self_ref u_self (.clk(clk));
endmodule
""",
    )
    hierarchy = build_module_hierarchy(parse_project([rtl]))
    assert hierarchy.edges["self_ref"] == {"self_ref"}
    assert hierarchy.roots == ["self_ref"]


def test_skill_candidate_standalone_closure(tmp_path: Path) -> None:
    rtl = write(tmp_path / "one.v", "module one(input wire clk); endmodule\n")
    candidate = compute_dependency_closure("one", build_module_hierarchy(parse_project([rtl])))
    assert candidate.candidate_kind == "standalone"
    assert candidate.dependency_modules == []
    assert candidate.is_self_contained is True


def test_skill_candidate_single_and_multilevel_dependencies(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "deps.v",
        """
module leaf(input wire clk); endmodule
module middle(input wire clk); leaf u_leaf(.clk(clk)); endmodule
module top(input wire clk); middle u_middle(.clk(clk)); endmodule
""",
    )
    candidate = compute_dependency_closure("top", build_module_hierarchy(parse_project([rtl])))
    assert candidate.candidate_kind == "composite"
    assert candidate.dependency_modules == ["middle", "leaf"]
    assert len(candidate.source_files) == 1
    graph = module_dependency_graph(build_module_hierarchy(parse_project([rtl])))
    assert graph["direct_edges"]["top"] == ["middle"]
    assert graph["direct_edges"]["middle"] == ["leaf"]
    assert graph["closure_edges"]["top"] == ["middle", "leaf"]
    mermaid = mermaid_dependency_graph(build_module_hierarchy(parse_project([rtl])), closure=True)
    assert "m_top --> m_middle" in mermaid
    assert "m_top --> m_leaf" in mermaid


def test_skill_candidate_shared_dependency_is_deduped(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "shared.v",
        """
module common(input wire clk); endmodule
module a(input wire clk); common u_common(.clk(clk)); endmodule
module b(input wire clk); common u_common(.clk(clk)); endmodule
module top(input wire clk); a u_a(.clk(clk)); b u_b(.clk(clk)); endmodule
""",
    )
    candidate = compute_dependency_closure("top", build_module_hierarchy(parse_project([rtl])))
    assert candidate.dependency_modules.count("common") == 1
    assert candidate.dependency_modules == ["a", "common", "b"]


def test_skill_candidate_cycle_is_reported(tmp_path: Path) -> None:
    rtl = write(
        tmp_path / "cycle.v",
        """
module a(input wire clk); b u_b(.clk(clk)); endmodule
module b(input wire clk); a u_a(.clk(clk)); endmodule
""",
    )
    candidate = compute_dependency_closure("a", build_module_hierarchy(parse_project([rtl])))
    assert candidate.candidate_kind == "cyclic"
    assert candidate.hierarchy_warnings


def test_skill_candidate_external_dependency_is_unresolved(tmp_path: Path) -> None:
    rtl = write(tmp_path / "missing.v", "module top(input wire clk); missing_ip u_ip(.clk(clk)); endmodule\n")
    candidate = compute_dependency_closure("top", build_module_hierarchy(parse_project([rtl])))
    assert candidate.unresolved_dependencies == ["missing_ip"]
    assert candidate.is_self_contained is False
    assert candidate.candidate_kind == "unresolved"


def test_vendor_primitive_dependency_is_classified(tmp_path: Path) -> None:
    rtl = write(tmp_path / "vendor.v", "module top(input wire clk); RAMB36E1 u_ram(); endmodule\n")
    candidate = compute_dependency_closure("top", build_module_hierarchy(parse_project([rtl])))
    assert candidate.vendor_primitives == ["RAMB36E1"]
    assert candidate.unresolved_dependencies == []


def test_malformed_file_does_not_crash_builder(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write(repo / "rtl" / "broken.v", "module broken(input wire clk\n")
    report = build_skill_library(repo, tmp_path / "skills", clean=True, candidate_mode="all")
    assert report["rtl_files_scanned"] == 1
    assert report["modules_extracted"] == 0
    assert report["skills_generated"] == 0
    assert (tmp_path / "skills" / "report.json").exists()


def test_sample_repo_golden_output(tmp_path: Path) -> None:
    repo = Path("work/sample_rtl_repo")
    output = tmp_path / "skills"
    report = build_skill_library(repo, output, clean=True, candidate_mode="all")

    assert report["skills_generated"] == 4
    assert report["package_format"] == "minimal"
    assert sum(report["frontend"]["backend_counts"].values()) == 4
    assert report["frontend"]["module_count"] == 4
    assert sorted(report["frontend"]["root_modules"]) == [
        "pulse_counter",
        "reset_sync",
        "round_robin",
        "simple_fifo",
    ]
    assert report["frontend"]["unresolved_dependencies"] == {}
    assert report["frontend"]["parse_warnings"]
    assert not (output / "dependency_graph.mmd").exists()
    assert not (output / "dependency_closure_graph.mmd").exists()
    assert report["dependency_graph"]["direct_edges"]["simple_fifo"] == []
    assert report["dependency_graph"]["closure_edges"]["simple_fifo"] == []
    assert report["dependency_graph"]["mermaid_closure"] is None
    assert (output / "report.json").exists()
    assert report["quality_gate_counts"] == {}

    for skill in report["skills"]:
        skill_dir = output / skill["skill_name"]
        assert validate_library(output) == []
        assert (skill_dir / "skill.json").exists()
        assert (skill_dir / "compact_card.json").exists()
        assert not (skill_dir / "module_info.json").exists()
        assert not (skill_dir / "README.md").exists()
        assert not (skill_dir / "template.v").exists()


def test_builder_generates_only_skill_card_and_rtl(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write(
        repo / "rtl" / "axis_adapter.v",
        """
module axis_adapter #(
    parameter S_DATA_WIDTH = 8,
    parameter M_DATA_WIDTH = 16
) (
    input wire clk,
    input wire rst,
    input wire [S_DATA_WIDTH-1:0] s_axis_tdata,
    input wire s_axis_tvalid,
    output wire s_axis_tready,
    output wire [M_DATA_WIDTH-1:0] m_axis_tdata,
    output wire m_axis_tvalid,
    input wire m_axis_tready
);
assign s_axis_tready = m_axis_tready;
assign m_axis_tvalid = s_axis_tvalid;
assign m_axis_tdata = {{(M_DATA_WIDTH-S_DATA_WIDTH){1'b0}}, s_axis_tdata};
endmodule
""",
    )
    output = tmp_path / "minimal_skills"
    report = build_skill_library(
        repo,
        output,
        clean=True,
    )
    skill_dir = output / "axis_adapter"
    assert report["package_format"] == "minimal"
    assert report["skills_generated"] == 1
    assert report["dependency_graph"]["mermaid_direct"] is None
    assert not (output / "dependency_graph.mmd").exists()
    assert not (output / "dependency_closure_graph.mmd").exists()
    assert (skill_dir / "skill.json").exists()
    assert (skill_dir / "compact_card.json").exists()
    assert (skill_dir / "rtl" / "axis_adapter.v").exists()
    assert not (skill_dir / "module_info.json").exists()
    assert not (skill_dir / "README.md").exists()
    assert not (skill_dir / "template.v").exists()
    assert not (skill_dir / "quality.json").exists()
    assert not (skill_dir / "examples").exists()

    skill_json = json.loads((skill_dir / "skill.json").read_text(encoding="utf-8"))
    compact_card = json.loads((skill_dir / "compact_card.json").read_text(encoding="utf-8"))
    assert validate_minimal_skill(skill_json) == []
    assert validate_compact_card(compact_card) == []
    assert skill_json["parameters"] == ["S_DATA_WIDTH", "M_DATA_WIDTH"]
    assert skill_json["rtl_files"] == ["rtl/axis_adapter.v"]
    assert len(compact_card["keywords"]) <= 10
    assert len(compact_card["structure"]) <= 4
    assert len(compact_card["retrieval_text"].split()) <= 60

    plan = QueryPlan(
        intent="AXI stream width adapter",
        positive_terms=["axis", "adapter", "width"],
        negative_terms=[],
        likely_categories=["primitive"],
        likely_interfaces=["axis"],
        required_features=["width"],
    )
    results = retrieve_skills(plan, output, limit=3)
    assert results[0].name == "axis_adapter"


def test_builder_rejects_duplicate_modules_without_stopping(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write(repo / "a" / "dup.v", "module dup(input wire clk); endmodule\n")
    write(repo / "b" / "dup.v", "module dup(input wire clk); endmodule\n")
    write(repo / "rtl" / "ok.v", "module ok(input wire clk); endmodule\n")

    output = tmp_path / "skills"
    report = build_skill_library(repo, output, clean=True, candidate_mode="all")

    assert report["skills_generated"] == 1
    assert report["skills_rejected"] == 2
    assert (output / "ok" / "skill.json").exists()
    assert not any(path.name.startswith("dup") for path in output.iterdir() if path.is_dir())
    assert all(
        "duplicate module definition" in " ".join(item["reasons"])
        for item in report["rejected_candidates"]
        if item["root_module"] == "dup"
    )


def test_builder_rejects_large_non_atomic_skill(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    body = "\n".join(f"assign out = in; // {idx}" for idx in range(501))
    write(
        repo / "rtl" / "large.v",
        f"""
module large(input wire in, output wire out);
{body}
endmodule
""",
    )

    report = build_skill_library(repo, tmp_path / "skills", clean=True, candidate_mode="all")

    assert report["skills_generated"] == 0
    assert report["skills_rejected"] == 1
    assert "RTL exceeds 500 lines" in report["rejected_candidates"][0]["reasons"]


def test_builder_rejects_more_than_one_state_machine(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write(
        repo / "rtl" / "two_fsm.v",
        """
module two_fsm(input wire clk, input wire [1:0] state_a, state_b, output reg done);
always @* begin
    case (state_a)
        2'd0: done = 1'b0;
        default: done = 1'b1;
    endcase
end
always @* begin
    case (state_b)
        2'd0: done = 1'b0;
        default: done = 1'b1;
    endcase
end
endmodule
""",
    )

    report = build_skill_library(repo, tmp_path / "skills", clean=True, candidate_mode="all")

    assert report["skills_generated"] == 0
    assert report["skills_rejected"] == 1
    assert "contains more than one state machine" in report["rejected_candidates"][0]["reasons"]


def test_committed_skills_follow_minimal_layout() -> None:
    assert validate_library(Path("skills")) == []


def test_clean_removes_previous_skill_directories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write(repo / "rtl" / "one.v", "module one(input wire clk); endmodule\n")
    output = tmp_path / "skills"
    stale = output / "stale_skill"
    stale.mkdir(parents=True)
    (stale / "old.txt").write_text("old", encoding="utf-8")

    build_skill_library(repo, output, clean=True)
    assert not stale.exists()
    assert (output / "one" / "skill.json").exists()
    assert not (output / "one" / "module_info.json").exists()


# ---------------------------------------------------------------------------
# Semantic annotation tests
# ---------------------------------------------------------------------------


class MockLLMAnnotator:
    """Annotator that returns pre-defined semantic annotations for testing."""

    def __init__(
        self,
        annotation: SemanticAnnotation | None = None,
        backend: str = "mock",
        should_fail: bool = False,
    ) -> None:
        self.annotation = annotation or SemanticAnnotation()
        self.backend = backend
        self.should_fail = should_fail

    def annotate(self, semantic_input: dict) -> AnnotationResult:
        if self.should_fail:
            raise RuntimeError("mock LLM failure")
        return AnnotationResult(
            annotation=self.annotation,
            backend=self.backend,
            llm_used=True,
            warnings=[],
        )


def _arbiter_annotation() -> SemanticAnnotation:
    return SemanticAnnotation(
        core_function="N-port configurable request arbitration",
        algorithm="masked round-robin arbitration",
        structure=["priority encoder", "rotating mask", "registered grant"],
        interface_protocol="request-grant",
        granularity="primitive",
        keywords=[
            "arbiter",
            "round_robin",
            "fixed_priority",
            "mask",
            "onehot_grant",
            "request_acknowledge",
        ],
    )


def _axis_adapter_annotation() -> SemanticAnnotation:
    return SemanticAnnotation(
        core_function="AXI-stream data width conversion",
        algorithm="width adaptation with handshake alignment",
        structure=["width converter", "handshake passthrough"],
        interface_protocol="ready-valid",
        granularity="primitive",
        keywords=[
            "axis",
            "adapter",
            "width_conversion",
            "handshake",
            "ready_valid",
        ],
    )


def _mock_arbiter_module_ir(tmp_path: Path):
    rtl = write(
        tmp_path / "arbiter.v",
        """
module arbiter #(
    parameter PORTS = 4,
    parameter ARB_TYPE_ROUND_ROBIN = 0,
    parameter ARB_BLOCK = 1,
    parameter ARB_BLOCK_ACK = 1,
    parameter ARB_LSB_HIGH_PRIORITY = 0
) (
    input wire clk,
    input wire rst,
    input wire [PORTS-1:0] request,
    input wire [PORTS-1:0] acknowledge,
    output wire [PORTS-1:0] grant,
    output wire grant_valid,
    output wire [$clog2(PORTS)-1:0] grant_encoded
);
    assign grant_valid = |request;
endmodule
""",
    )
    modules = parse_project([rtl])
    hierarchy = build_module_hierarchy(modules)
    candidate = compute_dependency_closure("arbiter", hierarchy)
    return modules[0], candidate, hierarchy


def _mock_axis_adapter_module_ir(tmp_path: Path):
    rtl = write(
        tmp_path / "axis_adapter.v",
        """
module axis_adapter #(
    parameter S_DATA_WIDTH = 8,
    parameter M_DATA_WIDTH = 16
) (
    input wire clk,
    input wire rst,
    input wire [S_DATA_WIDTH-1:0] s_axis_tdata,
    input wire s_axis_tvalid,
    output wire s_axis_tready,
    output wire [M_DATA_WIDTH-1:0] m_axis_tdata,
    output wire m_axis_tvalid,
    input wire m_axis_tready
);
    assign s_axis_tready = m_axis_tready;
    assign m_axis_tvalid = s_axis_tvalid;
endmodule
""",
    )
    modules = parse_project([rtl])
    hierarchy = build_module_hierarchy(modules)
    candidate = compute_dependency_closure("axis_adapter", hierarchy)
    return modules[0], candidate, hierarchy


class TestSemanticAnnotation:
    def test_mock_llm_annotation_merges_into_skill_json(self, tmp_path: Path) -> None:
        """Mock LLM returns semantic annotation → skill.json correctly merges deterministic + semantic."""
        module_ir, candidate, hierarchy = _mock_arbiter_module_ir(tmp_path)
        mock = MockLLMAnnotator(_arbiter_annotation())
        ctx = annotate_module(module_ir, candidate, hierarchy, "test_project", mock)

        skill_json = build_minimal_skill_json(
            module_ir.to_module_info(),
            candidate,
            tmp_path,
            ["rtl/arbiter.v"],
            ctx.merged,
        )

        assert skill_json["core_function"] == "N-port configurable request arbitration"
        assert skill_json["algorithm"] == "masked round-robin arbitration"
        assert "priority_encoder" in skill_json["structure"]
        assert ctx.result.llm_used is True

    def test_deterministic_fields_not_overridden_by_llm(self, tmp_path: Path) -> None:
        """LLM must NOT overwrite deterministic fields (name, parameters, dependencies, rtl_files)."""
        module_ir, candidate, hierarchy = _mock_arbiter_module_ir(tmp_path)
        mock = MockLLMAnnotator(_arbiter_annotation())
        ctx = annotate_module(module_ir, candidate, hierarchy, "test_project", mock)

        skill_json = build_minimal_skill_json(
            module_ir.to_module_info(),
            candidate,
            tmp_path,
            ["rtl/arbiter.v"],
            ctx.merged,
        )

        assert skill_json["name"] == "arbiter"
        assert "PORTS" in skill_json["parameters"]
        assert "ARB_TYPE_ROUND_ROBIN" in skill_json["parameters"]
        assert len(skill_json["parameters"]) == 5
        assert skill_json["rtl_files"] == ["rtl/arbiter.v"]
        assert skill_json["skill_id"] == "arbiter"

    def test_llm_failure_triggers_fallback(self, tmp_path: Path) -> None:
        """When LLM fails, fallback annotation is used and backend is marked 'fallback'."""
        module_ir, candidate, hierarchy = _mock_arbiter_module_ir(tmp_path)
        mock = MockLLMAnnotator(should_fail=True)
        annotator = mock

        try:
            ctx = annotate_module(module_ir, candidate, hierarchy, "test_project", annotator)
        except Exception:
            ctx = annotate_module(module_ir, candidate, hierarchy, "test_project", None)

        assert ctx.result.llm_used is False
        assert ctx.result.backend == "fallback"

    def test_compact_card_derived_from_skill_json_deterministically(self, tmp_path: Path) -> None:
        """compact_card.json is deterministically derived from skill.json; no second LLM call."""
        module_ir, candidate, hierarchy = _mock_axis_adapter_module_ir(tmp_path)
        mock = MockLLMAnnotator(_axis_adapter_annotation())
        ctx = annotate_module(module_ir, candidate, hierarchy, "test_project", mock)

        skill_json = build_minimal_skill_json(
            module_ir.to_module_info(),
            candidate,
            tmp_path,
            ["rtl/axis_adapter.v"],
            ctx.merged,
        )
        card = build_compact_card(skill_json)

        assert card["core_function"] == skill_json["core_function"]
        assert card["algorithm"] == skill_json["algorithm"]
        assert card["structure"] == skill_json["structure"]
        assert card["keywords"] == skill_json["keywords"]
        assert card["granularity"] == skill_json["granularity"]
        assert card["name"] == skill_json["name"]

        assert validate_compact_card(card) == []

    def test_retrieval_text_length_limit_still_passes(self, tmp_path: Path) -> None:
        """Retrieval text must still be ≤ 60 words even with LLM-generated content."""
        module_ir, candidate, hierarchy = _mock_arbiter_module_ir(tmp_path)
        mock = MockLLMAnnotator(_arbiter_annotation())
        ctx = annotate_module(module_ir, candidate, hierarchy, "test_project", mock)

        skill_json = build_minimal_skill_json(
            module_ir.to_module_info(),
            candidate,
            tmp_path,
            ["rtl/arbiter.v"],
            ctx.merged,
        )
        card = build_compact_card(skill_json)

        word_count = len(card["retrieval_text"].split())
        assert word_count <= 60, f"retrieval_text has {word_count} words, should be ≤ 60"

    def test_keywords_normalized_and_truncated(self, tmp_path: Path) -> None:
        """Taxonomy normalizes keywords (dedup, lowercase, underscorify) and truncates to 10."""
        raw = SemanticAnnotation(
            core_function="test",
            algorithm="test",
            structure=["a", "a", "b"],
            interface_protocol="test",
            granularity="primitive",
            keywords=[
                "Round Robin", "round-robin", "FIXED_PRIORITY",
                "Fixed Priority", "ONEHOT", "SKID_BUFFER",
                "Elastic Buffer", "elastic-buffer",
            ],
        )
        result = normalize_annotation(raw)
        norm = result.normalized
        assert "round_robin" in norm.keywords
        assert "fixed_priority" in norm.keywords
        assert "elastic_buffer" in norm.keywords
        assert norm.keywords.count("round_robin") == 1
        assert len(norm.keywords) <= 10

    def test_arbiter_mock_generates_correct_semantics(self, tmp_path: Path) -> None:
        """Arbiter mock case: core_function has 'arbitration', algorithm has 'round-robin' or 'priority'."""
        module_ir, candidate, hierarchy = _mock_arbiter_module_ir(tmp_path)
        mock = MockLLMAnnotator(_arbiter_annotation())
        ctx = annotate_module(module_ir, candidate, hierarchy, "test_project", mock)

        skill_json = build_minimal_skill_json(
            module_ir.to_module_info(),
            candidate,
            tmp_path,
            ["rtl/arbiter.v"],
            ctx.merged,
        )

        assert "arbitration" in skill_json["core_function"].lower()
        assert "round" in skill_json["algorithm"].lower() or "priority" in skill_json["algorithm"].lower()
        structure_text = " ".join(skill_json["structure"]).lower()
        assert any(
            term in structure_text
            for term in ("priority", "encoder", "mask", "grant")
        )

    def test_axis_adapter_mock_generates_correct_semantics(self, tmp_path: Path) -> None:
        """Axis adapter mock case: width conversion, handshake, AXI-stream."""
        module_ir, candidate, hierarchy = _mock_axis_adapter_module_ir(tmp_path)
        mock = MockLLMAnnotator(_axis_adapter_annotation())
        ctx = annotate_module(module_ir, candidate, hierarchy, "test_project", mock)

        skill_json = build_minimal_skill_json(
            module_ir.to_module_info(),
            candidate,
            tmp_path,
            ["rtl/axis_adapter.v"],
            ctx.merged,
        )

        core_lower = skill_json["core_function"].lower()
        alg_lower = skill_json["algorithm"].lower()
        assert any(term in core_lower for term in ("width", "conversion", "adapter"))
        assert any(term in alg_lower for term in ("width", "handshake", "adapt"))

    def test_report_records_semantic_backend(self, tmp_path: Path) -> None:
        """report.json includes 'semantic' section with backend and llm_used flags."""
        repo = tmp_path / "repo"
        write(
            repo / "rtl" / "one.v",
            "module one(input wire clk); assign done = 1'b1; endmodule\n",
        )
        output = tmp_path / "skills"
        mock = MockLLMAnnotator(
            SemanticAnnotation(
                core_function="test module",
                algorithm="test logic",
                structure=["test"],
                interface_protocol="parallel",
                granularity="primitive",
                keywords=["test"],
            ),
            backend="mock",
        )
        report = build_skill_library(repo, output, clean=True, annotator=mock)

        assert "semantic" in report
        assert report["semantic"]["backend"] == "mock"
        assert report["semantic"]["llm_used"] is True
        assert report["semantic"]["fallback_count"] == 0
        assert report["semantic"]["total_modules"] == 1
        assert len(report["semantic"]["per_module"]) == 1

    def test_files_mode_generates_one_skill_per_verilog_file(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        write(repo / "defs.v", "`define DEMO_WIDTH 8\n")
        write(
            repo / "pipe.v",
            """
module pipe_stage
// Params
#(
    parameter WIDTH = 8
)
(
    input wire clk,
    input wire [WIDTH-1:0] data_i,
    output wire [WIDTH-1:0] data_o
);
assign data_o = data_i;
endmodule
""",
        )

        output = tmp_path / "skills"
        report = build_skill_library(repo, output, clean=True, candidate_mode="files", annotator=FallbackAnnotator())

        assert report["rtl_files_scanned"] == 2
        assert report["skills_generated"] == 2
        assert report["candidate_mode"] == "files"
        assert sorted(skill["skill_name"] for skill in report["skills"]) == ["defs", "pipe"]
        defs = json.loads((output / "defs" / "skill.json").read_text())
        assert defs["name"] == "defs"
        assert defs["rtl_files"] == ["rtl/defs.v"]

    def test_no_api_key_uses_fallback_in_tests(self, tmp_path: Path) -> None:
        """When using FallbackAnnotator (no API key), backend is 'fallback' and llm_used=False."""
        repo = tmp_path / "repo"
        write(
            repo / "rtl" / "fifo.v",
            "module async_fifo(input wire wr_clk, rd_clk, rst); endmodule\n",
        )
        output = tmp_path / "skills"
        fallback = FallbackAnnotator()
        report = build_skill_library(repo, output, clean=True, annotator=fallback)

        assert report["semantic"]["llm_used"] is False
        assert report["semantic"]["backend"] == "fallback"
        for skill in report["skills"]:
            assert skill["granularity"] in {"leaf", "primitive", "composite"}
            assert skill["keyword_count"] >= 0

    def test_fallback_marked_with_low_confidence_in_report(self, tmp_path: Path) -> None:
        """Fallback annotations are clearly marked in the report."""
        repo = tmp_path / "repo"
        write(
            repo / "rtl" / "arb.v",
            "module arbiter(input wire clk, rst, request, output wire grant); endmodule\n",
        )
        output = tmp_path / "skills"
        report = build_skill_library(repo, output, clean=True)

        assert report["semantic"]["backend"] == "fallback"
        assert report["semantic"]["llm_used"] is False
        assert report["semantic"]["fallback_count"] == report["semantic"]["total_modules"]

    def test_cli_replays_recorded_semantic_annotations(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        write(
            repo / "rtl" / "one.v",
            "module one(input wire req, output wire grant); assign grant = req; endmodule\n",
        )
        record_path = tmp_path / "semantic.jsonl"
        recording_annotator = OpenAICompatibleAnnotator(
            RecordingReplayLLM(
                SemanticFakeLLM(),
                LLMReplayConfig(record_path=record_path, demo_freeze=True),
            )
        )
        build_skill_library(repo, tmp_path / "recorded", clean=True, annotator=recording_annotator)

        output = tmp_path / "replayed"
        rc = skill_builder_main([
            "build",
            str(repo),
            "--output",
            str(output),
            "--clean",
            "--replay-llm",
            str(record_path),
            "--demo-freeze",
            "--no-color",
        ])

        report = json.loads((output / "report.json").read_text())
        assert rc == 0
        assert report["semantic"]["backend"] == "openai_compatible"
        assert report["semantic"]["llm_used"] is True
        assert report["semantic"]["fallback_count"] == 0

    def test_replay_prompt_mismatch_is_not_silently_fallback(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        write(
            repo / "rtl" / "one.v",
            "module one(input wire req, output wire grant); assign grant = req; endmodule\n",
        )
        record_path = tmp_path / "semantic.jsonl"
        recording_annotator = OpenAICompatibleAnnotator(
            RecordingReplayLLM(
                SemanticFakeLLM(),
                LLMReplayConfig(record_path=record_path, demo_freeze=True),
            )
        )
        build_skill_library(repo, tmp_path / "recorded", clean=True, annotator=recording_annotator)
        records = [json.loads(line) for line in record_path.read_text().splitlines()]
        records[0]["prompt_hash"] = "0" * 64
        record_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        rc = skill_builder_main([
            "build",
            str(repo),
            "--output",
            str(tmp_path / "mismatch"),
            "--clean",
            "--replay-llm",
            str(record_path),
        ])

        assert rc == 1


class TestSemanticInputConstruction:
    def test_semantic_input_contains_ports_parameters_deps(self, tmp_path: Path) -> None:
        """build_semantic_input() captures ports, parameters, and dependencies from ModuleIR."""
        module_ir, candidate, hierarchy = _mock_arbiter_module_ir(tmp_path)
        inp = build_semantic_input(module_ir, candidate, hierarchy, "test_project")

        assert inp.module == "arbiter"
        assert inp.project == "test_project"
        assert inp.candidate_kind == "standalone"
        assert len(inp.parameters) == 5
        assert len(inp.ports) == 7
        assert inp.dependencies == []

    def test_semantic_input_includes_structural_facts(self, tmp_path: Path) -> None:
        """build_semantic_input() includes clock/reset candidates, always blocks, etc."""
        module_ir, candidate, hierarchy = _mock_axis_adapter_module_ir(tmp_path)
        inp = build_semantic_input(module_ir, candidate, hierarchy, "test_project")

        assert "clk" in inp.structural_facts["clock_candidates"]
        assert "rst" in inp.structural_facts["reset_candidates"]
        assert inp.structural_facts["always_blocks"] >= 0
        assert inp.structural_facts["continuous_assignments"] >= 0


class TestMergeDeterministicSemantic:
    def test_merge_does_not_let_llm_output_fields_it_should_not(self, tmp_path: Path) -> None:
        """merge_deterministic_and_semantic only uses semantic fields, never lets LLM set name/skill_id/etc."""
        module_ir, candidate, hierarchy = _mock_arbiter_module_ir(tmp_path)
        annotation = _arbiter_annotation()

        merged = merge_deterministic_and_semantic(module_ir, candidate, "test_project", annotation)

        assert merged["name"] == "arbiter"
        assert merged["skill_id"] == "arbiter"
        assert merged["project"] == "test_project"
        assert merged["parameters"] == [param.name for param in module_ir.parameters if param.kind == "parameter"]
        assert merged["core_function"] == annotation.core_function
        assert merged["algorithm"] == annotation.algorithm
        assert merged["structure"] == annotation.structure
        assert merged["granularity"] == annotation.granularity
