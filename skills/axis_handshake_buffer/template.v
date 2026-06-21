`timescale 1ns/1ps

module axis_handshake_buffer #(
    parameter integer DATA_WIDTH = 8
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
    reg [DATA_WIDTH-1:0] data_reg;
    reg valid_reg;

    assign s_axis_tready = !valid_reg || m_axis_tready;
    assign m_axis_tdata = data_reg;
    assign m_axis_tvalid = valid_reg;

    always @(posedge clk) begin
        if (rst) begin
            valid_reg <= 1'b0;
            data_reg <= {DATA_WIDTH{1'b0}};
        end else if (s_axis_tready) begin
            valid_reg <= s_axis_tvalid;
            if (s_axis_tvalid) begin
                data_reg <= s_axis_tdata;
            end
        end
    end
endmodule
