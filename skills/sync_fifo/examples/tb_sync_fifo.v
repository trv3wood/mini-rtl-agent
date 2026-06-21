`timescale 1ns/1ps

module tb_sync_fifo;
    reg clk = 0;
    reg rst = 1;
    reg wr_en = 0;
    reg [7:0] wr_data = 0;
    reg rd_en = 0;
    wire [7:0] rd_data;
    wire full;
    wire empty;
    wire [2:0] count;

    sync_fifo dut (.clk(clk), .rst(rst), .wr_en(wr_en), .wr_data(wr_data), .rd_en(rd_en), .rd_data(rd_data), .full(full), .empty(empty), .count(count));
    always #5 clk = ~clk;

    task push(input [7:0] data); begin
        @(negedge clk); wr_data = data; wr_en = 1; rd_en = 0;
        @(posedge clk); #1 wr_en = 0;
    end endtask
    task pop(input [7:0] expected); begin
        @(negedge clk); rd_en = 1; wr_en = 0;
        @(posedge clk); #1 rd_en = 0;
        if (rd_data !== expected) $fatal(1, "pop expected %h got %h", expected, rd_data);
    end endtask

    initial begin
        repeat (2) @(posedge clk); rst = 0;
        if (!empty) $fatal(1, "fifo should be empty");
        push(8'h11); push(8'h22); push(8'h33); push(8'h44);
        if (!full || count !== 4) $fatal(1, "fifo should be full");
        pop(8'h11); pop(8'h22); pop(8'h33); pop(8'h44);
        if (!empty || count !== 0) $fatal(1, "fifo should drain empty");
        $display("PASS sync_fifo");
        $finish;
    end
endmodule
