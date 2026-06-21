`timescale 1ns/1ps

module example_sync_fifo(input wire clk, input wire rst, input wire wr_en, input wire [7:0] wr_data, input wire rd_en, output wire [7:0] rd_data, output wire full, output wire empty);
    wire [2:0] count;
    sync_fifo #(.DATA_WIDTH(8), .DEPTH(4), .ADDR_WIDTH(2)) u_fifo (.clk(clk), .rst(rst), .wr_en(wr_en), .wr_data(wr_data), .rd_en(rd_en), .rd_data(rd_data), .full(full), .empty(empty), .count(count));
endmodule
