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
from src.skill_retriever.user_benchmark import load_user_query_benchmark, run_user_query_benchmark
from src.skill_retriever.workflow import retrieve_for_user_query


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


def write_compact_skill(root: Path, name: str, text: str, *, keywords: list[str] | None = None) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "compact_card.json").write_text(
        json.dumps(
            {
                "skill_id": name,
                "name": name,
                "core_function": text,
                "algorithm": text,
                "structure": keywords or [],
                "interface_signature": text,
                "granularity": "primitive",
                "project": "test",
                "keywords": keywords or [],
                "retrieval_text": text,
            }
        ),
        encoding="utf-8",
    )


class FakeQueryPlannerLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_structured(self, messages: list[dict[str, str]], schema, *, temperature: float = 0.0):
        user_query = messages[-1]["content"]
        self.calls.append(user_query)
        lowered = user_query.lower()
        if "uart" in lowered and ("tx" in lowered or "transmit" in lowered):
            payload = {
                "intent": "design a UART transmitter",
                "positive_terms": ["uart", "transmitter", "ready", "valid", "busy"],
                "negative_terms": ["receiver"],
                "likely_categories": ["serial"],
                "likely_interfaces": ["uart", "ready valid"],
                "required_features": ["busy", "serial transmit"],
            }
        elif "single idle-high line" in lowered:
            payload = {
                "intent": "UART transmitter",
                "positive_terms": ["uart", "transmitter", "serial frame", "start bit", "stop bit"],
                "negative_terms": ["receiver"],
                "likely_categories": ["serial"],
                "likely_interfaces": ["uart"],
                "required_features": ["busy", "frame progress"],
            }
        elif "fifo" in lowered:
            payload = {
                "intent": "single clock fifo",
                "positive_terms": ["fifo", "full", "empty", "queue"],
                "negative_terms": ["async"],
                "likely_categories": ["buffer"],
                "likely_interfaces": ["fifo"],
                "required_features": ["single clock"],
            }
        elif "elastic storage" in lowered:
            payload = {
                "intent": "AXI stream FIFO",
                "positive_terms": ["axis", "stream", "fifo", "burst", "preserve order"],
                "negative_terms": ["register slice"],
                "likely_categories": ["streaming"],
                "likely_interfaces": ["axis", "fifo"],
                "required_features": ["flow control", "burst buffering"],
            }
        elif "fixed precedence" in lowered:
            payload = {
                "intent": "priority encoder",
                "positive_terms": ["priority", "encoder", "fixed precedence", "winning line", "numeric position"],
                "negative_terms": [],
                "likely_categories": ["selection"],
                "likely_interfaces": ["request"],
                "required_features": ["encoded output"],
            }
        elif "pauses for a cycle" in lowered:
            payload = {
                "intent": "AXI stream register skid buffer",
                "positive_terms": ["axis", "register", "skid", "ready", "valid", "backpressure"],
                "negative_terms": [],
                "likely_categories": ["streaming"],
                "likely_interfaces": ["axis", "ready_valid"],
                "required_features": ["hold data", "no drop"],
            }
        elif "different chunk sizes" in lowered:
            payload = {
                "intent": "AXI stream width adapter",
                "positive_terms": ["axis", "stream", "width", "adapter", "ready", "valid"],
                "negative_terms": ["fifo", "storage"],
                "likely_categories": ["streaming"],
                "likely_interfaces": ["axis", "ready_valid"],
                "required_features": ["width conversion", "backpressure"],
            }
        elif "polynomial residue" in lowered:
            payload = {
                "intent": "CRC32 checksum",
                "positive_terms": ["crc32", "checksum", "polynomial", "residue"],
                "negative_terms": [],
                "likely_categories": ["integrity"],
                "likely_interfaces": ["data"],
                "required_features": ["polynomial division"],
            }
        elif "assert exactly one output line" in lowered:
            payload = {
                "intent": "binary to onehot encoder",
                "positive_terms": ["onehot", "encoder", "binary", "output vector"],
                "negative_terms": [],
                "likely_categories": ["encoding"],
                "likely_interfaces": ["combinational"],
                "required_features": ["enable"],
            }
        elif "hardware tally" in lowered:
            payload = {
                "intent": "event counter register",
                "positive_terms": ["counter", "increment", "write", "clear", "control"],
                "negative_terms": [],
                "likely_categories": ["counter"],
                "likely_interfaces": ["register"],
                "required_features": ["software read", "event increment"],
            }
        else:
            payload = {
                "intent": "fair arbiter with acknowledge",
                "positive_terms": ["fair", "arbiter", "grant", "request", "acknowledge"],
                "negative_terms": [],
                "likely_categories": ["control"],
                "likely_interfaces": ["arbiter"],
                "required_features": ["round robin", "acknowledge"],
            }
        return schema.model_validate(payload)

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        raise AssertionError("skill_retriever query workflow must not request free-form text generation")


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
    assert any("arbiter" in why for why in results[0].why_matched)


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


