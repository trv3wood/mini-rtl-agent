`timescale 1ns/1ps

module example_uart_tx(input wire clk, input wire rst, input wire [7:0] data, input wire valid, output wire ready, output wire txd, output wire busy);
    uart_tx #(.DATA_WIDTH(8), .CLKS_PER_BIT(8)) u_tx (.clk(clk), .rst(rst), .s_axis_tdata(data), .s_axis_tvalid(valid), .s_axis_tready(ready), .txd(txd), .busy(busy), .prescale(16'd8));
endmodule
