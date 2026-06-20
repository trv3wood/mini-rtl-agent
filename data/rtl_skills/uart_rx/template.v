`timescale 1ns/1ps

module uart_rx #(
    parameter integer DATA_WIDTH = 8,
    parameter integer CLKS_PER_BIT = 8
) (
    input  wire clk,
    input  wire rst,
    output reg  [DATA_WIDTH-1:0] m_axis_tdata,
    output reg  m_axis_tvalid,
    input  wire m_axis_tready,
    input  wire rxd,
    output reg  busy,
    output reg  overrun_error,
    output reg  frame_error,
    input  wire [15:0] prescale
);
    localparam S_IDLE = 0, S_START = 1, S_DATA = 2, S_STOP = 3;
    reg [1:0] state;
    reg [15:0] clk_count;
    reg [$clog2(DATA_WIDTH)-1:0] bit_index;
    wire [15:0] bit_cycles = (prescale == 0) ? CLKS_PER_BIT[15:0] : prescale;

    always @(posedge clk) begin
        if (rst) begin
            state <= S_IDLE;
            clk_count <= 0;
            bit_index <= 0;
            m_axis_tdata <= 0;
            m_axis_tvalid <= 0;
            busy <= 0;
            overrun_error <= 0;
            frame_error <= 0;
        end else begin
            if (m_axis_tvalid && m_axis_tready) m_axis_tvalid <= 0;
            case (state)
                S_IDLE: begin
                    busy <= 0;
                    clk_count <= 0;
                    bit_index <= 0;
                    if (!rxd) begin busy <= 1; state <= S_START; end
                end
                S_START: begin
                    if (clk_count == (bit_cycles >> 1)) begin
                        if (!rxd) begin clk_count <= 0; state <= S_DATA; end
                        else state <= S_IDLE;
                    end else clk_count <= clk_count + 1'b1;
                end
                S_DATA: begin
                    if (clk_count == bit_cycles - 1) begin
                        clk_count <= 0;
                        m_axis_tdata[bit_index] <= rxd;
                        if (bit_index == DATA_WIDTH-1) state <= S_STOP;
                        else bit_index <= bit_index + 1'b1;
                    end else clk_count <= clk_count + 1'b1;
                end
                S_STOP: begin
                    if (clk_count == bit_cycles - 1) begin
                        frame_error <= !rxd;
                        overrun_error <= m_axis_tvalid && !m_axis_tready;
                        m_axis_tvalid <= rxd;
                        busy <= 0;
                        clk_count <= 0;
                        state <= S_IDLE;
                    end else clk_count <= clk_count + 1'b1;
                end
            endcase
        end
    end
endmodule