def test_curated_axis_adapter_width_queries_rank_axis_adapter_first() -> None:
    for plan in (
        QueryPlan(
            intent="AXI stream width adapter",
            positive_terms=["axis", "stream", "width", "adapter", "ready", "valid"],
            negative_terms=["fifo", "queue"],
            likely_categories=["streaming"],
            likely_interfaces=["axis"],
            required_features=["width conversion", "handshake alignment"],
        ),
        QueryPlan(
            intent="stream width conversion",
            positive_terms=["stream", "width conversion", "data width", "adapter", "tvalid", "tready"],
            negative_terms=["fifo", "storage"],
            likely_categories=["streaming"],
            likely_interfaces=["axis"],
            required_features=["zero extension", "truncation"],
        ),
    ):
        results = retrieve_skills(plan, Path("skills"), limit=3)
        assert results[0].name == "axis_adapter"


def test_priority_encoder_space_separated_query_matches_underscore_skill() -> None:
    plan = QueryPlan(
        intent="Design a priority encoder for an 8-bit request vector that outputs a valid flag and encoded index.",
        positive_terms=[
            "priority encoder",
            "8-bit request",
            "valid flag",
            "encoded index",
            "combinational logic",
        ],
        negative_terms=[],
        likely_categories=["priority encoder", "arbitration", "combinational logic"],
        likely_interfaces=["input [7:0] request", "output valid", "output [2:0] index"],
        required_features=["determine highest priority", "generate valid flag", "encode index"],
    )

    results = retrieve_skills(plan, Path("skills"), limit=5)

    assert results[0].name == "priority_encoder"
    assert any("priority encoder" in why for why in results[0].why_matched)


