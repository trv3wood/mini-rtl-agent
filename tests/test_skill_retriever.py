from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.skill_retriever.cli import load_query_plan
from src.skill_retriever.models import QueryPlan
from src.skill_retriever.retriever import retrieve_skills
from src.skill_retriever.tools import retrieve_rtl_skills_impl


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
