`timescale 1ns/1ps

module example_async_fifo(input wire wr_clk, input wire wr_rst, input wire wr_en, input wire [7:0] wr_data, output wire wr_full, input wire rd_clk, input wire rd_rst, input wire rd_en, output wire [7:0] rd_data, output wire rd_empty);
    async_fifo #(.DATA_WIDTH(8), .ADDR_WIDTH(2)) u_fifo (.wr_clk(wr_clk), .wr_rst(wr_rst), .wr_en(wr_en), .wr_data(wr_data), .wr_full(wr_full), .rd_clk(rd_clk), .rd_rst(rd_rst), .rd_en(rd_en), .rd_data(rd_data), .rd_empty(rd_empty));
endmodule
