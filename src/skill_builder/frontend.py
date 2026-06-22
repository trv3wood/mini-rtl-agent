from __future__ import annotations

from pathlib import Path

from .instance_extractor import extract_instances_from_pyslang_json
from .models import ModuleIR
from .parser import parse_modules_with_regex


LAST_PARSE_WARNINGS: list[str] = []


def _parse_with_pyslang(path: Path, include_dirs: list[Path], defines: dict[str, str]) -> list[ModuleIR]:
    try:
        import pyslang  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(f"pyslang unavailable: {exc}") from exc

    try:
        syntax_tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
        diagnostics = getattr(syntax_tree, "diagnostics", [])
        diagnostics = list(diagnostics or [])
        if diagnostics:
            detail = "; ".join(str(diagnostic) for diagnostic in diagnostics[:5])
            raise RuntimeError(f"pyslang diagnostics: {detail}")
    except Exception as exc:
        raise RuntimeError(f"pyslang failed for {path}: {exc}") from exc

    source_text = path.read_text(encoding="utf-8", errors="ignore")
    instances_by_module = extract_instances_from_pyslang_json(syntax_tree.to_json(), path, source_text)
    modules = parse_modules_with_regex(path)
    for module in modules:
        module.parse_backend = "pyslang"
        module.syntax_backend = "pyslang"
        module.instance_backend = "pyslang_ast"
        module.parameter_backend = "regex"
        module.port_backend = "regex"
        module.semantic_status = "syntax_only"
        module.instances = instances_by_module.get(module.name, [])
        module.parse_warnings.append(
            "pyslang accepted syntax; ports and parameters still use deterministic fallback extraction"
        )
    return modules


def _merge_modules(modules: list[ModuleIR]) -> list[ModuleIR]:
    merged: list[ModuleIR] = []
    seen: set[tuple[str, str]] = set()
    for module in modules:
        key = (module.name, module.source_file)
        if key in seen:
            module.parse_warnings.append(f"duplicate module ignored: {module.name} in {module.source_file}")
            continue
        seen.add(key)
        merged.append(module)
    return merged


def parse_project(
    rtl_files: list[Path],
    include_dirs: list[Path] | None = None,
    defines: dict[str, str] | None = None,
) -> list[ModuleIR]:
    global LAST_PARSE_WARNINGS
    include_dirs = include_dirs or []
    defines = defines or {}
    modules: list[ModuleIR] = []
    all_warnings: list[str] = []

    for rtl_file in rtl_files:
        file_warnings: list[str] = []
        try:
            parsed = _parse_with_pyslang(rtl_file, include_dirs, defines)
            modules.extend(parsed)
            continue
        except Exception as exc:
            file_warnings.append(f"{rtl_file}: {exc}; falling back to regex parser")

        try:
            parsed = parse_modules_with_regex(rtl_file)
        except Exception as exc:
            file_warnings.append(f"{rtl_file}: regex parser failed: {exc}")
            all_warnings.extend(file_warnings)
            continue

        if not parsed:
            file_warnings.append(f"{rtl_file}: regex parser found no modules")
        for module in parsed:
            module.parse_warnings.extend(file_warnings)
        modules.extend(parsed)
        all_warnings.extend(file_warnings)

    LAST_PARSE_WARNINGS = all_warnings
    return _merge_modules(modules)


def get_last_parse_warnings() -> list[str]:
    return list(LAST_PARSE_WARNINGS)
