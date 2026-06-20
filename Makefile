.PHONY: demo skills skill-builder-demo clean

PYTHON ?= python3
SPEC ?= "Create a UART transmitter with clk, rst, start, 8-bit data input, tx, busy, and done outputs. Use one start bit, 8 data bits LSB first, and one stop bit."

demo:
	$(PYTHON) -m src.agent --spec $(SPEC)

skills:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m src.rtl_skill_index --run-examples

skill-builder-demo:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m skill_builder build work/sample_rtl_repo --output work/built_skills

clean:
	rm -rf work/generated work/reports work/built_skills
