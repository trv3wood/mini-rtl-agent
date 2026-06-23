`timescale 1ns/1ps

module axis_pipeline_fifo #(
    parameter integer DATA_WIDTH = 8,
    parameter integer PIPELINE = 2
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire [DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,
    output wire [DATA_WIDTH-1:0] m_axis_tdata,
    output wire                  m_axis_tvalid,
    input  wire                  m_axis_tready
);
    reg [DATA_WIDTH-1:0] data0;
    reg [DATA_WIDTH-1:0] data1;
    reg valid0;
    reg valid1;

    wire ready1 = !valid1 || m_axis_tready;
    wire ready0 = !valid0 || ready1;

    assign s_axis_tready = ready0;
    assign m_axis_tdata = data1;
    assign m_axis_tvalid = valid1;

    always @(posedge clk) begin
        if (rst) begin
            data0 <= {DATA_WIDTH{1'b0}};
            data1 <= {DATA_WIDTH{1'b0}};
            valid0 <= 1'b0;
            valid1 <= 1'b0;
        end else begin
            if (ready1) begin
                data1 <= data0;
                valid1 <= valid0;
            end
            if (ready0) begin
                data0 <= s_axis_tdata;
                valid0 <= s_axis_tvalid;
            end
        end
    end
endmodule
