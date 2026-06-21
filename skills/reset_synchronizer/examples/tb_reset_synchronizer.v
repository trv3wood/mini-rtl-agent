`timescale 1ns/1ps

module tb_reset_synchronizer;
    reg clk = 0;
    reg rst_in = 1;
    wire rst_out;

    reset_synchronizer #(.STAGES(2), .RESET_ACTIVE_LEVEL(1)) dut (
        .clk(clk), .rst_in(rst_in), .rst_out(rst_out)
    );

    always #5 clk = ~clk;

    initial begin
        #3;
        if (rst_out !== 1'b1) $fatal(1, "rst_out should assert promptly");
        rst_in = 0;
        #1;
        if (rst_out !== 1'b1) $fatal(1, "rst_out released too early");
        @(posedge clk);
        if (rst_out !== 1'b1) $fatal(1, "rst_out released after one stage only");
        @(posedge clk);
        @(negedge clk);
        if (rst_out !== 1'b0) $fatal(1, "rst_out did not release after STAGES cycles");
        rst_in = 1;
        #1;
        if (rst_out !== 1'b1) $fatal(1, "rst_out did not assert asynchronously");
        $display("PASS reset_synchronizer");
        $finish;
    end
endmodule
