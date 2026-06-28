from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ...comparison import compare_benchmark_with_external_skillrouter
from ...models import QueryPlan
from ..rg_rerank.retriever import retrieve_skills
from .export import prepare_skillrouter_benchmark_data, prepare_skillrouter_query_data
from .import_results import fused_payload, fuse_rankings, import_skillrouter_results


DEFAULT_EMBEDDING_MODEL = "pipizhao/SkillRouter-Embedding-0.6B"
DEFAULT_RERANKER_MODEL = "pipizhao/SkillRouter-Reranker-0.6B"


def external_python(external_root: Path) -> Path | str:
    candidate = external_root / ".venv" / "bin" / "python"
    return candidate.absolute() if candidate.exists() else "python3"


def build_skillrouter_command(
    *,
    external_root: Path,
    data_root: Path,
    output_dir: str,
    tiers: list[str],
    mode: str,
    encoder_model: str = DEFAULT_EMBEDDING_MODEL,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    top_k: int = 20,
    encoder_max_length: int = 1024,
    reranker_max_length: int = 1024,
    encoder_batch_size: int = 16,
    reranker_batch_size: int = 4,
) -> list[str]:
    python = external_python(external_root)
    if mode == "retrieval":
        return [
            str(python),
            "-m",
            "src.export_retrieval",
            "--encoder_model_or_path",
            encoder_model,
            "--data_root",
            str(data_root),
            "--tiers",
            *tiers,
            "--top_k",
            str(top_k),
            "--max_length",
            str(encoder_max_length),
            "--batch_size",
            str(encoder_batch_size),
            "--output_dir",
            output_dir,
        ]
    if mode == "pipeline":
        raise ValueError("use build_skillrouter_rerank_command for local query pipeline mode")
    raise ValueError(f"unsupported SkillRouter mode: {mode}")


def build_skillrouter_rerank_command(
    *,
    external_root: Path,
    data_root: Path,
    retrieval_json: Path,
    output_json: Path,
    tier: str,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    reranker_max_length: int = 1024,
    reranker_batch_size: int = 4,
    prompt_format: str = "flat-full",
) -> list[str]:
    python = external_python(external_root)
    script = Path(__file__).resolve().parents[4] / "scripts" / "skillrouter_rerank_query.py"
    return [
        str(python),
        str(script),
        "--external-root",
        str(external_root.resolve()),
        "--data-root",
        str(data_root),
        "--retrieval-json",
        str(retrieval_json),
        "--output-json",
        str(output_json),
        "--reranker-model-or-path",
        reranker_model,
        "--tier",
        tier,
        "--max-length",
        str(reranker_max_length),
        "--batch-size",
        str(reranker_batch_size),
        "--prompt-format",
        prompt_format,
    ]


def build_skillrouter_eval_command(
    *,
    external_root: Path,
    data_root: Path,
    output_dir: str,
    tiers: list[str],
    encoder_model: str = DEFAULT_EMBEDDING_MODEL,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    top_k: int = 20,
    encoder_max_length: int = 1024,
    reranker_max_length: int = 1024,
    encoder_batch_size: int = 16,
    reranker_batch_size: int = 4,
) -> list[str]:
    python = external_python(external_root)
    return [
        str(python),
        "-m",
        "src.run_open_model_eval",
        "--data_root",
        str(data_root),
        "--encoder_model_or_path",
        encoder_model,
        "--reranker_model_or_path",
        reranker_model,
        "--tiers",
        *tiers,
        "--retrieval_top_k",
        str(top_k),
        "--encoder_max_length",
        str(encoder_max_length),
        "--reranker_max_length",
        str(reranker_max_length),
        "--encoder_batch_size",
        str(encoder_batch_size),
        "--reranker_batch_size",
        str(reranker_batch_size),
        "--output_dir",
        output_dir,
    ]


def retrieval_output_path(external_root: Path, output_dir: str, tier: str, mode: str) -> Path:
    subdir = "reranked" if mode == "pipeline" else "retrieval"
    return external_root / output_dir / subdir / f"{tier}.json"


