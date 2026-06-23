from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.skill_retriever.benchmark import run_benchmark
from src.skill_retriever.cli import load_query_plan
from src.skill_retriever.comparison import compare_benchmark_with_external_skillrouter, compare_with_external_skillrouter
from src.skill_retriever.external_skillrouter import (
    build_skillrouter_rerank_command,
    run_external_skillrouter_benchmark,
    run_external_skillrouter_query,
)
from src.skill_retriever.models import QueryPlan
from src.skill_retriever.retriever import retrieve_skills
from src.skill_retriever.reporting import (
    render_skillrouter_benchmark_markdown,
    render_skillrouter_goal_alignment_markdown,
    skillrouter_goal_alignment_payload,
)
from src.skill_retriever.router_response import build_router_response
from src.skill_retriever.skillrouter_export import (
    export_skillrouter_records,
    prepare_skillrouter_benchmark_data,
    prepare_skillrouter_query_data,
)
from src.skill_retriever.skillrouter_import import fuse_rankings, import_skillrouter_results
from src.skill_retriever.tools import retrieve_rtl_skills_impl, route_rtl_skill_impl


def write_query_plan(path: Path, **overrides) -> Path:
    data = {
        "intent": "fair arbiter with acknowledge",
        "positive_terms": ["fair", "arbiter", "grant", "request", "acknowledge"],
        "negative_terms": [],
        "likely_categories": ["control"],
        "likely_interfaces": ["arbiter"],
        "required_features": ["acknowledge", "round_robin"],
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_valid_query_plan_loads(tmp_path: Path) -> None:
    plan = load_query_plan(write_query_plan(tmp_path / "query_plan.json"))
    assert plan.intent == "fair arbiter with acknowledge"
    assert "arbiter" in plan.positive_terms


def test_missing_query_plan_fields_fail_gracefully(tmp_path: Path) -> None:
    path = tmp_path / "bad_query_plan.json"
    path.write_text(json.dumps({"intent": "bad"}), encoding="utf-8")
    run = subprocess.run(
        ["python3", "-m", "skill_retriever", "search", str(path), "--skills-root", "skills"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert run.returncode == 1
    assert "missing required fields" in run.stdout


def test_missing_query_plan_file_fails_gracefully(tmp_path: Path) -> None:
    run = subprocess.run(
        ["python3", "-m", "skill_retriever", "search", str(tmp_path / "missing.json"), "--skills-root", "skills"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert run.returncode == 1
    assert "query_plan not found or unreadable" in run.stdout
    assert "Traceback" not in run.stderr


def test_curated_arbiter_query_ranks_round_robin_first(tmp_path: Path) -> None:
    plan = load_query_plan(write_query_plan(tmp_path / "query_plan.json"))
    results = retrieve_skills(plan, Path("skills"), limit=3)
    assert results[0].name == "round_robin_arbiter"
    assert results[0].score > 0
    assert any("category matched" in why for why in results[0].why_matched)


def test_negative_term_penalty_ranks_sync_fifo_above_async_fifo() -> None:
    plan = QueryPlan(
        intent="fifo not async",
        positive_terms=["fifo", "queue", "full", "empty"],
        negative_terms=["async"],
        likely_categories=["buffering"],
        likely_interfaces=["fifo"],
        required_features=[],
    )
    results = retrieve_skills(plan, Path("skills"), limit=5)
    names = [result.name for result in results]
    assert names.index("sync_fifo") < names.index("async_fifo")
    async_result = next(result for result in results if result.name == "async_fifo")
    assert async_result.penalties


def test_skill_spec_retrieval_text_participates_in_recall_and_scoring(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    generic = skills_root / "generic_register"
    semantic = skills_root / "axis_latency_guard"
    generic.mkdir(parents=True)
    semantic.mkdir(parents=True)
    base_info = {
        "category": "rtl",
        "interfaces": [],
        "patterns": [],
        "ports": [],
        "parameters": [],
        "constraints": [],
        "keywords": [],
    }
    (generic / "module_info.json").write_text(
        json.dumps({"name": "generic_register", **base_info}),
        encoding="utf-8",
    )
    (generic / "README.md").write_text("plain register", encoding="utf-8")
    (semantic / "module_info.json").write_text(
        json.dumps({"name": "axis_latency_guard", **base_info}),
        encoding="utf-8",
    )
    (semantic / "skill_spec.json").write_text(
        json.dumps(
            {
                "retrieval_text": "AXI Stream latency guard preserves ready valid backpressure ordering",
                "unknowns": ["Latency bound is unverified."],
                "claims": [
                    {
                        "kind": "behavior",
                        "claim": "Preserves ready valid backpressure ordering.",
                        "status": "inferred",
                        "evidence_ids": ["E_PORT_001"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (semantic / "adaptation.json").write_text(
        json.dumps(
            {
                "customizable_parameters": [{"name": "DATA_WIDTH", "default": "32"}],
                "modification_risks": ["Changing interface width requires revalidation."],
                "revalidation_required": ["source_compile", "smoke_simulation"],
            }
        ),
        encoding="utf-8",
    )
    plan = QueryPlan(
        intent="ready valid latency guard",
        positive_terms=["latency", "ready", "valid"],
        negative_terms=[],
        likely_categories=[],
        likely_interfaces=[],
        required_features=["backpressure ordering"],
    )
    results = retrieve_skills(plan, skills_root, limit=5)
    assert results[0].name == "axis_latency_guard"
    assert any("skill_spec" in why for why in results[0].why_matched)
    assert "Latency bound is unverified." in results[0].risks
    assert "set parameter DATA_WIDTH (default 32)" in results[0].adaptation_hints


def test_cli_table_and_json_output(tmp_path: Path) -> None:
    query_plan = write_query_plan(tmp_path / "query_plan.json")
    table_run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "search",
            str(query_plan),
            "--skills-root",
            "skills",
            "--limit",
            "2",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "round_robin_arbiter" in table_run.stdout
    assert "rank" in table_run.stdout

    json_run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "search",
            str(query_plan),
            "--skills-root",
            "skills",
            "--format",
            "json",
            "--limit",
            "1",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(json_run.stdout)
    assert payload["query_plan"]["intent"] == "fair arbiter with acknowledge"
    assert payload["results"][0]["name"] == "round_robin_arbiter"


def test_router_response_matches_goal_contract_for_local_ranking(tmp_path: Path) -> None:
    query_plan = write_query_plan(
        tmp_path / "query_plan.json",
        intent="design a UART transmitter",
        positive_terms=["uart", "transmitter", "ready", "valid", "busy"],
        negative_terms=["receiver"],
        likely_categories=["serial"],
        likely_interfaces=["uart", "ready_valid"],
        required_features=["busy"],
    )
    plan = load_query_plan(query_plan)
    ranked = retrieve_skills(plan, Path("skills"), limit=5)
    payload = build_router_response(plan, ranked, limit=5)
    assert payload["selected_skill"] == "uart_tx"
    assert "uart_tx" in payload["candidate_skills"]
    assert "interface: uart" in payload["matched_capabilities"]
    assert payload["source_path"].endswith("skills/uart_tx/template.v")
    assert payload["results"][0]["name"] == "uart_tx"


def test_cli_route_outputs_goal_contract_with_external_fusion(tmp_path: Path) -> None:
    query_plan = write_query_plan(
        tmp_path / "query_plan.json",
        intent="design a UART transmitter",
        positive_terms=["uart", "transmitter"],
        negative_terms=[],
        likely_categories=["serial"],
        likely_interfaces=["uart"],
        required_features=["busy"],
    )
    external_json = tmp_path / "external.json"
    external_json.write_text(json.dumps({"local_query": ["uart_tx"]}), encoding="utf-8")
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "route",
            str(query_plan),
            "--skills-root",
            "skills",
            "--external-json",
            str(external_json),
            "--limit",
            "3",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(run.stdout)
    assert payload["selected_skill"] == "uart_tx"
    assert payload["candidate_skills"][0] == "uart_tx"
    assert payload["source_path"].endswith("skills/uart_tx/template.v")
    assert any("external SkillRouter rank 1" in why for why in payload["results"][0]["why_matched"])


def test_export_skillrouter_pool_prefers_skill_spec_and_falls_back_to_module_info(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    spec_skill = skills_root / "spec_skill"
    fallback_skill = skills_root / "fallback_skill"
    spec_skill.mkdir(parents=True)
    fallback_skill.mkdir(parents=True)
    (spec_skill / "module_info.json").write_text(
        json.dumps(
            {
                "name": "spec_skill",
                "description": "module info description",
                "category": "buffering",
                "interfaces": ["ready_valid"],
            }
        ),
        encoding="utf-8",
    )
    (spec_skill / "skill_spec.json").write_text(
        json.dumps(
            {
                "skill_id": "spec_skill",
                "retrieval_text": "semantic ready valid skid buffer retrieval text",
                "claims": [
                    {
                        "kind": "function",
                        "status": "inferred",
                        "claim": "Provides ready valid buffering.",
                    }
                ],
                "unknowns": ["Latency is unverified."],
            }
        ),
        encoding="utf-8",
    )
    (fallback_skill / "module_info.json").write_text(
        json.dumps(
            {
                "name": "fallback_skill",
                "description": "Fallback description from module info.",
                "category": "serial",
                "interfaces": ["uart"],
            }
        ),
        encoding="utf-8",
    )
    (fallback_skill / "README.md").write_text("Fallback README body.", encoding="utf-8")

    records = export_skillrouter_records(skills_root)
    by_id = {record["skill_id"]: record for record in records}
    assert set(by_id) == {"spec_skill", "fallback_skill"}
    assert "semantic ready valid skid buffer retrieval text" in by_id["spec_skill"]["body"]
    assert "Provides ready valid buffering." in by_id["spec_skill"]["description"]
    assert "Fallback description from module info." in by_id["fallback_skill"]["description"]
    assert "Fallback README body." in by_id["fallback_skill"]["body"]


def test_cli_export_skillrouter_pool(tmp_path: Path) -> None:
    output = tmp_path / "pool.jsonl"
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "export-skillrouter-pool",
            "--skills-root",
            "skills",
            "--output",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "exported" in run.stdout
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines
    first = json.loads(lines[0])
    assert {"skill_id", "name", "description", "body"} <= first.keys()


def test_prepare_skillrouter_query_data_writes_tasks_and_pool(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill = skills_root / "uart_tx"
    skill.mkdir(parents=True)
    (skill / "module_info.json").write_text(
        json.dumps({"name": "uart_tx", "description": "UART transmitter", "category": "serial"}),
        encoding="utf-8",
    )
    plan = QueryPlan(
        intent="design a UART transmitter",
        positive_terms=["uart", "transmitter"],
        negative_terms=["receiver"],
        likely_categories=["serial"],
        likely_interfaces=["uart"],
        required_features=["busy output"],
    )
    output_dir = tmp_path / "skillrouter_data"
    payload = prepare_skillrouter_query_data(plan, skills_root, output_dir, tiers=["easy", "hard"], task_id="uart_query")
    assert payload["records"] == 1
    task = json.loads((output_dir / "tasks.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert task["task_id"] == "uart_query"
    assert "design a UART transmitter" in task["instruction_text"]
    assert "avoid: receiver" in task["instruction_text"]
    assert (output_dir / "easy" / "part-00000.jsonl").exists()
    assert (output_dir / "hard" / "part-00000.jsonl").exists()
    record = json.loads((output_dir / "easy" / "part-00000.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["skill_id"] == "uart_tx"
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["records"] == 1


def test_prepare_skillrouter_benchmark_data_writes_tasks_relevance_and_pool(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart", "transmitter"],
                            "negative_terms": [],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "skillrouter_benchmark"
    payload = prepare_skillrouter_benchmark_data(dataset, Path("skills"), output_dir, tiers=["easy", "hard"])
    assert payload["tasks"] == 1
    assert payload["records"] >= 1
    task = json.loads((output_dir / "tasks.jsonl").read_text(encoding="utf-8").splitlines()[0])
    relevance = json.loads((output_dir / "relevance.json").read_text(encoding="utf-8"))
    assert task["task_id"] == "uart_case"
    assert task["skill_names"] == ["uart_tx"]
    assert relevance["uart_case"]["gt_skill_ids"] == ["uart_tx"]
    assert (output_dir / "easy" / "part-00000.jsonl").exists()
    assert (output_dir / "hard" / "part-00000.jsonl").exists()


def test_cli_prepare_skillrouter_query_prints_external_command(tmp_path: Path) -> None:
    query_plan = write_query_plan(tmp_path / "query_plan.json")
    output_dir = tmp_path / "skillrouter_data"
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "prepare-skillrouter-query",
            str(query_plan),
            "--skills-root",
            "skills",
            "--output-dir",
            str(output_dir),
            "--tier",
            "easy",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "prepared" in run.stdout
    assert "src.export_retrieval" in run.stdout
    assert (output_dir / "tasks.jsonl").exists()
    assert (output_dir / "easy" / "part-00000.jsonl").exists()


def test_cli_prepare_skillrouter_benchmark_prints_external_command(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart"],
                            "negative_terms": [],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "skillrouter_benchmark"
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "prepare-skillrouter-benchmark",
            str(dataset),
            "--skills-root",
            "skills",
            "--output-dir",
            str(output_dir),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "prepared 1 task" in run.stdout
    assert "src.export_retrieval" in run.stdout
    assert "outputs/local_rtl_benchmark" in run.stdout
    assert (output_dir / "tasks.jsonl").exists()
    assert (output_dir / "easy" / "part-00000.jsonl").exists()


def test_import_and_fuse_external_skillrouter_results(tmp_path: Path) -> None:
    retrieval_json = tmp_path / "easy.json"
    retrieval_json.write_text(
        json.dumps({"local_query": ["uart_tx", "axis_handshake_buffer"]}),
        encoding="utf-8",
    )
    plan = QueryPlan(
        intent="uart transmitter",
        positive_terms=["uart", "transmitter", "ready", "valid"],
        negative_terms=[],
        likely_categories=["serial"],
        likely_interfaces=["uart", "ready_valid"],
        required_features=["busy"],
    )
    lexical = retrieve_skills(plan, Path("skills"), limit=5)
    semantic = import_skillrouter_results(retrieval_json, "local_query", Path("skills"), plan, limit=5)
    fused = fuse_rankings(lexical, semantic, limit=5)
    assert semantic[0].name == "uart_tx"
    assert any("external SkillRouter rank 1" in why for why in semantic[0].why_matched)
    assert fused[0].name == "uart_tx"
    assert fused[0].score >= lexical[0].score


def test_import_external_skillrouter_missing_task_fails(tmp_path: Path) -> None:
    retrieval_json = tmp_path / "easy.json"
    retrieval_json.write_text(json.dumps({"other": ["uart_tx"]}), encoding="utf-8")
    plan = QueryPlan(
        intent="uart",
        positive_terms=["uart"],
        negative_terms=[],
        likely_categories=[],
        likely_interfaces=[],
        required_features=[],
    )
    try:
        import_skillrouter_results(retrieval_json, "missing", Path("skills"), plan)
    except ValueError as exc:
        assert "task_id not found" in str(exc)
    else:
        raise AssertionError("missing task id should fail")


def test_cli_fuse_skillrouter_results_outputs_json(tmp_path: Path) -> None:
    query_plan = write_query_plan(
        tmp_path / "query_plan.json",
        intent="uart transmitter",
        positive_terms=["uart", "transmitter"],
        likely_categories=["serial"],
        likely_interfaces=["uart"],
        required_features=["busy"],
    )
    retrieval_json = tmp_path / "easy.json"
    retrieval_json.write_text(json.dumps({"local_query": ["uart_tx"]}), encoding="utf-8")
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "fuse-skillrouter-results",
            str(query_plan),
            "--skills-root",
            "skills",
            "--retrieval-json",
            str(retrieval_json),
            "--task-id",
            "local_query",
            "--limit",
            "3",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(run.stdout)
    assert payload["semantic_results"][0]["name"] == "uart_tx"
    assert payload["results"][0]["name"] == "uart_tx"
    assert payload["router_response"]["selected_skill"] == "uart_tx"


def test_compare_with_external_skillrouter_summarizes_rankings(tmp_path: Path) -> None:
    external_json = tmp_path / "reranked.json"
    external_json.write_text(
        json.dumps({"local_query": ["axis_handshake_buffer", "uart_tx"]}),
        encoding="utf-8",
    )
    plan = QueryPlan(
        intent="uart transmitter",
        positive_terms=["uart", "transmitter", "ready", "valid"],
        negative_terms=[],
        likely_categories=["serial"],
        likely_interfaces=["uart", "ready_valid"],
        required_features=["busy"],
    )
    payload = compare_with_external_skillrouter(
        plan,
        skills_root=Path("skills"),
        external_json=external_json,
        task_id="local_query",
        limit=5,
    )
    assert payload["comparison"]["local_top1"] == "uart_tx"
    assert payload["comparison"]["external_top1"] == "axis_handshake_buffer"
    assert payload["comparison"]["semantic_scored_top1"] == "uart_tx"
    assert payload["comparison"]["fused_top1"] in {"uart_tx", "axis_handshake_buffer"}
    assert "uart_tx" in payload["comparison"]["local_external_overlap"]


def test_cli_compare_skillrouter_query_outputs_table_and_json(tmp_path: Path) -> None:
    query_plan = write_query_plan(
        tmp_path / "query_plan.json",
        intent="uart transmitter",
        positive_terms=["uart", "transmitter"],
        likely_categories=["serial"],
        likely_interfaces=["uart"],
        required_features=["busy"],
    )
    external_json = tmp_path / "retrieval.json"
    external_json.write_text(json.dumps({"local_query": ["uart_tx"]}), encoding="utf-8")
    table_run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "compare-skillrouter-query",
            str(query_plan),
            "--skills-root",
            "skills",
            "--external-json",
            str(external_json),
            "--limit",
            "3",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "local top1:" in table_run.stdout
    assert "external top1:" in table_run.stdout
    assert "fused ranking:" in table_run.stdout

    json_run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "compare-skillrouter-query",
            str(query_plan),
            "--skills-root",
            "skills",
            "--external-json",
            str(external_json),
            "--limit",
            "3",
            "--format",
            "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(json_run.stdout)
    assert payload["comparison"]["external_top1"] == "uart_tx"
    assert payload["results"][0]["name"] == "uart_tx"


def test_compare_benchmark_with_external_skillrouter_computes_metrics(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart", "transmitter", "busy"],
                            "negative_terms": ["receiver"],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    },
                    {
                        "id": "fifo_case",
                        "query_plan": {
                            "intent": "single clock fifo",
                            "positive_terms": ["fifo", "single clock", "full", "empty"],
                            "negative_terms": ["async"],
                            "likely_categories": ["buffering"],
                            "likely_interfaces": ["fifo"],
                            "required_features": ["full", "empty"],
                        },
                        "relevant_skill_ids": ["sync_fifo"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    external_json = tmp_path / "external.json"
    external_json.write_text(
        json.dumps(
            {
                "uart_case": ["axis_handshake_buffer", "uart_tx"],
                "fifo_case": ["sync_fifo", "async_fifo"],
            }
        ),
        encoding="utf-8",
    )
    payload = compare_benchmark_with_external_skillrouter(
        dataset,
        skills_root=Path("skills"),
        external_json=external_json,
        limit=5,
    )
    assert payload["case_count"] == 2
    assert payload["metrics"]["external"]["hit_at_1"] == 0.5
    assert payload["metrics"]["local"]["hit_at_1"] == 1.0
    assert payload["metrics"]["fused"]["hit_at_1"] >= payload["metrics"]["external"]["hit_at_1"]
    assert payload["cases"][0]["external_first_relevant_rank"] == 2


def test_cli_compare_skillrouter_benchmark_outputs_table_and_json(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart", "transmitter"],
                            "negative_terms": [],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    external_json = tmp_path / "external.json"
    external_json.write_text(json.dumps({"uart_case": ["uart_tx"]}), encoding="utf-8")
    table_run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "compare-skillrouter-benchmark",
            str(dataset),
            "--skills-root",
            "skills",
            "--external-json",
            str(external_json),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "semantic_scored" in table_run.stdout
    assert "uart_case" in table_run.stdout

    json_run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "compare-skillrouter-benchmark",
            str(dataset),
            "--skills-root",
            "skills",
            "--external-json",
            str(external_json),
            "--format",
            "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(json_run.stdout)
    assert payload["metrics"]["external"]["hit_at_1"] == 1.0
    assert payload["cases"][0]["fused_ranked_skill_ids"][0] == "uart_tx"


def test_skillrouter_benchmark_markdown_report_renders_metrics(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart", "transmitter"],
                            "negative_terms": [],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    external_json = tmp_path / "external.json"
    external_json.write_text(json.dumps({"uart_case": ["uart_tx"]}), encoding="utf-8")
    payload = compare_benchmark_with_external_skillrouter(
        dataset,
        skills_root=Path("skills"),
        external_json=external_json,
        limit=5,
    )
    markdown = render_skillrouter_benchmark_markdown(payload)
    assert "# SkillRouter Benchmark Comparison" in markdown
    assert "| local | 1.000 | 1.000 |" in markdown
    assert "| uart_case | uart_tx | 1 | 1 | 1 | 1 |" in markdown


def test_skillrouter_goal_alignment_report_lists_boundaries() -> None:
    payload = skillrouter_goal_alignment_payload()
    markdown = render_skillrouter_goal_alignment_markdown(payload)
    assert payload["status"] == "external_skillrouter_optional_adapter_integrated"
    assert "Use paper SkillRouter embedding retriever" in markdown
    assert "Long GPU model runs remain user-triggered" in markdown


def test_cli_skillrouter_status_writes_reports_without_breaking_json(tmp_path: Path) -> None:
    report_md = tmp_path / "status.md"
    report_json = tmp_path / "status.json"
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "skillrouter-status",
            "--report-md",
            str(report_md),
            "--report-json",
            str(report_json),
            "--format",
            "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(run.stdout)
    assert payload["goal"] == "GOAL.md section 7 Skill Router"
    assert report_md.exists()
    assert report_json.exists()
    assert "SkillRouter GOAL Alignment" in report_md.read_text(encoding="utf-8")


def test_cli_compare_skillrouter_benchmark_writes_reports_without_breaking_json(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart"],
                            "negative_terms": [],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    external_json = tmp_path / "external.json"
    external_json.write_text(json.dumps({"uart_case": ["uart_tx"]}), encoding="utf-8")
    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "compare-skillrouter-benchmark",
            str(dataset),
            "--skills-root",
            "skills",
            "--external-json",
            str(external_json),
            "--report-md",
            str(report_md),
            "--report-json",
            str(report_json),
            "--format",
            "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(run.stdout)
    assert payload["case_count"] == 1
    assert report_md.exists()
    assert report_json.exists()
    assert "SkillRouter Benchmark Comparison" in report_md.read_text(encoding="utf-8")


def test_external_skillrouter_dry_run_prepares_command_and_data(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    (external_root / ".venv" / "bin").mkdir(parents=True)
    (external_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    plan = QueryPlan(
        intent="uart transmitter",
        positive_terms=["uart", "transmitter"],
        negative_terms=[],
        likely_categories=["serial"],
        likely_interfaces=["uart"],
        required_features=["busy"],
    )
    payload = run_external_skillrouter_query(
        plan,
        skills_root=Path("skills"),
        external_root=external_root,
        work_dir=tmp_path / "skillrouter_data",
        output_dir="outputs/local_rtl_query",
        dry_run=True,
        top_k=7,
    )
    assert payload["dry_run"] is True
    assert payload["prepared"]["records"] >= 1
    assert payload["command"][1:3] == ["-m", "src.export_retrieval"]
    assert Path(payload["command"][0]).is_absolute()
    assert "--top_k" in payload["command"]
    assert "7" in payload["command"]
    assert (tmp_path / "skillrouter_data" / "tasks.jsonl").exists()
    assert (tmp_path / "skillrouter_data" / "easy" / "part-00000.jsonl").exists()


def test_external_skillrouter_pipeline_dry_run_includes_rerank_command(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    (external_root / ".venv" / "bin").mkdir(parents=True)
    (external_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    plan = QueryPlan(
        intent="uart transmitter",
        positive_terms=["uart"],
        negative_terms=[],
        likely_categories=[],
        likely_interfaces=[],
        required_features=[],
    )
    payload = run_external_skillrouter_query(
        plan,
        skills_root=Path("skills"),
        external_root=external_root,
        work_dir=tmp_path / "skillrouter_data",
        output_dir="outputs/local_rtl_query",
        mode="pipeline",
        dry_run=True,
    )
    assert payload["dry_run"] is True
    assert len(payload["commands"]) == 2
    assert payload["commands"][0][1:3] == ["-m", "src.export_retrieval"]
    assert payload["commands"][1][1].endswith("scripts/skillrouter_rerank_query.py")
    assert payload["expected_result"].endswith("outputs/local_rtl_query/reranked/easy.json")


def test_cli_run_skillrouter_query_dry_run_outputs_json(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    external_root.mkdir()
    query_plan = write_query_plan(tmp_path / "query_plan.json")
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "run-skillrouter-query",
            str(query_plan),
            "--skills-root",
            "skills",
            "--external-root",
            str(external_root),
            "--work-dir",
            str(tmp_path / "skillrouter_data"),
            "--dry-run",
            "--format",
            "json",
            "--top-k",
            "5",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(run.stdout)
    assert payload["dry_run"] is True
    assert payload["command"][1:3] == ["-m", "src.export_retrieval"]
    assert payload["prepared"]["records"] >= 1


def test_cli_run_skillrouter_query_pipeline_dry_run_outputs_two_commands(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    external_root.mkdir()
    query_plan = write_query_plan(tmp_path / "query_plan.json")
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "run-skillrouter-query",
            str(query_plan),
            "--skills-root",
            "skills",
            "--external-root",
            str(external_root),
            "--work-dir",
            str(tmp_path / "skillrouter_data"),
            "--mode",
            "pipeline",
            "--dry-run",
            "--format",
            "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(run.stdout)
    assert payload["dry_run"] is True
    assert len(payload["commands"]) == 2
    assert payload["commands"][1][1].endswith("scripts/skillrouter_rerank_query.py")
    assert payload["expected_result"].endswith("reranked/easy.json")


def test_external_skillrouter_benchmark_pipeline_dry_run_includes_commands(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart"],
                            "negative_terms": [],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    external_root = tmp_path / "SkillRouter"
    external_root.mkdir()
    payload = run_external_skillrouter_benchmark(
        dataset,
        skills_root=Path("skills"),
        external_root=external_root,
        work_dir=tmp_path / "skillrouter_benchmark",
        output_dir="outputs/local_rtl_benchmark",
        mode="pipeline",
        dry_run=True,
    )
    assert payload["dry_run"] is True
    assert payload["prepared"]["tasks"] == 1
    assert len(payload["commands"]) == 2
    assert payload["commands"][0][1:3] == ["-m", "src.export_retrieval"]
    assert payload["commands"][1][1].endswith("scripts/skillrouter_rerank_query.py")
    assert payload["expected_result"].endswith("reranked/easy.json")


def test_cli_run_skillrouter_benchmark_use_existing_outputs_comparison_json(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart", "transmitter"],
                            "negative_terms": [],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    external_root = tmp_path / "SkillRouter"
    output = external_root / "outputs" / "local_rtl_benchmark" / "reranked" / "easy.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({"uart_case": ["uart_tx"]}), encoding="utf-8")
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "run-skillrouter-benchmark",
            str(dataset),
            "--skills-root",
            "skills",
            "--external-root",
            str(external_root),
            "--work-dir",
            str(tmp_path / "skillrouter_benchmark"),
            "--mode",
            "pipeline",
            "--use-existing",
            "--format",
            "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(run.stdout)
    assert payload["status"] == "ok"
    assert payload["comparison"]["metrics"]["external"]["hit_at_1"] == 1.0
    assert payload["comparison"]["cases"][0]["fused_ranked_skill_ids"][0] == "uart_tx"


def test_external_skillrouter_use_existing_pipeline_output_fuses_results(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    output = external_root / "outputs" / "local_rtl_query" / "reranked" / "easy.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({"local_query": ["uart_tx", "axis_handshake_buffer"]}), encoding="utf-8")
    plan = QueryPlan(
        intent="uart transmitter",
        positive_terms=["uart", "transmitter"],
        negative_terms=[],
        likely_categories=["serial"],
        likely_interfaces=["uart"],
        required_features=["busy"],
    )
    payload = run_external_skillrouter_query(
        plan,
        skills_root=Path("skills"),
        external_root=external_root,
        work_dir=tmp_path / "skillrouter_data",
        output_dir="outputs/local_rtl_query",
        mode="pipeline",
        use_existing=True,
    )
    assert payload["status"] == "ok"
    assert payload["use_existing"] is True
    assert payload["fused"]["semantic_results"][0]["name"] == "uart_tx"
    assert payload["fused"]["results"][0]["name"] == "uart_tx"


def test_external_skillrouter_use_existing_missing_output_fails(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    external_root.mkdir()
    plan = QueryPlan(
        intent="uart transmitter",
        positive_terms=["uart"],
        negative_terms=[],
        likely_categories=[],
        likely_interfaces=[],
        required_features=[],
    )
    try:
        run_external_skillrouter_query(
            plan,
            skills_root=Path("skills"),
            external_root=external_root,
            work_dir=tmp_path / "skillrouter_data",
            output_dir="outputs/local_rtl_query",
            use_existing=True,
        )
    except ValueError as exc:
        assert "expected external SkillRouter output not found" in str(exc)
    else:
        raise AssertionError("missing external output should fail")


def test_cli_run_skillrouter_query_use_existing_outputs_fused_json(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    output = external_root / "outputs" / "local_rtl_query" / "retrieval" / "easy.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({"local_query": ["uart_tx"]}), encoding="utf-8")
    query_plan = write_query_plan(
        tmp_path / "query_plan.json",
        intent="uart transmitter",
        positive_terms=["uart", "transmitter"],
        likely_categories=["serial"],
        likely_interfaces=["uart"],
        required_features=["busy"],
    )
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "run-skillrouter-query",
            str(query_plan),
            "--skills-root",
            "skills",
            "--external-root",
            str(external_root),
            "--work-dir",
            str(tmp_path / "skillrouter_data"),
            "--use-existing",
            "--format",
            "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(run.stdout)
    assert payload["status"] == "ok"
    assert payload["fused"]["results"][0]["name"] == "uart_tx"
    assert payload["fused"]["router_response"]["selected_skill"] == "uart_tx"


def test_build_skillrouter_rerank_command_shape(tmp_path: Path) -> None:
    command = build_skillrouter_rerank_command(
        external_root=tmp_path,
        data_root=tmp_path / "data",
        retrieval_json=tmp_path / "retrieval" / "easy.json",
        output_json=tmp_path / "reranked" / "easy.json",
        tier="easy",
        reranker_batch_size=1,
    )
    assert command[1].endswith("scripts/skillrouter_rerank_query.py")
    assert "--retrieval-json" in command
    assert str(tmp_path / "retrieval" / "easy.json") in command
    assert "--batch-size" in command


def test_router_benchmark_computes_metrics(tmp_path: Path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "uart_tx_case",
                        "query_plan": {
                            "intent": "uart transmitter",
                            "positive_terms": ["uart", "transmitter", "busy"],
                            "negative_terms": ["receiver"],
                            "likely_categories": ["serial"],
                            "likely_interfaces": ["uart"],
                            "required_features": ["busy"],
                        },
                        "relevant_skill_ids": ["uart_tx"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = run_benchmark(dataset, Path("skills"), limit=10)
    assert payload["case_count"] == 1
    assert payload["metrics"]["hit_at_1"] == 1.0
    assert payload["metrics"]["mrr_at_10"] == 1.0
    assert payload["cases"][0]["first_relevant_rank"] == 1


def test_cli_router_benchmark_json_and_table() -> None:
    json_run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "benchmark",
            "benchmarks/router_benchmark.json",
            "--skills-root",
            "skills",
            "--limit",
            "10",
            "--format",
            "json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(json_run.stdout)
    assert payload["case_count"] == 12
    assert "hit_at_1" in payload["metrics"]

    table_run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "benchmark",
            "benchmarks/router_benchmark.json",
            "--skills-root",
            "skills",
            "--limit",
            "10",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "hit@1=" in table_run.stdout
    assert "uart_transmitter_ready_valid" in table_run.stdout


def test_langchain_tool_impl_invokes_retriever() -> None:
    payload = retrieve_rtl_skills_impl(
        intent="fair arbiter with acknowledge",
        positive_terms=["fair", "arbiter", "grant", "request", "acknowledge"],
        negative_terms=[],
        likely_categories=["control"],
        likely_interfaces=["arbiter"],
        required_features=["acknowledge", "round_robin"],
        skills_root="skills",
        limit=1,
    )
    assert payload["results"][0]["name"] == "round_robin_arbiter"


def test_langchain_route_tool_impl_returns_agent_contract(tmp_path: Path) -> None:
    external_json = tmp_path / "external.json"
    external_json.write_text(json.dumps({"local_query": ["uart_tx"]}), encoding="utf-8")
    payload = route_rtl_skill_impl(
        intent="design a UART transmitter",
        positive_terms=["uart", "transmitter", "busy"],
        negative_terms=[],
        likely_categories=["serial"],
        likely_interfaces=["uart"],
        required_features=["busy"],
        skills_root="skills",
        limit=3,
        external_json=str(external_json),
    )
    assert payload["selected_skill"] == "uart_tx"
    assert payload["candidate_skills"][0] == "uart_tx"
    assert payload["source_path"].endswith("skills/uart_tx/template.v")
