`timescale 1ns/1ps

module axis_srl_fifo #(
    parameter integer DATA_WIDTH = 8,
    parameter integer DEPTH = 4
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
    reg [DATA_WIDTH-1:0] data [0:DEPTH-1];
    reg [31:0] count;
    integer i;

    wire input_fire = s_axis_tvalid && s_axis_tready;
    wire output_fire = m_axis_tvalid && m_axis_tready;
    wire [31:0] next_count = count + (input_fire ? 1 : 0) - (output_fire ? 1 : 0);

    assign s_axis_tready = (count < DEPTH) || output_fire;
    assign m_axis_tvalid = (count != 0);
    assign m_axis_tdata = data[0];

    always @(posedge clk) begin
        if (rst) begin
            count <= 0;
            for (i = 0; i < DEPTH; i = i + 1) begin
                data[i] <= {DATA_WIDTH{1'b0}};
            end
        end else begin
            if (output_fire) begin
                for (i = 0; i < DEPTH-1; i = i + 1) begin
                    data[i] <= data[i+1];
                end
            end
            if (input_fire) begin
                if (output_fire) begin
                    data[count-1] <= s_axis_tdata;
                end else begin
                    data[count] <= s_axis_tdata;
                end
            end
            count <= next_count;
        end
    end
endmodule
