from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def build_cpp_reference(
    *,
    cpp_dir: Path,
    compiler: str = "g++",
    std: str = "c++17",
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    compiler_path = shutil.which(compiler)
    if compiler_path is None and compiler == "g++":
        compiler_path = shutil.which("clang++")
        compiler = "clang++"
    if compiler_path is None:
        return {
            "status": "skipped",
            "reason": "missing_cpp_compiler",
            "command": [compiler],
            "returncode": None,
            "stdout": "",
            "stderr": f"missing C++ compiler: {compiler}",
        }
    source_files = sorted(path.name for path in cpp_dir.glob("*_ref.cpp") if not path.name.startswith("test_"))
    test_files = sorted(path.name for path in cpp_dir.glob("test_*_ref.cpp"))
    if not source_files or not test_files:
        return {
            "status": "failed",
            "command": [compiler_path],
            "returncode": 1,
            "stdout": "",
            "stderr": "missing generated C++ source or test file",
        }
    exe = cpp_dir / "ref_test"
    command = [compiler_path, f"-std={std}", "-Wall", "-Wextra", "-pedantic", *source_files, *test_files, "-o", exe.name]
    run = subprocess.run(
        command,
        cwd=cpp_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "status": "passed" if run.returncode == 0 else "failed",
        "command": command,
        "returncode": run.returncode,
        "stdout": run.stdout,
        "stderr": run.stderr,
    }


def run_cpp_reference_tests(
    *,
    cpp_dir: Path,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    exe = cpp_dir / "ref_test"
    if not exe.exists():
        return {
            "status": "skipped",
            "reason": "missing_test_executable",
            "command": [str(exe)],
            "returncode": None,
            "stdout": "",
            "stderr": "C++ reference test executable does not exist",
        }
    command = ["./ref_test"]
    run = subprocess.run(
        command,
        cwd=cpp_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "status": "passed" if run.returncode == 0 else "failed",
        "command": command,
        "returncode": run.returncode,
        "stdout": run.stdout,
        "stderr": run.stderr,
    }


def write_report(
    report: dict[str, Any],
    output_path: Path,
) -> Path:
    if "status" not in report:
        raise ValueError("report.status is required")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
