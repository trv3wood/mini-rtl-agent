`timescale 1ns/1ps

module example_spi_master(input wire clk, input wire rst, input wire start, input wire [7:0] tx_data, input wire miso, output wire [7:0] rx_data, output wire sclk, output wire mosi, output wire cs_n);
    wire busy, done;
    spi_master #(.DATA_WIDTH(8), .CS_WIDTH(1)) u_spi (.clk(clk), .rst(rst), .start(start), .tx_data(tx_data), .rx_data(rx_data), .busy(busy), .done(done), .sclk(sclk), .mosi(mosi), .miso(miso), .cs_n(cs_n));
endmodule
