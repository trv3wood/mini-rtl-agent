from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .models import SkillCandidate, VerificationResult, VerificationStageResult


def _tool_missing(command: list[str], tool: str) -> VerificationStageResult:
    return VerificationStageResult("tool_missing", command, None, "", f"{tool} not found on PATH", 0.0)


def _run_command(command: list[str], timeout_seconds: float) -> VerificationStageResult:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return VerificationStageResult(
            "timeout",
            command,
            None,
            exc.stdout or "",
            exc.stderr or "",
            time.monotonic() - start,
        )
    return VerificationStageResult(
        "passed" if completed.returncode == 0 else "failed",
        command,
        completed.returncode,
        completed.stdout.strip(),
        completed.stderr.strip(),
        time.monotonic() - start,
    )


def _skipped(reason: str) -> VerificationStageResult:
    return VerificationStageResult("skipped", [], None, "", reason, 0.0)


def categorize_verification_failure(
    candidate: SkillCandidate,
    source_compile: VerificationStageResult,
    tb_compile: VerificationStageResult,
    simulation: VerificationStageResult,
) -> tuple[str | None, str | None]:
    if any("duplicate module definition" in warning for warning in candidate.hierarchy_warnings):
        return "dependency_closure", "duplicate_module_definition"
    if source_compile.status == "tool_missing" or tb_compile.status == "tool_missing" or simulation.status == "tool_missing":
        return "tool", "tool_missing"
    if not candidate.is_self_contained:
        return "dependency_closure", "dependency_closure_incomplete"
    if source_compile.status in {"failed", "timeout"}:
        category = "source_compile_failed" if source_compile.status == "failed" else "unknown_failure"
        return "source_compile", category
    if tb_compile.status in {"failed", "timeout"}:
        combined = f"{tb_compile.stdout}\n{tb_compile.stderr}".lower()
        category = "unsupported_interface" if "interface" in combined or "modport" in combined else "generated_tb_compile_failed"
        return "generated_tb_compile", category
    if simulation.status == "timeout":
        return "simulation", "simulation_timeout"
    if simulation.status == "failed":
        return "simulation", "simulation_runtime_failed"
    return None, None


def verify_candidate(
    candidate: SkillCandidate,
    skill_dir: Path,
    testbench_path: Path,
    *,
    timeout_seconds: float = 10.0,
) -> VerificationResult:
    source_files = [str(Path(path)) for path in candidate.source_files]
    if shutil.which("iverilog") is None:
        command = ["iverilog", "-g2012", "-Wall", "-s", candidate.root_module, "-o", "", *source_files]
        missing = _tool_missing(command, "iverilog")
        skipped = _skipped("iverilog missing")
        failure_stage, failure_category = categorize_verification_failure(candidate, missing, skipped, skipped)
        return VerificationResult(missing, skipped, skipped, failure_stage, failure_category)

    if not source_files:
        source_compile = VerificationStageResult(
            "failed",
            ["iverilog", "-g2012", "-Wall", "-s", candidate.root_module],
            1,
            "",
            "dependency closure has no source files",
            0.0,
        )
        skipped = _skipped("source compile failed")
        failure_stage, failure_category = categorize_verification_failure(candidate, source_compile, skipped, skipped)
        return VerificationResult(source_compile, skipped, skipped, failure_stage, failure_category)

    with tempfile.TemporaryDirectory(prefix=f"skill_verify_{candidate.root_module}_", dir="/tmp") as tmpdir:
        source_output = str(Path(tmpdir) / "source.vvp")
        source_command = [
            "iverilog",
            "-g2012",
            "-Wall",
            "-s",
            candidate.root_module,
            "-o",
            source_output,
            *source_files,
        ]
        source_compile = _run_command(source_command, timeout_seconds)
        if source_compile.status != "passed":
            skipped = _skipped("source compile did not pass")
            failure_stage, failure_category = categorize_verification_failure(candidate, source_compile, skipped, skipped)
            return VerificationResult(source_compile, skipped, skipped, failure_stage, failure_category)

        tb_output = str(Path(tmpdir) / "tb.vvp")
        tb_command = [
            "iverilog",
            "-g2012",
            "-Wall",
            "-s",
            f"tb_{candidate.root_module}",
            "-o",
            tb_output,
            *source_files,
            str(testbench_path),
        ]
        tb_compile = _run_command(tb_command, timeout_seconds)
        if tb_compile.status != "passed":
            skipped = _skipped("generated testbench compile did not pass")
            failure_stage, failure_category = categorize_verification_failure(candidate, source_compile, tb_compile, skipped)
            return VerificationResult(source_compile, tb_compile, skipped, failure_stage, failure_category)

        if shutil.which("vvp") is None:
            simulation = _tool_missing(["vvp", tb_output], "vvp")
        else:
            simulation = _run_command(["vvp", tb_output], timeout_seconds)
        failure_stage, failure_category = categorize_verification_failure(candidate, source_compile, tb_compile, simulation)
        return VerificationResult(source_compile, tb_compile, simulation, failure_stage, failure_category)
