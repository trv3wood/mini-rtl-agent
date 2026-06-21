`timescale 1ns/1ps

module tb_round_robin_arbiter;
    reg clk = 0;
    reg rst = 1;
    reg [3:0] request = 4'b1111;
    reg acknowledge = 0;
    wire [3:0] grant;
    wire grant_valid;
    wire [1:0] grant_encoded;

    round_robin_arbiter #(.PORTS(4)) dut (
        .clk(clk), .rst(rst), .request(request), .acknowledge(acknowledge),
        .grant(grant), .grant_valid(grant_valid), .grant_encoded(grant_encoded)
    );

    always #5 clk = ~clk;

    task expect_grant;
        input [3:0] expected;
        begin
            @(negedge clk);
            if (grant !== expected || !grant_valid) $fatal(1, "bad grant expected=%b got=%b", expected, grant);
            acknowledge <= 1;
            @(posedge clk);
            acknowledge <= 0;
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        rst <= 0;
        expect_grant(4'b0001);
        expect_grant(4'b0010);
        expect_grant(4'b0100);
        expect_grant(4'b1000);
        request <= 4'b0100;
        @(posedge clk);
        @(negedge clk);
        if (grant !== 4'b0100) $fatal(1, "sparse request grant failed");
        $display("PASS round_robin_arbiter");
        $finish;
    end
endmodule
