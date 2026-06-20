`timescale 1ns/1ps

module tb_spi_master;
    reg clk = 0, rst = 1, start = 0;
    reg [7:0] tx_data = 8'ha6;
    wire [7:0] rx_data;
    wire busy, done, sclk, mosi;
    reg miso = 0;
    wire cs_n;
    reg [7:0] response = 8'h3c;
    integer idx;

    spi_master dut (.clk(clk), .rst(rst), .start(start), .tx_data(tx_data), .rx_data(rx_data), .busy(busy), .done(done), .sclk(sclk), .mosi(mosi), .miso(miso), .cs_n(cs_n));
    always #5 clk = ~clk;

    initial begin
        idx = 7;
        repeat (2) @(posedge clk); rst = 0;
        @(negedge clk); miso = response[idx]; start = 1;
        @(negedge clk); start = 0;
        while (!done) begin
            @(negedge clk);
            if (busy && idx > 0) begin
                idx = idx - 1;
                miso = response[idx];
            end
        end
        if (rx_data !== response) $fatal(1, "spi rx expected %h got %h", response, rx_data);
        if (!cs_n) $fatal(1, "cs_n should release");
        $display("PASS spi_master");
        $finish;
    end
endmodule
