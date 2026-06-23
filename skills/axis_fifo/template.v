`timescale 1ns/1ps

module axis_fifo #(
    parameter integer DATA_WIDTH = 8,
    parameter integer DEPTH = 4,
    parameter integer ADDR_WIDTH = 2
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire [DATA_WIDTH-1:0] s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,
    output wire [DATA_WIDTH-1:0] m_axis_tdata,
    output wire                  m_axis_tvalid,
    input  wire                  m_axis_tready,
    output reg  [ADDR_WIDTH:0]   count
);
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    reg [ADDR_WIDTH-1:0] wr_ptr;
    reg [ADDR_WIDTH-1:0] rd_ptr;

    wire input_fire = s_axis_tvalid && s_axis_tready;
    wire output_fire = m_axis_tvalid && m_axis_tready;

    assign s_axis_tready = (count < DEPTH) || output_fire;
    assign m_axis_tvalid = (count != 0);
    assign m_axis_tdata = mem[rd_ptr];

    always @(posedge clk) begin
        if (rst) begin
            wr_ptr <= 0;
            rd_ptr <= 0;
            count <= 0;
        end else begin
            if (input_fire) begin
                mem[wr_ptr] <= s_axis_tdata;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (output_fire) begin
                rd_ptr <= rd_ptr + 1'b1;
            end
            case ({input_fire, output_fire})
                2'b10: count <= count + 1'b1;
                2'b01: count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end
endmodule