def retrieval_command_output_path(external_root: Path, output_dir: str, tier: str) -> Path:
    return external_root / output_dir / "retrieval" / f"{tier}.json"


def run_external_skillrouter_query(
    plan: QueryPlan,
    *,
    skills_root: Path,
    external_root: Path,
    work_dir: Path,
    output_dir: str,
    task_id: str = "local_query",
    tier: str = "easy",
    mode: str = "retrieval",
    limit: int = 10,
    dry_run: bool = False,
    use_existing: bool = False,
    encoder_model: str = DEFAULT_EMBEDDING_MODEL,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    top_k: int = 20,
    encoder_max_length: int = 1024,
    reranker_max_length: int = 1024,
    encoder_batch_size: int = 16,
    reranker_batch_size: int = 4,
) -> dict[str, Any]:
    if tier not in {"easy", "hard"}:
        raise ValueError("tier must be easy or hard")
    if mode not in {"retrieval", "pipeline"}:
        raise ValueError("mode must be retrieval or pipeline")
    if not external_root.exists():
        raise ValueError(f"external SkillRouter root does not exist: {external_root}")
    prep = prepare_skillrouter_query_data(plan, skills_root, work_dir, tiers=[tier], task_id=task_id)
    retrieval_command = build_skillrouter_command(
        external_root=external_root,
        data_root=work_dir.resolve(),
        output_dir=output_dir,
        tiers=[tier],
        mode="retrieval",
        encoder_model=encoder_model,
        reranker_model=reranker_model,
        top_k=top_k,
        encoder_max_length=encoder_max_length,
        reranker_max_length=reranker_max_length,
        encoder_batch_size=encoder_batch_size,
        reranker_batch_size=reranker_batch_size,
    )
    retrieval_path = retrieval_command_output_path(external_root, output_dir, tier)
    output_path = retrieval_output_path(external_root, output_dir, tier, mode)
    rerank_command = None
    if mode == "pipeline":
        rerank_command = build_skillrouter_rerank_command(
            external_root=external_root,
            data_root=work_dir.resolve(),
            retrieval_json=retrieval_path.resolve(),
            output_json=output_path.resolve(),
            tier=tier,
            reranker_model=reranker_model,
            reranker_max_length=reranker_max_length,
            reranker_batch_size=reranker_batch_size,
        )
    base_payload: dict[str, Any] = {
        "query_plan": plan.to_dict(),
        "prepared": prep,
        "external_root": str(external_root),
        "command": retrieval_command,
        "commands": [retrieval_command, *([rerank_command] if rerank_command else [])],
        "cwd": str(external_root),
        "mode": mode,
        "tier": tier,
        "expected_result": str(output_path),
    }
    if dry_run:
        return {**base_payload, "dry_run": True}

    if use_existing:
        if not output_path.exists():
            raise ValueError(f"expected external SkillRouter output not found: {output_path}")
        lexical = retrieve_skills(plan, skills_root, limit=limit)
        semantic = import_skillrouter_results(output_path, task_id, skills_root, plan, limit=limit)
        fused = fuse_rankings(lexical, semantic, limit=limit)
        return {
            **base_payload,
            "dry_run": False,
            "use_existing": True,
            "status": "ok",
            "fused": fused_payload(plan, lexical, semantic, fused),
        }

    completed = subprocess.run(
        retrieval_command,
        cwd=external_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    run_payload = {
        **base_payload,
        "dry_run": False,
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        return {**run_payload, "status": "external_failed"}
    if rerank_command is not None:
        rerank_completed = subprocess.run(
            rerank_command,
            cwd=external_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        run_payload["rerank_return_code"] = rerank_completed.returncode
        run_payload["rerank_stdout"] = rerank_completed.stdout
        run_payload["rerank_stderr"] = rerank_completed.stderr
        if rerank_completed.returncode != 0:
            return {**run_payload, "status": "external_rerank_failed"}
    lexical = retrieve_skills(plan, skills_root, limit=limit)
    semantic = import_skillrouter_results(output_path, task_id, skills_root, plan, limit=limit)
    fused = fuse_rankings(lexical, semantic, limit=limit)
    return {
        **run_payload,
        "status": "ok",
        "fused": fused_payload(plan, lexical, semantic, fused),
    }


def run_external_skillrouter_benchmark(
    dataset_path: Path,
    *,
    skills_root: Path,
    external_root: Path,
    work_dir: Path,
    output_dir: str,
    tier: str = "easy",
    mode: str = "retrieval",
    limit: int = 10,
    dry_run: bool = False,
    use_existing: bool = False,
    encoder_model: str = DEFAULT_EMBEDDING_MODEL,
    reranker_model: str = DEFAULT_RERANKER_MODEL,
    top_k: int = 20,
    encoder_max_length: int = 1024,
    reranker_max_length: int = 1024,
    encoder_batch_size: int = 16,
    reranker_batch_size: int = 4,
) -> dict[str, Any]:
    if tier not in {"easy", "hard"}:
        raise ValueError("tier must be easy or hard")
    if mode not in {"retrieval", "pipeline"}:
        raise ValueError("mode must be retrieval or pipeline")
    if not external_root.exists():
        raise ValueError(f"external SkillRouter root does not exist: {external_root}")
    prep = prepare_skillrouter_benchmark_data(dataset_path, skills_root, work_dir, tiers=[tier])
    retrieval_command = build_skillrouter_command(
        external_root=external_root,
        data_root=work_dir.resolve(),
        output_dir=output_dir,
        tiers=[tier],
        mode="retrieval",
        encoder_model=encoder_model,
        reranker_model=reranker_model,
        top_k=top_k,
        encoder_max_length=encoder_max_length,
        reranker_max_length=reranker_max_length,
        encoder_batch_size=encoder_batch_size,
        reranker_batch_size=reranker_batch_size,
    )
    retrieval_path = retrieval_command_output_path(external_root, output_dir, tier)
    output_path = retrieval_output_path(external_root, output_dir, tier, mode)
    rerank_command = None
    if mode == "pipeline":
        rerank_command = build_skillrouter_rerank_command(
            external_root=external_root,
            data_root=work_dir.resolve(),
            retrieval_json=retrieval_path.resolve(),
            output_json=output_path.resolve(),
            tier=tier,
            reranker_model=reranker_model,
            reranker_max_length=reranker_max_length,
            reranker_batch_size=reranker_batch_size,
        )
    base_payload: dict[str, Any] = {
        "dataset": str(dataset_path),
        "prepared": prep,
        "external_root": str(external_root),
        "command": retrieval_command,
        "commands": [retrieval_command, *([rerank_command] if rerank_command else [])],
        "cwd": str(external_root),
        "mode": mode,
        "tier": tier,
        "expected_result": str(output_path),
    }
    if dry_run:
        return {**base_payload, "dry_run": True}

    if use_existing:
        if not output_path.exists():
            raise ValueError(f"expected external SkillRouter output not found: {output_path}")
        comparison = compare_benchmark_with_external_skillrouter(
            dataset_path,
            skills_root=skills_root,
            external_json=output_path,
            limit=limit,
        )
        return {**base_payload, "dry_run": False, "use_existing": True, "status": "ok", "comparison": comparison}

    completed = subprocess.run(
        retrieval_command,
        cwd=external_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    run_payload = {
        **base_payload,
        "dry_run": False,
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        return {**run_payload, "status": "external_failed"}
    if rerank_command is not None:
        rerank_completed = subprocess.run(
            rerank_command,
            cwd=external_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        run_payload["rerank_return_code"] = rerank_completed.returncode
        run_payload["rerank_stdout"] = rerank_completed.stdout
        run_payload["rerank_stderr"] = rerank_completed.stderr
        if rerank_completed.returncode != 0:
            return {**run_payload, "status": "external_rerank_failed"}
    comparison = compare_benchmark_with_external_skillrouter(
        dataset_path,
        skills_root=skills_root,
        external_json=output_path,
        limit=limit,
    )
    return {**run_payload, "status": "ok", "comparison": comparison}


def render_command(command: list[str]) -> str:
    return " ".join(json.dumps(part) if " " in part else part for part in command)
