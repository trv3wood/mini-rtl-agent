`timescale 1ns/1ps

module uart_tx #(
    parameter integer DATA_WIDTH = 8,
    parameter integer CLKS_PER_BIT = 8
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire [DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,
    output reg                   txd,
    output reg                   busy,
    input  wire [15:0]           prescale
);
    localparam S_IDLE = 0, S_START = 1, S_DATA = 2, S_STOP = 3;
    reg [1:0] state;
    reg [15:0] clk_count;
    reg [$clog2(DATA_WIDTH)-1:0] bit_index;
    reg [DATA_WIDTH-1:0] data_reg;
    wire [15:0] bit_cycles = (prescale == 0) ? CLKS_PER_BIT[15:0] : prescale;

    assign s_axis_tready = (state == S_IDLE);

    always @(posedge clk) begin
        if (rst) begin
            state <= S_IDLE;
            clk_count <= 0;
            bit_index <= 0;
            data_reg <= 0;
            txd <= 1'b1;
            busy <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    txd <= 1'b1;
                    busy <= 1'b0;
                    clk_count <= 0;
                    bit_index <= 0;
                    if (s_axis_tvalid) begin
                        data_reg <= s_axis_tdata;
                        busy <= 1'b1;
                        state <= S_START;
                    end
                end
                S_START: begin
                    txd <= 1'b0;
                    if (clk_count == bit_cycles - 1) begin clk_count <= 0; state <= S_DATA; end
                    else clk_count <= clk_count + 1'b1;
                end
                S_DATA: begin
                    txd <= data_reg[bit_index];
                    if (clk_count == bit_cycles - 1) begin
                        clk_count <= 0;
                        if (bit_index == DATA_WIDTH-1) state <= S_STOP;
                        else bit_index <= bit_index + 1'b1;
                    end else clk_count <= clk_count + 1'b1;
                end
                S_STOP: begin
                    txd <= 1'b1;
                    if (clk_count == bit_cycles - 1) begin clk_count <= 0; state <= S_IDLE; busy <= 1'b0; end
                    else clk_count <= clk_count + 1'b1;
                end
            endcase
        end
    end
endmodule
