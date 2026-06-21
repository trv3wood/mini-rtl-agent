from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.skill_builder.builder import build_skill_library
from src.skill_builder.parser import parse_modules
from src.skill_builder.schema import validate_module_info


class FakeClassifierLLM:
    def complete_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> dict:
        prompt = messages[-1]["content"].lower()
        if "fifo" in prompt:
            return {
                "category": "buffering",
                "interfaces": ["fifo"],
                "patterns": ["fifo"],
                "keywords": ["fifo", "buffering"],
            }
        if "round_robin" in prompt or "arbiter" in prompt:
            return {
                "category": "control",
                "interfaces": ["arbiter"],
                "patterns": ["arbiter"],
                "keywords": ["arbiter", "control"],
            }
        if "reset" in prompt or "sync" in prompt:
            return {
                "category": "cdc",
                "interfaces": ["cdc"],
                "patterns": ["synchronizer"],
                "keywords": ["synchronizer", "cdc"],
            }
        return {
            "category": "control",
            "interfaces": ["rtl"],
            "patterns": ["counter"],
            "keywords": ["counter", "control"],
        }

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        raise AssertionError("skill classifier should request JSON, not text")


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


def test_malformed_file_does_not_crash_builder(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write(repo / "rtl" / "broken.v", "module broken(input wire clk\n")
    report = build_skill_library(repo, tmp_path / "skills", clean=True, llm=FakeClassifierLLM())
    assert report["rtl_files_scanned"] == 1
    assert report["modules_extracted"] == 0
    assert report["skills_generated"] == 0
    assert (tmp_path / "skills" / "report.json").exists()


def test_module_info_schema_reports_missing_required_fields() -> None:
    errors = validate_module_info({"name": "bad"})
    assert errors
    assert any("missing top-level fields" in error for error in errors)


def test_sample_repo_golden_output(tmp_path: Path) -> None:
    repo = Path("work/sample_rtl_repo")
    output = tmp_path / "skills"
    report = build_skill_library(repo, output, clean=True, llm=FakeClassifierLLM())

    assert report["skills_generated"] == 4
    assert (output / "report.json").exists()
    assert all(skill["sim_ok"] for skill in report["skills"])

    for skill in report["skills"]:
        skill_dir = output / skill["skill_name"]
        module_name = skill["name"]
        assert (skill_dir / "module_info.json").exists()
        assert (skill_dir / "README.md").exists()
        assert (skill_dir / "template.v").exists()
        assert (skill_dir / "examples" / "instantiation.v").exists()
        assert (skill_dir / "examples" / f"tb_{module_name}.v").exists()

        module_info = json.loads((skill_dir / "module_info.json").read_text(encoding="utf-8"))
        assert module_info["provenance"]["source_file"]
        assert module_info["provenance"]["detected_module_name"] == module_name
        assert module_info["provenance"]["builder_version"]
        assert module_info["provenance"]["parser_mode"] == "deterministic"
        assert validate_module_info(module_info) == []


def test_clean_removes_previous_skill_directories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write(repo / "rtl" / "one.v", "module one(input wire clk); endmodule\n")
    output = tmp_path / "skills"
    stale = output / "stale_skill"
    stale.mkdir(parents=True)
    (stale / "old.txt").write_text("old", encoding="utf-8")

    build_skill_library(repo, output, clean=True, llm=FakeClassifierLLM())
    assert not stale.exists()
    assert (output / "one" / "module_info.json").exists()
