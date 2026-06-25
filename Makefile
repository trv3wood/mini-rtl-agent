.PHONY: demo skills skill-builder-demo router-benchmark skillrouter-benchmark-dry-run skillrouter-report-existing skillrouter-status clean

PYTHON ?= python3
SKILLS_ROOT ?= skills
ROUTER_BENCHMARK ?= benchmarks/router_benchmark.json
SKILLROUTER_ROOT ?= external/SkillRouter
SKILLROUTER_WORK_DIR ?= work/skillrouter_benchmark
SKILLROUTER_MODE ?= pipeline
SKILLROUTER_EXTERNAL_JSON ?= $(SKILLROUTER_ROOT)/outputs/local_rtl_benchmark/reranked/easy.json
SKILLROUTER_REPORT_MD ?= work/reports/skillrouter_benchmark.md
SKILLROUTER_REPORT_JSON ?= work/reports/skillrouter_benchmark.json
SKILLROUTER_STATUS_MD ?= work/reports/skillrouter_status.md
SKILLROUTER_STATUS_JSON ?= work/reports/skillrouter_status.json

skills:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m src.skill_builder.validate_minimal_skills $(SKILLS_ROOT)

skill-builder-demo:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m skill_builder build work/sample_rtl_repo --output work/built_skills --clean

router-benchmark:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m skill_retriever benchmark $(ROUTER_BENCHMARK) --skills-root $(SKILLS_ROOT) --limit 10

skillrouter-benchmark-dry-run:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m skill_retriever run-skillrouter-benchmark $(ROUTER_BENCHMARK) \
		--skills-root $(SKILLS_ROOT) \
		--external-root $(SKILLROUTER_ROOT) \
		--work-dir $(SKILLROUTER_WORK_DIR) \
		--mode $(SKILLROUTER_MODE) \
		--dry-run

skillrouter-report-existing:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m skill_retriever compare-skillrouter-benchmark $(ROUTER_BENCHMARK) \
		--skills-root $(SKILLS_ROOT) \
		--external-json $(SKILLROUTER_EXTERNAL_JSON) \
		--report-md $(SKILLROUTER_REPORT_MD) \
		--report-json $(SKILLROUTER_REPORT_JSON)

skillrouter-status:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m skill_retriever skillrouter-status \
		--report-md $(SKILLROUTER_STATUS_MD) \
		--report-json $(SKILLROUTER_STATUS_JSON)

clean:
	rm -rf work/generated work/reports work/built_skills
