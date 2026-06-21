`timescale 1ns/1ps

module tb_uart_tx;
    reg clk = 0, rst = 1, valid = 0;
    reg [7:0] data = 8'ha5;
    wire ready, txd, busy;
    integer i;
    uart_tx dut (.clk(clk), .rst(rst), .s_axis_tdata(data), .s_axis_tvalid(valid), .s_axis_tready(ready), .txd(txd), .busy(busy), .prescale(16'd8));
    always #5 clk = ~clk;

    task expect_bit(input bit_value); begin
        if (txd !== bit_value) $fatal(1, "expected txd=%b got %b", bit_value, txd);
    end endtask

    initial begin
        #5000;
        $fatal(1, "global timeout");
    end

    initial begin
        repeat (3) @(posedge clk); rst = 0;
        @(negedge clk); valid = 1;
        @(negedge clk); valid = 0;
        wait(txd == 0);
        repeat (4) @(posedge clk); expect_bit(0);
        repeat (8) @(posedge clk);
        for (i = 0; i < 8; i = i + 1) begin
            expect_bit(data[i]);
            repeat (8) @(posedge clk);
        end
        expect_bit(1);
        wait(!busy);
        $display("PASS uart_tx");
        $finish;
    end
endmodule
