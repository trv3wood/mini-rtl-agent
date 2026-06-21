`timescale 1ns/1ps

module tb_i2c_master;
    reg clk = 0, rst = 1, arst = 0;
    reg [2:0] adr = 0;
    reg [7:0] dat_i = 0;
    wire [7:0] dat_o;
    reg we = 0, stb = 0, cyc = 0;
    wire ack, irq;
    reg scl_i = 1, sda_i = 1;
    wire scl_o, scl_oe, sda_o, sda_oe;
    i2c_master dut (.wb_clk_i(clk), .wb_rst_i(rst), .arst_i(arst), .wb_adr_i(adr), .wb_dat_i(dat_i), .wb_dat_o(dat_o), .wb_we_i(we), .wb_stb_i(stb), .wb_cyc_i(cyc), .wb_ack_o(ack), .wb_inta_o(irq), .scl_pad_i(scl_i), .scl_pad_o(scl_o), .scl_padoen_o(scl_oe), .sda_pad_i(sda_i), .sda_pad_o(sda_o), .sda_padoen_o(sda_oe));
    always #5 clk = ~clk;

    task wb_write(input [2:0] a, input [7:0] d); begin
        @(negedge clk); adr = a; dat_i = d; we = 1; stb = 1; cyc = 1;
        @(posedge clk); @(negedge clk); stb = 0; cyc = 0; we = 0;
    end endtask

    initial begin
        repeat (2) @(posedge clk); rst = 0;
        wb_write(3'd1, 8'h00);
        wb_write(3'd2, 8'h80);
        repeat (2) @(posedge clk);
        if (sda_oe !== 0) $fatal(1, "transfer should drive SDA low for zero data");
        wait(irq);
        if (scl_oe !== 1 || sda_oe !== 1) $fatal(1, "stop should release open-drain lines");
        $display("PASS i2c_master");
        $finish;
    end
endmodule
