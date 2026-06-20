.PHONY: demo skills clean

PYTHON ?= python3
SPEC ?= "Create a UART transmitter with clk, rst, start, 8-bit data input, tx, busy, and done outputs. Use one start bit, 8 data bits LSB first, and one stop bit."

demo:
	$(PYTHON) -m src.agent --spec $(SPEC)

skills:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m src.rtl_skill_index --run-examples

clean:
	rm -rf work/generated work/reports
