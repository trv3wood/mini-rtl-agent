.PHONY: demo skills architecture-demo skill-builder-demo clean

PYTHON ?= python3

skills:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m src.rtl_skill_index --run-examples

architecture-demo:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m architecture "Design a UART receiver with FIFO buffering" --output-dir work/architecture

skill-builder-demo:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m skill_builder build work/sample_rtl_repo --output work/built_skills

clean:
	rm -rf work/generated work/reports work/architecture work/built_skills
