from __future__ import annotations

import argparse
import json
from pathlib import Path

from .minimal import validate_compact_card, validate_minimal_skill, word_count


FORBIDDEN_FILES = {"README.md", "module_info.json", "template.v", "manifest.json", "quality.json"}


def validate_skill_dir(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_path = skill_dir / "skill.json"
    card_path = skill_dir / "compact_card.json"
    if not skill_path.exists():
        errors.append(f"{skill_dir}: missing skill.json")
    if not card_path.exists():
        errors.append(f"{skill_dir}: missing compact_card.json")
    for forbidden in FORBIDDEN_FILES:
        if (skill_dir / forbidden).exists():
            errors.append(f"{skill_dir}: forbidden legacy file {forbidden}")
    for path in skill_dir.iterdir():
        if path.name in {"skill.json", "compact_card.json", "rtl"}:
            continue
        errors.append(f"{skill_dir}: unexpected entry {path.name}")
    for path in skill_dir.rglob("*"):
        if len(path.relative_to(skill_dir).parts) > 2:
            errors.append(f"{skill_dir}: path is deeper than allowed: {path.relative_to(skill_dir)}")
    if not skill_path.exists() or not card_path.exists():
        return errors
    try:
        skill = json.loads(skill_path.read_text(encoding="utf-8"))
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [*errors, f"{skill_dir}: invalid JSON: {exc}"]
    errors.extend(f"{skill_dir}: {error}" for error in validate_minimal_skill(skill))
    errors.extend(f"{skill_dir}: {error}" for error in validate_compact_card(card))
    rtl_files = [str(item) for item in skill.get("rtl_files", [])]
    expected_files = {skill_path, card_path}
    for rtl_file in rtl_files:
        rtl_path = skill_dir / rtl_file
        if not rtl_file.startswith("rtl/") or not rtl_path.exists():
            errors.append(f"{skill_dir}: rtl file not found under rtl/: {rtl_file}")
        expected_files.add(rtl_path)
    for path in skill_dir.rglob("*"):
        if path.is_file() and path not in expected_files:
            errors.append(f"{skill_dir}: file is not declared in minimal package: {path.relative_to(skill_dir)}")
    if word_count(card.get("retrieval_text", "")) > 60:
        errors.append(f"{skill_dir}: retrieval_text exceeds 60 words")
    return errors


def validate_library(root: Path) -> list[str]:
    if not root.exists():
        return [f"skills root does not exist: {root}"]
    skill_dirs = [path for path in sorted(root.iterdir()) if path.is_dir()]
    if not skill_dirs:
        return [f"no skill directories found: {root}"]
    errors: list[str] = []
    for skill_dir in skill_dirs:
        errors.extend(validate_skill_dir(skill_dir))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate minimal RTL skill packages.")
    parser.add_argument("skills_root", nargs="?", default="skills")
    args = parser.parse_args()
    errors = validate_library(Path(args.skills_root))
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"validated minimal skills: {args.skills_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
