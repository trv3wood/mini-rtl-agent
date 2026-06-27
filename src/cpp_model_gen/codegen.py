from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model_plan import has_blocking_cpp_model_issue


ALLOWED_CPP_FILES = {"{ip}_ref.h", "{ip}_ref.cpp", "test_{ip}_ref.cpp", "CMakeLists.txt"}


def build_cpp_codegen_prompt(
    *,
    cpp_model_plan: dict[str, Any],
    engineer_spec: dict[str, Any],
) -> list[dict[str, str]]:
    ip_name = str(cpp_model_plan["ip_name"])
    allowed = sorted(pattern.format(ip=ip_name) for pattern in ALLOWED_CPP_FILES)
    return [
        {
            "role": "system",
            "content": (
                "You generate C++17 reference model files from cpp_model.v1. "
                "Use cpp_model.v1 as the source of truth. Use engineer_spec as behavior context. "
                "Return valid JSON only in this envelope: {\"files\":[{\"path\":\"...\",\"content\":\"...\"}]}. "
                "Do not include Markdown. Do not write outside cpp/. Do not include shell commands. "
                f"Only these relative file names are allowed: {', '.join(allowed)}."
            ),
        },
        {
            "role": "user",
            "content": (
                f"cpp_model.v1:\n{json.dumps(cpp_model_plan, indent=2)}\n\n"
                f"engineer_spec.v1:\n{json.dumps(engineer_spec, indent=2)}"
            ),
        },
    ]


def generate_cpp_files(
    *,
    llm_client: Any,
    cpp_model_plan: dict[str, Any],
    engineer_spec: dict[str, Any],
    output_cpp_dir: Path,
    max_repair_attempts: int = 1,
) -> list[Path]:
    if has_blocking_cpp_model_issue(cpp_model_plan):
        raise ValueError("refusing C++ codegen because cpp_model has blocking unknown/conflict or invalid fields")
    messages = build_cpp_codegen_prompt(cpp_model_plan=cpp_model_plan, engineer_spec=engineer_spec)
    last_error = ""
    for attempt in range(max_repair_attempts + 1):
        text = llm_client.complete_text(messages, temperature=0.0)
        try:
            envelope = _parse_json(text)
            files = _write_cpp_envelope(envelope, output_cpp_dir)
            validate_cpp_file_set(files=files, output_cpp_dir=output_cpp_dir, expected_ip_name=str(cpp_model_plan["ip_name"]))
            return files
        except ValueError as exc:
            last_error = str(exc)
            if attempt == max_repair_attempts:
                break
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Repair the C++ file JSON envelope. Return valid JSON only with allowed files under cpp/."
                    ),
                },
                {"role": "user", "content": f"Validation error:\n{last_error}\n\nInvalid envelope:\n{text}"},
            ]
    raise ValueError(f"LLM failed to generate valid C++ file set: {last_error}")


def validate_cpp_file_set(
    *,
    files: list[Path],
    output_cpp_dir: Path,
    expected_ip_name: str,
) -> None:
    required = {
        output_cpp_dir / f"{expected_ip_name}_ref.h",
        output_cpp_dir / f"{expected_ip_name}_ref.cpp",
        output_cpp_dir / f"test_{expected_ip_name}_ref.cpp",
        output_cpp_dir / "CMakeLists.txt",
    }
    actual = {path.resolve() for path in files}
    required_resolved = {path.resolve() for path in required}
    missing = sorted(str(path) for path in required_resolved - actual)
    if missing:
        raise ValueError(f"missing generated C++ file(s): {', '.join(missing)}")
    root = output_cpp_dir.resolve()
    for path in files:
        resolved = path.resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError(f"generated file escapes cpp output dir: {path}")
        text = path.read_text(encoding="utf-8")
        if "#include \"/" in text or "#include </" in text:
            raise ValueError(f"absolute include path is not allowed: {path}")
        if "system(" in text or "popen(" in text:
            raise ValueError(f"shell command execution is not allowed in generated C++: {path}")


def _write_cpp_envelope(envelope: dict[str, Any], output_cpp_dir: Path) -> list[Path]:
    files = envelope.get("files")
    if not isinstance(files, list):
        raise ValueError("C++ codegen envelope must contain files list")
    output_cpp_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("C++ file entry must be an object")
        rel_path = str(item.get("path", ""))
        content = item.get("content")
        if not isinstance(content, str):
            raise ValueError(f"C++ file {rel_path} content must be a string")
        if "/" in rel_path or "\\" in rel_path or rel_path.startswith("."):
            raise ValueError(f"C++ file path must be a simple relative file name: {rel_path}")
        path = output_cpp_dir / rel_path
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def _parse_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
