from __future__ import annotations

from pathlib import Path


RTL_SUFFIXES = {".v", ".sv"}
IGNORE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "build",
    "dist",
    "doc",
    "docs",
    "documentation",
    "image",
    "images",
    "img",
    "out",
    "output",
    "outputs",
    "sim_build",
    "test_output",
    "test_outputs",
    "wave",
    "waves",
    "work",
}
IGNORE_FILE_HINTS = {
    ".vcd",
    ".fst",
    ".gtkw",
    ".log",
    ".out",
    ".vvp",
}
GENERATED_FILE_HINTS = ("generated", "_gen.", ".gen.")


def is_ignored(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & IGNORE_DIR_NAMES:
        return True
    name = path.name.lower()
    if any(hint in name for hint in GENERATED_FILE_HINTS):
        return True
    return any(name.endswith(suffix) for suffix in IGNORE_FILE_HINTS)


def scan_rtl_files(repo_path: Path) -> list[Path]:
    repo_path = repo_path.resolve()
    files: list[Path] = []
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if is_ignored(path.relative_to(repo_path)):
            continue
        if path.suffix.lower() in RTL_SUFFIXES:
            files.append(path)
    return sorted(files)
