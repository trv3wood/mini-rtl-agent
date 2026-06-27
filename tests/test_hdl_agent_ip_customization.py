from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.hdl_agent.workflow import run_hdl_agent
from src.utils.llm import LLMConfig, OpenAICompatibleLLM


@dataclass(frozen=True)
class IPCustomizationCase:
    case_id: str
    request: str
    expected_skill: str
    expected_module: str
    query_plan: dict[str, object]
    hdl: str


IP_CUSTOMIZATION_CASES = [
    IPCustomizationCase(
        case_id="uart_tx_baud_prescale",
        request=(
            "Create IP named custom_uart_tx8 that sends one byte on an asynchronous serial line, "
            "with valid/ready input flow control and a busy output."
        ),
        expected_skill="uart_tx",
        expected_module="custom_uart_tx8",
        query_plan={
            "intent": "custom asynchronous serial byte transmitter with input handshake",
            "positive_terms": ["uart", "transmitter", "tx", "serial", "baud", "ready", "valid", "busy"],
            "negative_terms": [],
            "likely_categories": ["uart", "serial"],
            "likely_interfaces": ["ready_valid_handshake", "busy_signal"],
            "required_features": ["start_bit", "stop_bit", "baud_prescale", "ready_valid_input"],
        },
        hdl="""
module custom_uart_tx8 #(
  parameter integer CLKS_PER_BIT = 16
) (
  input wire clk,
  input wire rst,
  input wire [7:0] s_data,
  input wire s_valid,
  output wire s_ready,
  output reg txd,
  output wire busy
);
  reg [9:0] shreg;
  reg [3:0] bit_idx;
  reg [15:0] clk_cnt;
  reg active;

  assign s_ready = !active;
  assign busy = active;

  always @(posedge clk) begin
    if (rst) begin
      shreg <= 10'h3ff;
      bit_idx <= 4'd0;
      clk_cnt <= 16'd0;
      active <= 1'b0;
      txd <= 1'b1;
    end else if (!active) begin
      txd <= 1'b1;
      if (s_valid) begin
        shreg <= {1'b1, s_data, 1'b0};
        bit_idx <= 4'd0;
        clk_cnt <= 16'd0;
        active <= 1'b1;
      end
    end else begin
      txd <= shreg[0];
      if (clk_cnt == CLKS_PER_BIT-1) begin
        clk_cnt <= 16'd0;
        shreg <= {1'b1, shreg[9:1]};
        if (bit_idx == 4'd9) begin
          active <= 1'b0;
        end else begin
          bit_idx <= bit_idx + 1'b1;
        end
      end else begin
        clk_cnt <= clk_cnt + 1'b1;
      end
    end
  end
endmodule
""",
    ),
    IPCustomizationCase(
        case_id="axis_register_slice_32",
        request=(
            "Create IP named custom_axis_reg32 that inserts one elastic ready/valid register "
            "between a 32-bit stream source and sink."
        ),
        expected_skill="axis_register",
        expected_module="custom_axis_reg32",
        query_plan={
            "intent": "custom AXI stream one-cycle elastic register slice",
            "positive_terms": [
                "axi_stream",
                "axis",
                "register",
                "skid_buffer",
                "ready_valid",
                "tdata",
                "tvalid",
                "tready",
            ],
            "negative_terms": [],
            "likely_categories": ["axi_stream"],
            "likely_interfaces": ["ready_valid_interface"],
            "required_features": ["register_slice", "skid_buffer", "datapath_registers"],
        },
        hdl="""
module custom_axis_reg32 #(
  parameter integer DATA_WIDTH = 32
) (
  input wire clk,
  input wire rst,
  input wire [DATA_WIDTH-1:0] s_axis_tdata,
  input wire s_axis_tvalid,
  output wire s_axis_tready,
  output wire [DATA_WIDTH-1:0] m_axis_tdata,
  output wire m_axis_tvalid,
  input wire m_axis_tready
);
  reg [DATA_WIDTH-1:0] data_reg;
  reg valid_reg;

  assign s_axis_tready = !valid_reg || m_axis_tready;
  assign m_axis_tdata = data_reg;
  assign m_axis_tvalid = valid_reg;

  always @(posedge clk) begin
    if (rst) begin
      data_reg <= {DATA_WIDTH{1'b0}};
      valid_reg <= 1'b0;
    end else if (s_axis_tready) begin
      data_reg <= s_axis_tdata;
      valid_reg <= s_axis_tvalid;
    end
  end
endmodule
""",
    ),
    IPCustomizationCase(
        case_id="priority_encoder_8",
        request=(
            "Create IP named custom_priority8 that converts an 8-bit request vector into "
            "a valid flag and encoded winning index."
        ),
        expected_skill="priority_encoder",
        expected_module="custom_priority8",
        query_plan={
            "intent": "custom request vector priority index encoder",
            "positive_terms": [
                "priority_encoder",
                "binary_encoding",
                "valid_flag",
                "input_unencoded",
                "output_encoded",
            ],
            "negative_terms": [],
            "likely_categories": ["control", "arbiter"],
            "likely_interfaces": ["vector_to_index"],
            "required_features": ["priority_select", "valid_flag", "encoded_index"],
        },
        hdl="""
module custom_priority8 (
  input wire [7:0] request,
  output reg valid,
  output reg [2:0] index
);
  integer i;
  always @* begin
    valid = 1'b0;
    index = 3'd0;
    for (i = 7; i >= 0; i = i - 1) begin
      if (request[i]) begin
        valid = 1'b1;
        index = i[2:0];
      end
    end
  end
endmodule
""",
    ),
    IPCustomizationCase(
        case_id="onehot_encoder_8",
        request=(
            "Create IP named custom_onehot8 that expands a 3-bit selected index into "
            "an enabled 8-bit one-hot output."
        ),
        expected_skill="prim_onehot_enc",
        expected_module="custom_onehot8",
        query_plan={
            "intent": "custom binary index to one hot decoder",
            "positive_terms": ["onehot_encoder", "binary_to_onehot", "one-hot", "onehot", "in_i", "out_o"],
            "negative_terms": [],
            "likely_categories": ["codec", "ip"],
            "likely_interfaces": ["binary_to_onehot"],
            "required_features": ["enable", "onehot_output", "width_conversion"],
        },
        hdl="""
module custom_onehot8 (
  input wire [2:0] index,
  input wire enable,
  output reg [7:0] onehot
);
  always @* begin
    onehot = 8'b0000_0000;
    if (enable) begin
      onehot[index] = 1'b1;
    end
  end
endmodule
""",
    ),
    IPCustomizationCase(
        case_id="reset_sync_3stage",
        request=(
            "Create IP named custom_reset_sync3 that asynchronously asserts reset and "
            "releases it through three clocked stages."
        ),
        expected_skill="reset_synchronizer",
        expected_module="custom_reset_sync3",
        query_plan={
            "intent": "custom reset synchronizer with async assertion and sync release",
            "positive_terms": [
                "reset",
                "reset synchronizer",
                "cdc",
                "asynchronous assertion",
                "synchronous deassertion",
                "synchronizer",
                "stages",
            ],
            "negative_terms": [],
            "likely_categories": ["reset", "control"],
            "likely_interfaces": ["reset_signal", "cdc"],
            "required_features": ["async_assert_sync_release", "multi_stage_flip_flop_synchronizer"],
        },
        hdl="""
module custom_reset_sync3 (
  input wire clk,
  input wire arst,
  output wire srst
);
  reg [2:0] sync_reg;

  assign srst = sync_reg[2];

  always @(posedge clk or posedge arst) begin
    if (arst) begin
      sync_reg <= 3'b111;
    end else begin
      sync_reg <= {sync_reg[1:0], 1'b0};
    end
  end
endmodule
""",
    ),
]


