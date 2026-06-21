`timescale 1ns/1ps

module example_axis_handshake_buffer(input wire clk, input wire rst, input wire [7:0] in_data, input wire in_valid, output wire in_ready, output wire [7:0] out_data, output wire out_valid, input wire out_ready);
    axis_handshake_buffer #(.DATA_WIDTH(8)) u_buf (.clk(clk), .rst(rst), .s_axis_tdata(in_data), .s_axis_tvalid(in_valid), .s_axis_tready(in_ready), .m_axis_tdata(out_data), .m_axis_tvalid(out_valid), .m_axis_tready(out_ready));
endmodule
