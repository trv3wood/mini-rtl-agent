`timescale 1ns/1ps

module axis_adapter #(
    parameter integer S_DATA_WIDTH = 8,
    parameter integer M_DATA_WIDTH = 16
) (
    input  wire                    clk,
    input  wire                    rst,
    input  wire [S_DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                    s_axis_tvalid,
    output wire                    s_axis_tready,
    output wire [M_DATA_WIDTH-1:0] m_axis_tdata,
    output wire                    m_axis_tvalid,
    input  wire                    m_axis_tready
);
    assign s_axis_tready = m_axis_tready;
    assign m_axis_tvalid = s_axis_tvalid;

    generate
        if (M_DATA_WIDTH >= S_DATA_WIDTH) begin : widen
            assign m_axis_tdata = {{(M_DATA_WIDTH-S_DATA_WIDTH){1'b0}}, s_axis_tdata};
        end else begin : narrow
            assign m_axis_tdata = s_axis_tdata[M_DATA_WIDTH-1:0];
        end
    endgenerate

    wire unused_clk = clk;
    wire unused_rst = rst;
endmodule
