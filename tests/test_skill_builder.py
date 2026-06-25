from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.skill_builder.builder import build_skill_library
from src.skill_builder.minimal import validate_compact_card, validate_minimal_skill
from src.skill_builder.models import ModuleInfo, SkillCandidate
from src.skill_builder.frontend import parse_project
from src.skill_builder.hierarchy import (
    build_module_hierarchy,
    build_skill_candidates,
    compute_dependency_closure,
    mermaid_dependency_graph,
    module_dependency_graph,
)
from src.skill_builder.parser import parse_modules
from src.skill_builder.validate_minimal_skills import validate_library
from src.skill_retriever.models import QueryPlan
from src.skill_retriever.retriever import retrieve_skills


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


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
    report = build_skill_library(repo, tmp_path / "skills", clean=True)
    assert report["rtl_files_scanned"] == 1
    assert report["modules_extracted"] == 0
    assert report["skills_generated"] == 0
    assert (tmp_path / "skills" / "report.json").exists()


def test_sample_repo_golden_output(tmp_path: Path) -> None:
    repo = Path("work/sample_rtl_repo")
    output = tmp_path / "skills"
    report = build_skill_library(repo, output, clean=True)

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
