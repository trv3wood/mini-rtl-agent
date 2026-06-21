`timescale 1ns/1ps

module tb_async_fifo;
    reg wr_clk = 0, rd_clk = 0;
    reg wr_rst = 1, rd_rst = 1;
    reg wr_en = 0, rd_en = 0;
    reg [7:0] wr_data = 0;
    wire [7:0] rd_data;
    wire wr_full, rd_empty;

    async_fifo dut (.wr_clk(wr_clk), .wr_rst(wr_rst), .wr_en(wr_en), .wr_data(wr_data), .wr_full(wr_full), .rd_clk(rd_clk), .rd_rst(rd_rst), .rd_en(rd_en), .rd_data(rd_data), .rd_empty(rd_empty));
    always #3 wr_clk = ~wr_clk;
    always #5 rd_clk = ~rd_clk;

    task write_word(input [7:0] data); begin
        @(negedge wr_clk); wr_data = data; wr_en = 1;
        @(posedge wr_clk); #1 wr_en = 0;
    end endtask
    task read_word(input [7:0] expected);
        integer timeout;
        begin
            timeout = 0;
            while (rd_empty && timeout < 20) begin
                @(posedge rd_clk);
                timeout = timeout + 1;
            end
            if (rd_empty) $fatal(1, "fifo stayed empty while expecting %h", expected);
            @(negedge rd_clk); rd_en = 1;
            @(posedge rd_clk); #1 rd_en = 0;
            if (rd_data !== expected) $fatal(1, "read expected %h got %h", expected, rd_data);
        end
    endtask

    initial begin
        #10000;
        $fatal(1, "global timeout");
    end

    initial begin
        repeat (3) @(posedge wr_clk); wr_rst = 0;
        repeat (3) @(posedge rd_clk); rd_rst = 0;
        write_word(8'ha1); write_word(8'ha2); write_word(8'ha3);
        read_word(8'ha1); read_word(8'ha2); read_word(8'ha3);
        $display("PASS async_fifo");
        $finish;
    end
endmodule
