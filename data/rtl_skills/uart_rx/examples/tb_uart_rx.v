`timescale 1ns/1ps

module tb_uart_rx;
    reg clk = 0, rst = 1, ready = 0, rxd = 1;
    wire [7:0] data;
    wire valid, busy, overrun_error, frame_error;
    integer i;
    reg [7:0] payload = 8'h5a;
    uart_rx dut (.clk(clk), .rst(rst), .m_axis_tdata(data), .m_axis_tvalid(valid), .m_axis_tready(ready), .rxd(rxd), .busy(busy), .overrun_error(overrun_error), .frame_error(frame_error), .prescale(16'd8));
    always #5 clk = ~clk;

    task drive_bit(input b); begin
        @(negedge clk);
        rxd = b;
        repeat (8) @(posedge clk);
    end endtask

    initial begin
        #5000;
        $fatal(1, "global timeout");
    end

    initial begin
        repeat (3) @(posedge clk); rst = 0;
        drive_bit(0);
        for (i = 0; i < 8; i = i + 1) drive_bit(payload[i]);
        drive_bit(1);
        wait(valid);
        if (data !== payload) $fatal(1, "rx expected %h got %h", payload, data);
        if (frame_error) $fatal(1, "unexpected frame_error");
        @(negedge clk); ready = 1;
        $display("PASS uart_rx");
        $finish;
    end
endmodule
