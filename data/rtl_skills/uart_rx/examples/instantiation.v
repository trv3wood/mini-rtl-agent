`timescale 1ns/1ps

module example_uart_rx(input wire clk, input wire rst, input wire rxd, output wire [7:0] data, output wire valid);
    wire busy, overrun_error, frame_error;
    uart_rx #(.DATA_WIDTH(8), .CLKS_PER_BIT(8)) u_rx (.clk(clk), .rst(rst), .m_axis_tdata(data), .m_axis_tvalid(valid), .m_axis_tready(1'b1), .rxd(rxd), .busy(busy), .overrun_error(overrun_error), .frame_error(frame_error), .prescale(16'd8));
endmodule
