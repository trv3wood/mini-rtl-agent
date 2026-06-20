from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .classifier import classify
from .generator import (
    generate_instantiation,
    generate_readme,
    generate_template,
    generate_testbench,
    module_info_json,
    sanitize_skill_name,
    score_skill,
)
from .models import ModuleInfo
from .parser import parse_modules
from .scanner import scan_rtl_files
from .schema import validate_module_info


class SkillBuilderError(RuntimeError):
    pass


def run_testbench(skill_dir: Path, module_name: str) -> tuple[bool, str]:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        return False, "iverilog or vvp not found on PATH"
    template = skill_dir / "template.v"
    tb = skill_dir / "examples" / f"tb_{module_name}.v"
    with tempfile.TemporaryDirectory(prefix=f"skill_{module_name}_", dir="/tmp") as tmpdir:
        sim = Path(tmpdir) / f"{module_name}.vvp"
        compile_run = subprocess.run(
            ["iverilog", "-g2012", "-Wall", "-o", str(sim), str(template), str(tb)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if compile_run.returncode != 0:
            return False, compile_run.stdout.strip()
        try:
            sim_run = subprocess.run(
                ["vvp", str(sim)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return False, "simulation timed out after 5 seconds"
        return sim_run.returncode == 0, sim_run.stdout.strip()


def write_skill(module: ModuleInfo, output_root: Path) -> dict:
    skill_name = sanitize_skill_name(module.name)
    skill_dir = output_root / skill_name
    examples_dir = skill_dir / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)

    module_info_text = module_info_json(module)
    module_info = json.loads(module_info_text)
    schema_errors = validate_module_info(module_info)
    if schema_errors:
        raise SkillBuilderError(f"generated module_info invalid for {module.name}: {schema_errors}")

    (skill_dir / "module_info.json").write_text(module_info_text, encoding="utf-8")
    (skill_dir / "README.md").write_text(generate_readme(module), encoding="utf-8")
    (skill_dir / "template.v").write_text(generate_template(module), encoding="utf-8")
    (examples_dir / "instantiation.v").write_text(generate_instantiation(module), encoding="utf-8")
    (examples_dir / f"tb_{module.name}.v").write_text(generate_testbench(module), encoding="utf-8")

    files_ok = all(
        path.exists()
        for path in (
            skill_dir / "module_info.json",
            skill_dir / "README.md",
            skill_dir / "template.v",
            examples_dir / "instantiation.v",
            examples_dir / f"tb_{module.name}.v",
        )
    )
    sim_ok, sim_log = run_testbench(skill_dir, module.name)
    score = score_skill(module, files_ok, sim_ok)
    return {
        "name": module.name,
        "skill_name": skill_name,
        "source_path": str(module.source_path),
        "category": module.category,
        "patterns": module.patterns,
        "interfaces": module.interfaces,
        "sim_ok": sim_ok,
        "sim_log": sim_log,
        "score": {
            "total": score.total,
            "metadata_completeness": score.metadata_completeness,
            "interface_quality": score.interface_quality,
            "documentation_quality": score.documentation_quality,
            "verification_quality": score.verification_quality,
            "template_usability": score.template_usability,
            "notes": score.notes,
        },
        "schema_ok": not schema_errors,
        "schema_errors": schema_errors,
        "paths": {
            "module_info": str(skill_dir / "module_info.json"),
            "readme": str(skill_dir / "README.md"),
            "template": str(skill_dir / "template.v"),
            "instantiation": str(examples_dir / "instantiation.v"),
            "testbench": str(examples_dir / f"tb_{module.name}.v"),
        },
    }


def clean_output_root(output_root: Path) -> None:
    if not output_root.exists():
        return
    for child in output_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        elif child.name == "report.json":
            child.unlink()


def build_skill_library(repo_path: Path, output_root: Path | None = None, clean: bool = False) -> dict:
    repo_path = repo_path.resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise SkillBuilderError(f"repo_path is not a directory: {repo_path}")
    output_root = (output_root or (Path.cwd() / "skills")).resolve()
    if clean:
        clean_output_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    rtl_files = scan_rtl_files(repo_path)
    modules: list[ModuleInfo] = []
    parse_errors = []
    for rtl_file in rtl_files:
        try:
            modules.extend(classify(module) for module in parse_modules(rtl_file))
        except Exception as exc:  # deterministic builder should report and continue
            parse_errors.append({"path": str(rtl_file), "error": str(exc)})

    skills = [write_skill(module, output_root) for module in modules]
    report = {
        "input_repo": str(repo_path),
        "output_root": str(output_root),
        "rtl_files_scanned": len(rtl_files),
        "modules_extracted": len(modules),
        "skills_generated": len(skills),
        "parse_errors": parse_errors,
        "skills": skills,
    }
    (output_root / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