def test_compact_card_retrieval_text_participates_in_recall_and_scoring(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    generic = skills_root / "generic_register"
    semantic = skills_root / "axis_latency_guard"
    generic.mkdir(parents=True)
    semantic.mkdir(parents=True)
    (generic / "compact_card.json").write_text(
        json.dumps(
            {
                "skill_id": "generic_register",
                "name": "generic_register",
                "core_function": "Plain register",
                "algorithm": "Register storage",
                "structure": ["register"],
                "interface_signature": "clk -> q",
                "granularity": "primitive",
                "project": "test",
                "keywords": ["register"],
                "retrieval_text": "plain register",
            }
        ),
        encoding="utf-8",
    )
    (semantic / "compact_card.json").write_text(
        json.dumps(
            {
                "skill_id": "axis_latency_guard",
                "name": "axis_latency_guard",
                "core_function": "AXI Stream latency guard",
                "algorithm": "Preserves ready valid backpressure ordering",
                "structure": ["ready valid guard"],
                "interface_signature": "axis",
                "granularity": "primitive",
                "project": "test",
                "keywords": ["axis", "latency", "ready", "valid", "backpressure"],
                "retrieval_text": "AXI Stream latency guard preserves ready valid backpressure ordering",
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
    assert any("retrieval_text" in why for why in results[0].why_matched)


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


def test_cli_search_skillrouter_backend_dry_run_outputs_json(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    external_root.mkdir()
    query_plan = write_query_plan(tmp_path / "query_plan.json")
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "search",
            str(query_plan),
            "--skills-root",
            "skills",
            "--backend",
            "skillrouter",
            "--external-root",
            str(external_root),
            "--work-dir",
            str(tmp_path / "skillrouter_data"),
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
    assert payload["mode"] == "pipeline"
    assert len(payload["commands"]) == 2
    assert payload["commands"][0][1:3] == ["-m", "src.export_retrieval"]
    assert payload["commands"][1][1].endswith("scripts/skillrouter_rerank_query.py")


def test_cli_search_skillrouter_backend_dry_run_outputs_table(tmp_path: Path) -> None:
    external_root = tmp_path / "SkillRouter"
    external_root.mkdir()
    query_plan = write_query_plan(tmp_path / "query_plan.json")
    run = subprocess.run(
        [
            "python3",
            "-m",
            "skill_retriever",
            "search",
            str(query_plan),
            "--skills-root",
            "skills",
            "--backend",
            "skillrouter",
            "--external-root",
            str(external_root),
            "--work-dir",
            str(tmp_path / "skillrouter_data"),
            "--dry-run",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert "prepared SkillRouter query data" in run.stdout
    assert "src.export_retrieval" in run.stdout
    assert "skillrouter_rerank_query.py" in run.stdout


def test_user_query_workflow_with_fake_llm_multiple_queries() -> None:
    llm = FakeQueryPlannerLLM()
    cases = [
        ("Need a UART TX with ready valid input and busy output", "uart_tx"),
        ("Need a single clock FIFO with full and empty flags", "sync_fifo"),
        ("Need a fair arbiter with acknowledge", "round_robin_arbiter"),
    ]

    for query, expected in cases:
        payload = retrieve_for_user_query(query, llm, skills_root=Path("skills"), limit=5)
        assert payload["user_query"] == query
        assert payload["query_plan"]["intent"]
        assert payload["results"][0]["name"] == expected
        assert payload["results"][0]["score"] > 0
        assert payload["results"][0]["why_matched"]

    assert len(llm.calls) == len(cases)


def test_semantic_user_query_benchmark_with_fake_llm(tmp_path: Path) -> None:
    skills_root = tmp_path / "built_skills"
    write_compact_skill(
        skills_root,
        "uart_tx",
        "UART transmitter serial frame start bit stop bit busy frame progress",
        keywords=["uart", "transmitter", "serial", "frame", "busy"],
    )
    write_compact_skill(
        skills_root,
        "axis_fifo",
        "AXI stream FIFO burst buffering flow control preserve order",
        keywords=["axis", "stream", "fifo", "burst", "flow_control"],
    )
    write_compact_skill(
        skills_root,
        "priority_encoder",
        "Priority encoder fixed precedence winning line encoded output numeric position",
        keywords=["priority", "encoder", "fixed_precedence"],
    )
    write_compact_skill(
        skills_root,
        "axis_register",
        "AXI stream register skid buffer ready valid backpressure hold data no drop",
        keywords=["axis", "register", "skid", "ready", "valid"],
    )
    write_compact_skill(
        skills_root,
        "axis_adapter",
        "AXI stream width adapter width conversion backpressure different data widths",
        keywords=["axis", "adapter", "width", "conversion"],
    )
    write_compact_skill(
        skills_root,
        "prim_crc32",
        "CRC32 checksum polynomial residue polynomial division packet integrity",
        keywords=["crc32", "checksum", "polynomial"],
    )
    write_compact_skill(
        skills_root,
        "prim_onehot_enc",
        "Binary to onehot encoder enable output vector exactly one line",
        keywords=["onehot", "encoder", "binary"],
    )
    write_compact_skill(
        skills_root,
        "ibex_counter",
        "Counter increment write clear software read event tally register",
        keywords=["counter", "increment", "register"],
    )

    cases = load_user_query_benchmark(Path("benchmarks/semantic_user_queries.json"))
    assert cases[0].user_query
    assert "UART" not in cases[0].user_query

    payload = run_user_query_benchmark(
        Path("benchmarks/semantic_user_queries.json"),
        skills_root,
        FakeQueryPlannerLLM(),
        limit=5,
    )

    assert payload["case_count"] == len(cases)
    assert payload["metrics"]["hit_at_1"] == 1.0
    for case in payload["cases"]:
        assert case["query_plan"]["positive_terms"]
        assert case["results"][0]["why_matched"]


def test_cli_help_centers_local_query_path() -> None:
    run = subprocess.run(
        ["python3", "-m", "skill_retriever", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "query" in run.stdout
    assert "search" in run.stdout
    assert "user-benchmark" in run.stdout
    assert "compact_card" in run.stdout


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
    assert payload["source_path"].endswith("skills/uart_tx/rtl/uart_tx.v")
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
    assert payload["source_path"].endswith("skills/uart_tx/rtl/uart_tx.v")
    assert any("external SkillRouter rank 1" in why for why in payload["results"][0]["why_matched"])


def test_export_skillrouter_pool_supports_compact_card_only_skills(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "axis_adapter"
    skill.mkdir(parents=True)
    (skill / "compact_card.json").write_text(
        json.dumps(
            {
                "skill_id": "axis_adapter",
                "name": "axis_adapter",
                "core_function": "AXI stream width adapter",
                "algorithm": "width conversion",
                "structure": ["width converter"],
                "interface_signature": "AXIS -> AXIS",
                "granularity": "primitive",
                "project": "test",
                "keywords": ["axis", "adapter", "width"],
                "retrieval_text": "AXI stream width adapter for width conversion.",
            }
        ),
        encoding="utf-8",
    )
    (skill / "skill.json").write_text(
        json.dumps({"skill_id": "axis_adapter", "rtl_files": ["rtl/axis_adapter.v"]}),
        encoding="utf-8",
    )
    records = export_skillrouter_records(tmp_path / "skills")
    assert records[0]["skill_id"] == "axis_adapter"
    assert records[0]["description"] == "AXI stream width adapter"
    assert "retrieval_text" in records[0]["body"]
    assert "rtl/axis_adapter.v" in records[0]["body"]


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
    (skill / "compact_card.json").write_text(
        json.dumps(
            {
                "skill_id": "uart_tx",
                "name": "uart_tx",
                "core_function": "UART transmitter",
                "algorithm": "serial frame generation",
                "structure": ["start data stop bits"],
                "interface_signature": "uart",
                "granularity": "primitive",
                "project": "test",
                "keywords": ["uart", "transmitter"],
                "retrieval_text": "UART transmitter serial frame generation.",
            }
        ),
        encoding="utf-8",
    )
    (skill / "skill.json").write_text(
        json.dumps({"skill_id": "uart_tx", "rtl_files": ["rtl/uart_tx.v"]}),
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
    assert payload["compact_card_metrics"]["card_count"] >= 1
    assert payload["cases"][0]["first_relevant_rank"] == 1


def test_router_benchmark_reports_compact_card_metrics(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill = skills_root / "axis_adapter"
    skill.mkdir(parents=True)
    (skill / "compact_card.json").write_text(
        json.dumps(
            {
                "skill_id": "axis_adapter",
                "name": "axis_adapter",
                "core_function": "AXI stream width adapter",
                "algorithm": "width conversion",
                "structure": ["width converter"],
                "interface_signature": "AXIS -> AXIS",
                "granularity": "primitive",
                "project": "test",
                "keywords": ["axis", "adapter", "width"],
                "retrieval_text": "AXI stream width adapter for width conversion.",
            }
        ),
        encoding="utf-8",
    )
    (skill / "skill.json").write_text(
        json.dumps(
            {
                "skill_id": "axis_adapter",
                "name": "axis_adapter",
                "granularity": "primitive",
                "project": "test",
                "core_function": "AXI stream width adapter",
                "algorithm": "width conversion",
                "interface": {"input": "AXIS", "output": "AXIS"},
                "structure": ["width converter"],
                "parameters": [],
                "dependencies": [],
                "used_by": [],
                "rtl_files": ["rtl/axis_adapter.v"],
            }
        ),
        encoding="utf-8",
    )
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "axis_adapter_case",
                        "query_plan": {
                            "intent": "AXI stream width adapter",
                            "positive_terms": ["axis", "width"],
                            "negative_terms": [],
                            "likely_categories": ["primitive"],
                            "likely_interfaces": ["axis"],
                            "required_features": ["adapter"],
                        },
                        "relevant_skill_ids": ["axis_adapter"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = run_benchmark(dataset, skills_root, limit=5)
    assert payload["metrics"]["hit_at_1"] == 1.0
    assert payload["compact_card_metrics"]["card_count"] == 1
    assert payload["compact_card_metrics"]["avg_text_length"] <= 60
    assert payload["compact_card_metrics"]["keyword_match_rate"] == 1.0


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
    assert payload["case_count"] == 14
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
    assert "avg_text_length=" in table_run.stdout
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
    assert payload["source_path"].endswith("skills/uart_tx/rtl/uart_tx.v")