class IPCustomizationLLM:
    def __init__(self, case: IPCustomizationCase) -> None:
        self.case = case
        self.text_prompts: list[list[dict[str, str]]] = []

    def complete_structured(self, messages: list[dict[str, str]], schema, *, temperature: float = 0.0):
        assert self.case.request in messages[-1]["content"]
        return schema.model_validate(self.case.query_plan)

    def complete_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> str:
        self.text_prompts.append(messages)
        prompt = messages[-1]["content"]
        assert f"Selected skill: {self.case.expected_skill}" in prompt
        assert "skill.json" in prompt
        assert "compact_card.json" in prompt
        assert "RTL source" in prompt
        return f"```verilog\n{self.case.hdl.strip()}\n```"


@pytest.mark.parametrize("case", IP_CUSTOMIZATION_CASES, ids=[case.case_id for case in IP_CUSTOMIZATION_CASES])
def test_hdl_agent_customizes_ip_from_existing_skills(case: IPCustomizationCase, tmp_path: Path) -> None:
    if not shutil.which("iverilog"):
        pytest.skip("iverilog is required for HDL syntax validation")

    output = tmp_path / f"{case.expected_module}.v"
    result = run_hdl_agent(
        case.request,
        llm=IPCustomizationLLM(case),
        skills_root=Path("skills"),
        output_path=output,
        limit=8,
        max_retries=1,
    )

    generated = output.read_text(encoding="utf-8")
    assert result.selected_skill.name == case.expected_skill
    assert result.retrieved["results"][0]["name"] == case.expected_skill
    assert result.repair_attempts == 0
    assert f"module {case.expected_module}" in generated
    assert "```" not in generated


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_IP_CUSTOMIZATION") != "1",
    reason="set RUN_LIVE_LLM_IP_CUSTOMIZATION=1 to run the real LLM IP customization smoke",
)
def test_live_llm_ip_customization_smoke(tmp_path: Path) -> None:
    if not shutil.which("iverilog"):
        pytest.skip("iverilog is required for HDL syntax validation")

    try:
        config = LLMConfig.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))

    output = tmp_path / "live_priority8.v"
    result = run_hdl_agent(
        (
            "Create a synthesizable module named live_priority8 by customizing the available "
            "priority encoder skill. It should accept an 8-bit request vector and produce a "
            "valid flag plus a 3-bit encoded winning index."
        ),
        llm=OpenAICompatibleLLM(config),
        skills_root=Path("skills"),
        output_path=output,
        limit=8,
        max_retries=3,
    )

    assert result.selected_skill.name == "priority_encoder"
    assert output.exists()
    assert "module" in output.read_text(encoding="utf-8")
